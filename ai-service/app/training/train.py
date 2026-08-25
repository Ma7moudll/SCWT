"""Transfer-learning training pipeline for the 4-class waste classifier.

Trains a MobileNetV3-Small head on TrashNet (mapped to plastic/metal/paper/
other), evaluates the ONNX export exactly as it will be served, writes a
model-evaluation report + confusion matrix, and curates the confidence-band
fixture images used by the automated tests and the end-to-end proof.

Usage:
    python -m app.training.train [--epochs-head N] [--epochs-finetune M] ...

The ONNX artifact (with a softmax output node) and a `preprocess.json` (input
geometry + normalization + class order) are written to `--models-dir`; the
serving `RealInferenceClassifier` reads both.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    precision_recall_fscore_support,
)
from torch.utils.data import DataLoader, Dataset
from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small
from torchvision import transforms as T

from .dataset import (
    CLASSES,
    CLASS_TO_IDX,
    Sample,
    class_counts,
    load_samples,
    stratified_split,
    verify_or_extract,
)

INPUT_SIZE = 224
RESIZE_SIZE = 256
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def make_transforms():
    train = T.Compose(
        [
            T.RandomResizedCrop(INPUT_SIZE, scale=(0.6, 1.0), ratio=(0.8, 1.25)),
            T.RandomHorizontalFlip(),
            T.ToTensor(),
            T.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        ]
    )
    val = T.Compose(
        [
            T.Resize(RESIZE_SIZE),
            T.CenterCrop(INPUT_SIZE),
            T.ToTensor(),
            T.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        ]
    )
    return train, val


class WasteImageDataset(Dataset):
    def __init__(self, samples: list[Sample], transform) -> None:
        self.samples = samples
        self.transform = transform

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int):
        sample = self.samples[idx]
        image = self.transform(_load_pil(sample.path))
        return image, sample.label_idx


def _load_pil(path: Path):
    from PIL import Image

    return Image.open(path).convert("RGB")


class ClassifyNet(nn.Module):
    """MobileNetV3-Small backbone + a small task head (logits)."""

    def __init__(self, num_classes: int = 4) -> None:
        super().__init__()
        backbone = mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.IMAGENET1K_V1)
        self.features = backbone.features
        self.avgpool = backbone.avgpool
        in_features = 576
        self.head = nn.Sequential(
            nn.Linear(in_features, 256),
            nn.ReLU(inplace=True),
            nn.Dropout(0.2),
            nn.Linear(256, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.features(x)
        x = self.avgpool(x)
        x = torch.flatten(x, 1)
        return self.head(x)


class SoftmaxNet(nn.Module):
    """Export wrapper: softmax over the head logits -> probabilities."""

    def __init__(self, net: ClassifyNet) -> None:
        super().__init__()
        self.net = net

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return torch.softmax(self.net(x), dim=1)


def _device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def train_epoch(model, loader, criterion, optimizer, device) -> tuple[float, float]:
    model.train()
    total = correct = 0
    loss_sum = 0.0
    for images, labels in loader:
        images, labels = images.to(device), labels.to(device)
        optimizer.zero_grad()
        logits = model(images)
        loss = criterion(logits, labels)
        loss.backward()
        optimizer.step()
        loss_sum += loss.item() * images.size(0)
        total += labels.size(0)
        correct += (logits.argmax(dim=1) == labels).sum().item()
    return loss_sum / total, correct / total


@torch.no_grad()
def evaluate_torch(model, loader, device) -> tuple[float, np.ndarray, np.ndarray]:
    model.eval()
    y_all: list[int] = []
    pred_all: list[int] = []
    for images, labels in loader:
        logits = model(images.to(device))
        pred_all.extend(logits.argmax(dim=1).cpu().tolist())
        y_all.extend(labels.tolist())
    y, pred = np.asarray(y_all), np.asarray(pred_all)
    return accuracy_score(y, pred), y, pred


# ---------------------------------------------------------------------------
# ONNX path — mirrors the serving preprocessing in app.inference.real exactly.
# ---------------------------------------------------------------------------

def onnx_preprocess(image, resize=RESIZE_SIZE, size=INPUT_SIZE) -> np.ndarray:
    """Resize -> center-crop -> ImageNet normalize -> NCHW float32.
    Accepts raw image bytes, a path, or a PIL image (mirrors serving input)."""
    import io as _io

    from PIL import Image

    if isinstance(image, (bytes, bytearray)):
        image = Image.open(_io.BytesIO(image)).convert("RGB")
    elif not isinstance(image, Image.Image):
        image = Image.open(image).convert("RGB")
    else:
        image = image.convert("RGB")
    image = image.resize((resize, resize))
    offset = (resize - size) // 2
    image = image.crop((offset, offset, offset + size, offset + size))
    arr = np.asarray(image, dtype=np.float32) / 255.0
    mean = np.asarray(IMAGENET_MEAN, dtype=np.float32)
    std = np.asarray(IMAGENET_STD, dtype=np.float32)
    arr = (arr - mean) / std
    return arr.transpose(2, 0, 1)[None, ...]


def load_onnx_session(model_path: Path):
    import onnxruntime as ort

    return ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])


@torch.no_grad()
def export_onnx(net: ClassifyNet, out_path: Path, opset: int = 13) -> None:
    net.eval()
    wrapped = SoftmaxNet(net).cpu()
    wrapped.eval()
    dummy = torch.randn(1, 3, INPUT_SIZE, INPUT_SIZE)
    torch.onnx.export(
        wrapped,
        dummy,
        str(out_path),
        input_names=["input"],
        output_names=["probabilities"],
        opset_version=opset,
        dynamic_axes=None,
        dynamo=False,  # legacy TorchScript exporter (no onnxscript dep)
    )


def onnx_forward(session, tensor: np.ndarray) -> np.ndarray:
    input_name = session.get_inputs()[0].name
    out = session.run(None, {input_name: tensor.astype(np.float32)})
    return np.asarray(out[0], dtype=np.float32)


def onnx_predict_probs(session, images_bytes: list[bytes]) -> np.ndarray:
    """Serving-identical inference: raw image bytes -> softmax probabilities."""
    probs = np.stack(
        [onnx_forward(session, onnx_preprocess(b))[0] for b in images_bytes]
    )
    return probs


# ---------------------------------------------------------------------------
# Evaluation + report
# ---------------------------------------------------------------------------

def evaluate_onnx(
    session,
    samples_val: list[Sample],
    save_png: Path | None = None,
) -> dict:
    """Full metric report computed on the deployed ONNX artifact."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    probs = onnx_predict_probs(session, [s.path for s in samples_val])
    y_true = np.asarray([s.label_idx for s in samples_val])
    y_pred = probs.argmax(axis=1)
    conf = probs.max(axis=1)

    acc = accuracy_score(y_true, y_pred)
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=list(range(len(CLASSES))), zero_division=0
    )
    cm = confusion_matrix(y_true, y_pred, labels=list(range(len(CLASSES))))

    if save_png is not None:
        fig, ax = plt.subplots(figsize=(6.4, 5.4))
        im = ax.imshow(cm, cmap="Blues")
        ax.set_xticks(range(len(CLASSES)), CLASSES)
        ax.set_yticks(range(len(CLASSES)), CLASSES)
        ax.set_xlabel("Predicted")
        ax.set_ylabel("True")
        ax.set_title("TrashNet → plastic/metal/paper/other (val, ONNX)")
        for i in range(len(CLASSES)):
            for j in range(len(CLASSES)):
                ax.text(j, i, str(cm[i, j]), ha="center", va="center",
                        color="white" if cm[i, j] > cm.max() / 2 else "black")
        fig.colorbar(im, fraction=0.046, pad=0.04)
        fig.tight_layout()
        fig.savefig(save_png, dpi=144)
        plt.close(fig)

    mean_conf = conf.mean()
    return {
        "accuracy": float(acc),
        "precision": [float(v) for v in precision],
        "recall": [float(v) for v in recall],
        "f1": [float(v) for v in f1],
        "support": [int(v) for v in support],
        "confusion_matrix": cm.tolist(),
        "mean_confidence": float(mean_conf),
        "count": int(len(y_true)),
    }


