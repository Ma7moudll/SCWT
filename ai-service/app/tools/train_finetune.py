"""Fine-tune the classifier on the simulated-station-pilot dataset and compare
baseline (served artifact) vs fine-tuned model on a held-out pilot test split.

The served `models/model.onnx` is NOT replaced here — the tool only produces and
reports a candidate artifact (`data/checkpoints/model_finetuned.onnx`). Going
live with a model swap is a separate, explicit decision that requires the
fine-tuned model to clearly demonstrate an improvement with justification.

    python -m app.tools.train_finetune [--eval-only]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from .calibrate import _split_samples
from ..training.train import (
    CLASSES,
    ClassifyNet,
    WasteImageDataset,
    _device,
    evaluate_onnx,
    evaluate_torch,
    export_onnx,
    load_onnx_session,
    make_transforms,
    measure_latency,
    train_epoch,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", default="models/model.onnx", help="served baseline")
    p.add_argument("--checkpoint", default="data/checkpoints/model_final.pt")
    p.add_argument("--splits", default="data/station_capture_splits")
    p.add_argument("--export", default="data/checkpoints/model_finetuned.onnx")
    p.add_argument("--report", default="reports/finetune_report.md")
    p.add_argument("--epochs", type=int, default=6)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--eval-only", action="store_true",
                   help="re-evaluate an existing fine-tuned artifact + rewrite report")
    return p.parse_args(argv)


def _load_split(splits_root: Path, name: str):
    root = splits_root / name
    samples = _split_samples(root)
    if not samples:
        raise SystemExit(f"empty split {root} — run split_dataset first")
    return samples


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    device = _device()

    splits_root = Path(args.splits)
    train_samples = _load_split(splits_root, "train")
    val_samples = _load_split(splits_root, "val")
    test_samples = _load_split(splits_root, "test")

    print(f"[DATA] train={len(train_samples)} val={len(val_samples)} "
          f"test={len(test_samples)} (device {device})")

    # -- baseline: served artifact on the pilot test split -------------------
    session_base = load_onnx_session(Path(args.model))
    base_metrics = evaluate_onnx(session_base, test_samples)

    # -- fine-tuned candidate ------------------------------------------------
    export_path = Path(args.export)
    model = ClassifyNet(num_classes=len(CLASSES))
    checkpoint = Path(args.checkpoint)
    if not checkpoint.exists():
        raise SystemExit(f"checkpoint missing: {checkpoint}")
    model.load_state_dict(torch.load(checkpoint, map_location="cpu"))
    print(f"[MODEL] loaded checkpoint {checkpoint}")

    if not args.eval_only:
        train_transform, val_transform = make_transforms()
        train_loader = DataLoader(WasteImageDataset(train_samples, train_transform),
                                  batch_size=args.batch_size, shuffle=True, num_workers=0)
        val_loader = DataLoader(WasteImageDataset(val_samples, val_transform),
                                batch_size=args.batch_size, shuffle=False, num_workers=0)

        for name, param in model.features.named_parameters():
            param.requires_grad_(False)
        for name, param in model.features.named_parameters():
            if name.startswith("11."):  # last InvertedResidual block
                param.requires_grad_(True)
        for param in model.head.parameters():
            param.requires_grad_(True)
        model = model.to(device)
        criterion = nn.CrossEntropyLoss()
        optimizer = torch.optim.AdamW(
            [p for p in model.parameters() if p.requires_grad],
            lr=args.lr, weight_decay=1e-4,
        )

        best_val = -1.0
        for epoch in range(1, args.epochs + 1):
            loss, acc = train_epoch(model, train_loader, criterion, optimizer, device)
            val_acc, _, _ = evaluate_torch(model, val_loader, device)
            print(f"[FT] epoch {epoch}/{args.epochs} loss={loss:.4f} "
                  f"acc={acc:.4f} val_acc={val_acc:.4f}")
            best_val = max(best_val, val_acc)
        print(f"[FT] best val_acc {best_val:.4f}")

        model = model.cpu().eval()
        export_onnx(model, export_path)
        print(f"[EXPORT] {export_path}")

    if not export_path.exists():
        raise SystemExit(f"fine-tuned export missing: {export_path} — run without --eval-only")
    session_finetuned = load_onnx_session(export_path)
    ft_metrics = evaluate_onnx(session_finetuned, test_samples)
    ft_latency = measure_latency(session_finetuned, test_samples[0].path)
    base_latency = measure_latency(session_base, test_samples[0].path)

    macro = lambda m: float(np.mean(m["f1"]))
    lines = [
        "# Fine-tuning report — baseline vs fine-tuned (pilot test)",
        "",
        "**WARNING:** These results validate the training/validation pipeline "
        "under simulated camera distribution shift. They do **NOT** establish "
        "performance on the real EcoLoop station camera.",
        "",
        f"- Baseline: served `{args.model}` (TrashNet-trained, untouched).",
        f"- Candidate: fine-tuned on `{splits_root}/train` "
        f"(source=simulated-station-pilot, seed {args.seed}, "
        f"eager head + last-block, {args.epochs} epochs, lr={args.lr}).",
        f"- Test: `{splits_root}/test` (n={len(test_samples)}).",
        "",
        "| model | accuracy | macro-F1 | conf mean | size | latency ms (mean/med/p95) |",
        "|---|---|---|---|---|---|",
        f"| baseline | {base_metrics['accuracy']:.4f} | {macro(base_metrics):.4f} | "
        f"{base_metrics['mean_confidence']:.4f} | {Path(args.model).stat().st_size / 1e6:.2f} MB | "
        f"{base_latency['mean_ms']:.1f}/{base_latency['median_ms']:.1f}/{base_latency['p95_ms']:.1f} |",
        f"| fine-tuned | {ft_metrics['accuracy']:.4f} | {macro(ft_metrics):.4f} | "
        f"{ft_metrics['mean_confidence']:.4f} | {export_path.stat().st_size / 1e6:.2f} MB | "
        f"{ft_latency['mean_ms']:.1f}/{ft_latency['median_ms']:.1f}/{ft_latency['p95_ms']:.1f} |",
        "",
        "## Fine-tuned per-class (pilot test)",
        "",
        "| class | precision | recall | f1 | support |",
        "|---|---|---|---|---|",
    ]
    for i, cls in enumerate(CLASSES):
        lines.append(f"| {cls} | {ft_metrics['precision'][i]:.3f} | "
                     f"{ft_metrics['recall'][i]:.3f} | {ft_metrics['f1'][i]:.3f} | "
                     f"{ft_metrics['support'][i]} |")
    lines += [
        "",
        "## Decision",
        "",
        f"The served `models/model.onnx` is "
        f"**{'retained' if base_metrics['accuracy'] >= ft_metrics['accuracy'] - 0.001 else 'reconsiderable'}** "
        "for now: swapping it live is a separate, explicit decision that needs "
        "a clear, justified improvement plus re-validation of the E2E chain.",
        "",
    ]
    out_report = Path(args.report)
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"Wrote {out_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())