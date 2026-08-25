"""Compare the served MobileNetV3-Small classifier against one lightweight
alternative (SqueezeNet1.1) on the pilot test split.

SqueezeNet1.1 is chosen because it is small (~5 MB) and CPU-friendly, the same
deployment class as MobileNetV3-Small. This is a shipping-agnostic comparison:
nothing is swapped in the live service.

    python -m app.tools.model_compare [--eval-only]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torchvision.models import SqueezeNet1_1_Weights, squeezenet1_1

from .calibrate import _split_samples
from ..training.dataset import CLASSES
from ..training.train import (
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
    p.add_argument("--splits", default="data/station_capture_splits")
    p.add_argument("--export", default="data/checkpoints/model_squeezenet.onnx")
    p.add_argument("--report", default="reports/model_compare.md")
    p.add_argument("--epochs", type=int, default=6)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--eval-only", action="store_true")
    return p.parse_args(argv)


def _build_squeezenet(num_classes: int) -> nn.Module:
    net = squeezenet1_1(weights=SqueezeNet1_1_Weights.IMAGENET1K_V1)
    net.classifier[1] = nn.Conv2d(net.classifier[1].in_channels, num_classes, kernel_size=1)
    for p in net.features.parameters():
        p.requires_grad_(False)
    for p in net.classifier.parameters():
        p.requires_grad_(True)
    return net


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    device = _device()

    splits_root = Path(args.splits)
    train_samples = _split_samples(splits_root / "train")
    val_samples = _split_samples(splits_root / "val")
    test_samples = _split_samples(splits_root / "test")
    print(f"[DATA] train={len(train_samples)} val={len(val_samples)} test={len(test_samples)}")

    # metric helpers
    macro = lambda m: float(np.mean(m["f1"]))
    rows: list[dict] = []

    # --- baseline: served MobileNetV3-Small ---------------------------------
    session_base = load_onnx_session(Path(args.model))
    base = evaluate_onnx(session_base, test_samples)
    base_lat = measure_latency(session_base, test_samples[0].path)
    rows.append({
        "name": "MobileNetV3-Small (served)",
        "artifact": Path(args.model).stem,
        "accuracy": base["accuracy"], "macro_f1": macro(base),
        "mean_conf": base["mean_confidence"],
        "size_mb": Path(args.model).stat().st_size / 1e6,
        "latency": f"{base_lat['mean_ms']:.1f}/{base_lat['median_ms']:.1f}/{base_lat['p95_ms']:.1f}",
        "f1": base["f1"], "support": base["support"],
    })

    # --- candidate: SqueezeNet1.1 -------------------------------------------
    export_path = Path(args.export)
    net = _build_squeezenet(num_classes=len(CLASSES)).to(device)
    if not args.eval_only:
        train_transform, val_transform = make_transforms()
        train_loader = DataLoader(WasteImageDataset(train_samples, train_transform),
                                  batch_size=args.batch_size, shuffle=True, num_workers=0)
        val_loader = DataLoader(WasteImageDataset(val_samples, val_transform),
                                batch_size=args.batch_size, shuffle=False, num_workers=0)
        criterion = nn.CrossEntropyLoss()
        optimizer = torch.optim.AdamW(
            [p for p in net.parameters() if p.requires_grad],
            lr=args.lr, weight_decay=1e-4,
        )
        for epoch in range(1, args.epochs + 1):
            loss, acc = train_epoch(net, train_loader, criterion, optimizer, device)
            val_acc, _, _ = evaluate_torch(net, val_loader, device)
            print(f"[SQZ] epoch {epoch}/{args.epochs} loss={loss:.4f} "
                  f"acc={acc:.4f} val_acc={val_acc:.4f}")
        net = net.cpu().eval()
        export_onnx(net, export_path)  # wraps in softmax
        print(f"[EXPORT] {export_path}")
    if not export_path.exists():
        raise SystemExit(f"candidate export missing: {export_path} — run without --eval-only")

    session_sqz = load_onnx_session(export_path)
    sqz = evaluate_onnx(session_sqz, test_samples)
    sqz_lat = measure_latency(session_sqz, test_samples[0].path)
    rows.append({
        "name": "SqueezeNet1.1 (candidate)",
        "artifact": export_path.stem,
        "accuracy": sqz["accuracy"], "macro_f1": macro(sqz),
        "mean_conf": sqz["mean_confidence"],
        "size_mb": export_path.stat().st_size / 1e6,
        "latency": f"{sqz_lat['mean_ms']:.1f}/{sqz_lat['median_ms']:.1f}/{sqz_lat['p95_ms']:.1f}",
        "f1": sqz["f1"], "support": sqz["support"],
    })

    lines = [
        "# Model comparison — pilot test split",
        "",
        "**WARNING:** These results validate the training/validation pipeline "
        "under simulated camera distribution shift. They do **NOT** establish "
        "performance on the real EcoLoop station camera.",
        "",
        f"- Test: `{splits_root}/test` (n={len(test_samples)}, "
        "source=simulated-station-pilot).",
        f"- Candidate trained on `{splits_root}/train` "
        f"({args.epochs} epochs, lr={args.lr}, seed {args.seed}).",
        "",
        "| model | accuracy | macro-F1 | mean conf | size (MB) | latency ms (mean/med/p95) |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['name']} | {r['accuracy']:.4f} | {r['macro_f1']:.4f} | "
                     f"{r['mean_conf']:.4f} | {r['size_mb']:.2f} | {r['latency']} |")
    lines += [
        "",
        "## Per-class F1",
        "",
        "| model | " + " | ".join(CLASSES) + " |",
        "|---|" + "---|" * len(CLASSES),
    ]
    for r in rows:
        cells = " | ".join(f"{f:.3f}" for f in r["f1"])
        lines.append(f"| {r['name']} | {cells} |")
    lines += [
        "",
        "The served model is unchanged; a model swap is a separate explicit "
        "decision documented in this report.",
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