def measure_latency(session, sample: bytes, n: int = 100, warmup: int = 10) -> dict:
    for _ in range(warmup):
        onnx_forward(session, onnx_preprocess(sample))
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        onnx_forward(session, onnx_preprocess(sample))
        times.append((time.perf_counter() - t0) * 1000.0)
    times = np.asarray(times)
    return {
        "mean_ms": float(times.mean()),
        "median_ms": float(np.median(times)),
        "p95_ms": float(np.percentile(times, 95)),
        "n": n,
    }


def _report_text(metrics: dict, cm_labels: list[str]) -> str:
    lines = ["Confusion matrix (val):"]
    header = "              " + "".join(f"{lab:>9}" for lab in cm_labels)
    lines.append(header)
    for i, row in enumerate(metrics["confusion_matrix"]):
        lines.append(
            f"{cm_labels[i]:<13}" + "".join(f"{v:>9}" for v in row)
        )
    return "\n".join(lines)


def write_report(
    report_path: Path,
    *,
    metrics: dict,
    dataset_counts: dict,
    train_counts: dict,
    val_counts: dict,
    split_ratio: float,
    params: dict,
    model_bytes: int,
    latency: dict,
    seed: int,
) -> None:
    lines = [
        "# Waste classifier — model evaluation report",
        "",
        "Trained artifact for the real inference path "
        "(`AI_SERVICE_CLASSIFIER=real`, `RealInferenceClassifier`, ONNX).",
        "",
        "## Dataset",
        "",
        "- **Source:** TrashNet (Gary Thung & Mindy Yang, Stanford) — "
        "https://github.com/garythung/trashnet",
        "- **License:** CC BY 4.0 (authors' repository); fetched from the "
        "official Hugging Face mirror (`garythung/trashnet`, "
        "`dataset-resized.zip`, sha256 "
        "`c060e8abfe5d6de0578ca15be1ed8ad0794a865d333c3473d53d1d9ad6e38b8c`).",
        "- **Images:** 2,527 (512×384 RGB).",
        "",
        "Class mapping: plastic→plastic, metal→metal, paper→paper, "
        "glass+cardboard+trash→other.",
        "",
    ]
    lines.append("### Class distribution (after mapping)")
    lines.append("")
    lines.append("| class | count |")
    lines.append("|---|---|")
    for cls in CLASSES:
        lines.append(f"| {cls} | {dataset_counts.get(cls, 0)} |")
    lines.append("")
    lines.append(f"Train/val split: stratified, val_ratio={split_ratio} (seed {seed}).")
    lines.append("")
    lines.append("| split | samples | per class |")
    lines.append("|---|---|---|")
    lines.append(
        f"| train | {sum(train_counts.values())} | "
        + ", ".join(f"{k}={v}" for k, v in train_counts.items())
        + " |"
    )
    lines.append(
        f"| val | {sum(val_counts.values())} | "
        + ", ".join(f"{k}={v}" for k, v in val_counts.items())
        + " |"
    )
    lines.append("")

    lines.append("## Model")
    lines.append("")
    lines.append(f"- **Architecture:** {params['architecture']} "
                 f"({params['params_m']}M params) transfer-learned on ImageNet.")
    lines.append(f"- **Task head:** {params['head']}")
    lines.append("- **Export:** ONNX opset 13, batch=1, softmax output node, "
                 "CPU (onnxruntime).")
    lines.append(f"- **Artifact size:** {model_bytes / 1e6:.2f} MB.")
    lines.append("")

    lines.append("## Training")
    lines.append("")
    for key, value in params["hyperparameters"].items():
        lines.append(f"- {key}: {value}")
    lines.append("")

    lines.append("## Validation results (ONNX artifact, val set)")
    lines.append("")
    lines.append(f"- **Accuracy:** {metrics['accuracy']:.4f}")
    lines.append(f"- **Mean confidence:** {metrics['mean_confidence']:.4f}")
    lines.append(f"- **Samples:** {metrics['count']}")
    lines.append("")
    lines.append("| class | precision | recall | f1 | support |")
    lines.append("|---|---|---|---|---|")
    for i, cls in enumerate(CLASSES):
        lines.append(
            f"| {cls} | {metrics['precision'][i]:.3f} | "
            f"{metrics['recall'][i]:.3f} | {metrics['f1'][i]:.3f} | "
            f"{metrics['support'][i]} |"
        )
    macro_f1 = float(np.mean(metrics["f1"]))
    lines.append(f"| **macro avg** | | | **{macro_f1:.3f}** | |")
    lines.append("")
    lines.append("```")
    lines.append(_report_text(metrics, list(CLASSES)))
    lines.append("```")
    lines.append("")
    lines.append("Confusion matrix rendered in `confusion_matrix.png`.")
    lines.append("")

    lines.append("## Inference latency (onnxruntime, CPU)")
    lines.append("")
    lines.append(f"- mean **{latency['mean_ms']:.1f} ms**, "
                 f"median **{latency['median_ms']:.1f} ms**, "
                 f"p95 **{latency['p95_ms']:.1f} ms** "
                 f"(n={latency['n']}, single 512×384 JPEG, M-series Mac).")
    lines.append("")

    lines.append("## Limitations (read before claiming production-readiness)")
    lines.append("")
    lines.append("- **Small, single-source dataset** (2,527 images, one camera "
                 "setup). Real station-top captures will differ in lighting, "
                 "angle and distance — expect distribution shift.")
    lines.append("- **`other` is a heterogeneous dump** (glass + cardboard + "
                 "trash): its precision/recall understates real-world "
                 "open-set rejection.")
    lines.append("- Confidence is the raw softmax probability, **not a "
                 "calibrated** probability; the backend policy thresholds are "
                 "the authority, not an ML guarantee.")
    lines.append("- Background clutter (hands, bins, carriers) is not "
                 "represented; the simulated scanner feed is idealised.")
    lines.append("- The model was trained on a single stratified split, not "
                 "cross-validated; numbers are on that held-out val set.")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Confidence-band fixtures for tests + E2E
# ---------------------------------------------------------------------------

def _synthetic_candidates() -> list[tuple[str, np.ndarray]]:
    rng = np.random.default_rng(0)
    grey = np.full((224, 224, 3), 128, dtype=np.uint8)
    black = np.zeros((224, 224, 3), dtype=np.uint8)
    white = np.full((224, 224, 3), 255, dtype=np.uint8)
    noise = rng.integers(0, 256, (224, 224, 3), dtype=np.uint8)
    return [
        ("grey", grey),
        ("black", black),
        ("white", white),
        ("noise", noise),
    ]


def _probs_for_arrays(session, arrays: list[np.ndarray]) -> np.ndarray:
    import io

    from PIL import Image

    blobs = []
    for arr in arrays:
        buf = io.BytesIO()
        Image.fromarray(arr).save(buf, format="PNG")
        blobs.append(buf.getvalue())
    return onnx_predict_probs(session, blobs)


def _perturb(session, src_path: Path, out_path: Path, target_lo: float, target_hi: float):
    """Search perturbations of a high-confidence image until confidence lands
    in [target_lo, target_hi); saves the result as a PNG."""
    from PIL import Image

    base = Image.open(src_path).convert("RGB").resize((INPUT_SIZE, INPUT_SIZE))
    rng = np.random.default_rng(7)
    arr = np.asarray(base).astype(np.int16)

    for noise_std in (30, 60, 90, 120, 150, 180):
        cand = np.clip(arr + rng.normal(0, noise_std, arr.shape), 0, 255).astype(np.uint8)
        prob = _probs_for_arrays(session, [cand])[0]
        conf = prob.max()
        if target_lo <= conf < target_hi:
            Image.fromarray(cand).save(out_path)
            return conf, float(prob.argmax())
    # Last resort: downscale/upscale blur of the base image.
    for scale in (4, 8, 16, 32, 64):
        small = base.resize((scale, scale))
        cand = np.asarray(small.resize((INPUT_SIZE, INPUT_SIZE), Image.BILINEAR)).astype(np.uint8)
        prob = _probs_for_arrays(session, [cand])[0]
        conf = prob.max()
        if target_lo <= conf < target_hi:
            Image.fromarray(cand).save(out_path)
            return conf, float(prob.argmax())
    raise RuntimeError("could not find a perturbation landing in the target band")


def curate_fixtures(
    session,
    samples_val: list[Sample],
    fixtures_dir: Path,
) -> dict:
    """Pick committed fixture images that the real model scores in the three
    confidence bands: HIGH (>=0.80 plastic), MEDIUM (0.50-0.80), LOW (<0.50).

    These are *inputs* for the confidence-policy tests/E2E; the model's score
    on them is genuine inference, never a forced prediction."""
    from PIL import Image

    fixtures_dir.mkdir(parents=True, exist_ok=True)
    probs = onnx_predict_probs(session, [s.path for s in samples_val])
    confs = probs.max(axis=1)
    preds = probs.argmax(axis=1)

    # HIGH: most-confident plastic from the val set.
    plastic_idx = [
        i for i in range(len(samples_val))
        if preds[i] == CLASS_TO_IDX["plastic"] and confs[i] >= 0.80
    ]
    if not plastic_idx:
        raise RuntimeError("no val plastic image scores >= 0.80 — rethink fixture strategy")
    high_i = max(plastic_idx, key=lambda i: confs[i])
    high_path = fixtures_dir / "high_conf_plastic.png"
    Image.open(samples_val[high_i].path).convert("RGB").save(high_path)

    # LOW: lowest-confidence synthetic/val candidate below 0.50.
    low_candidates = _synthetic_candidates()
    low_arrays = [arr for _, arr in low_candidates]
    low_probs = _probs_for_arrays(session, low_arrays)
    low_i = int(np.argmin(low_probs.max(axis=1)))
    low_conf = float(low_probs[low_i].max())
    if low_conf >= 0.50:
        raise RuntimeError("no synthetic image lands below 0.50 — expect near-uniform softmax")
    low_path = fixtures_dir / "low_conf.png"
    Image.fromarray(low_candidates[low_i][1]).save(low_path)
    low_pred = str(CLASSES[int(low_probs[low_i].argmax())])

    # MEDIUM: a real val image in the band, else a perturbed high image.
    medium_idx = [
        i for i in range(len(samples_val))
        if 0.50 <= confs[i] < 0.80
    ]
    if medium_idx:
        m_i = medium_idx[0]
        medium_path = fixtures_dir / "medium_conf.png"
        Image.open(samples_val[m_i].path).convert("RGB").save(medium_path)
        medium_conf = float(confs[m_i])
        medium_pred = str(CLASSES[int(preds[m_i])])
    else:
        medium_path = fixtures_dir / "medium_conf.png"
        medium_conf, medium_pred = _perturb(
            session, high_path, medium_path, 0.50, 0.80
        )

    return {
        "high_conf_plastic.png": {
            "confidence": float(confs[high_i]),
            "predicted_class": "plastic",
            "source": str(samples_val[high_i].path.name),
        },
        "medium_conf.png": {
            "confidence": medium_conf,
            "predicted_class": medium_pred,
            "source": str(samples_val[m_i].path.name) if medium_idx else f"perturbed({high_path.name})",
        },
        "low_conf.png": {
            "confidence": low_conf,
            "predicted_class": low_pred,
            "source": f"synthetic:{low_candidates[low_i][0]}",
        },
    }


# ---------------------------------------------------------------------------
# Training driver
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", default="data/raw", help="where dataset-resized.zip lives")
    p.add_argument("--models-dir", default="models", help="ONNX + preprocess.json output")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--fixtures-dir", default="tests/fixtures")
    p.add_argument("--checkpoint-dir", default="data/checkpoints")
    p.add_argument("--epochs-head", type=int, default=8)
    p.add_argument("--epochs-finetune", type=int, default=4)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--lr-head", type=float, default=1e-3)
    p.add_argument("--lr-finetune", type=float, default=1e-4)
    p.add_argument("--val-ratio", type=float, default=0.20)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--eval-only", action="store_true",
                   help="re-evaluate an existing ONNX artifact + rewrite report")
    return p.parse_args(argv)


def run(args: argparse.Namespace) -> None:
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    data_dir = Path(args.data_dir)
    models_dir = Path(args.models_dir)
    reports_dir = Path(args.reports_dir)
    fixtures_dir = Path(args.fixtures_dir)
    checkpoint_dir = Path(args.checkpoint_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    raw_root = verify_or_extract(data_dir)
    samples = load_samples(raw_root)
    train_samples, val_samples = stratified_split(samples, args.val_ratio, args.seed)
    print(f"[DATA] {len(samples)} images; train={len(train_samples)} val={len(val_samples)}")
    print("[DATA] mapped distribution:", dict(class_counts(samples)))

    device = _device()
    print(f"[DEVICE] {device}")

    onnx_path = models_dir / "model.onnx"
    net_params = sum(p.numel() for p in ClassifyNet(num_classes=len(CLASSES)).parameters())

    if args.eval_only:
        if not onnx_path.exists():
            raise SystemExit(f"{onnx_path} missing — run full training first")
        session = load_onnx_session(onnx_path)
    else:
        model = ClassifyNet(num_classes=len(CLASSES))
        print(
            f"[MODEL] MobileNetV3-Small transfer: {net_params/1e6:.2f}M params; "
            f"head-only then last-block fine-tune"
        )

        train_transform, val_transform = make_transforms()
        train_ds = WasteImageDataset(train_samples, train_transform)
        val_ds = WasteImageDataset(val_samples, val_transform)
        train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=0)
        val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=0)

        # -- Phase 1: frozen backbone, train the head -------------------------
        for p in model.features.parameters():
            p.requires_grad_(False)
        model = model.to(device)
        criterion = nn.CrossEntropyLoss()
        optimizer = torch.optim.AdamW(
            [p for p in model.head.parameters() if p.requires_grad],
            lr=args.lr_head, weight_decay=1e-4,
        )
        for epoch in range(1, args.epochs_head + 1):
            loss, acc = train_epoch(model, train_loader, criterion, optimizer, device)
            val_acc, _, _ = evaluate_torch(model, val_loader, device)
            print(f"[TRAIN head] epoch {epoch}/{args.epochs_head} "
                  f"loss={loss:.4f} acc={acc:.4f} val_acc={val_acc:.4f}")

        # -- Phase 2: unfreeze the last inverted-residual block, low-LR fine-tune
        for name, param in model.features.named_parameters():
            if name.startswith("11."):  # last InvertedResidual block
                param.requires_grad_(True)
        optimizer = torch.optim.AdamW(
            [p for p in model.parameters() if p.requires_grad],
            lr=args.lr_finetune, weight_decay=1e-4,
        )
        for epoch in range(1, args.epochs_finetune + 1):
            loss, acc = train_epoch(model, train_loader, criterion, optimizer, device)
            val_acc, _, _ = evaluate_torch(model, val_loader, device)
            print(f"[TRAIN finetune] epoch {epoch}/{args.epochs_finetune} "
                  f"loss={loss:.4f} acc={acc:.4f} val_acc={val_acc:.4f}")

        torch.save(model.state_dict(), checkpoint_dir / "model_final.pt")
        export_onnx(model, onnx_path)
        print(f"[EXPORT] {onnx_path}")

    # -- Evaluation on the deployed artifact ----------------------------------
    session = load_onnx_session(onnx_path)
    cm_png = reports_dir / "confusion_matrix.png"
    metrics = evaluate_onnx(session, val_samples, save_png=cm_png)

    latency = measure_latency(session, val_samples[0].path)

    preprocess_json = {
        "backend": "onnx",
        "input_size": INPUT_SIZE,
        "resize": RESIZE_SIZE,
        "mean": list(IMAGENET_MEAN),
        "std": list(IMAGENET_STD),
        "classes": list(CLASSES),
    }
    (models_dir / "preprocess.json").write_text(
        json.dumps(preprocess_json, indent=2) + "\n", encoding="utf-8"
    )

    model_bytes = onnx_path.stat().st_size
    params = {
        "architecture": "MobileNetV3-Small (ImageNet-pretrained) + 2-layer head",
        "params_m": round(net_params / 1e6, 2),
        "head": "Linear(576,256) -> ReLU -> Dropout(0.2) -> Linear(256,4)",
        "hyperparameters": {
            "epochs_head": args.epochs_head,
            "epochs_finetune": args.epochs_finetune,
            "batch_size": args.batch_size,
            "lr_head": args.lr_head,
            "lr_finetune": args.lr_finetune,
            "val_ratio": args.val_ratio,
            "seed": args.seed,
            "device": str(device),
        },
    }
    write_report(
        reports_dir / "eval_report.md",
        metrics=metrics,
        dataset_counts=dict(class_counts(samples)),
        train_counts=dict(class_counts(train_samples)),
        val_counts=dict(class_counts(val_samples)),
        split_ratio=args.val_ratio,
        params=params,
        model_bytes=model_bytes,
        latency=latency,
        seed=args.seed,
    )

    fixtures = curate_fixtures(session, val_samples, fixtures_dir)
    (models_dir / "fixtures.json").write_text(
        json.dumps(fixtures, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[FIXTURES] {json.dumps(fixtures, indent=2)}")
    print(f"[EVAL] accuracy={metrics['accuracy']:.4f} "
          f"mean_conf={metrics['mean_confidence']:.4f} "
          f"latency_mean={latency['mean_ms']:.1f}ms")
    print(f"[REPORT] {reports_dir / 'eval_report.md'}")


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
