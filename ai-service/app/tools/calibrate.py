"""Confidence calibration for the served ONNX classifier.

Fits a temperature scaling factor on the PILOT validation split and reports
ECE (15 bins) + Brier before/after. Calibration does NOT change the served
model or the backend policy thresholds (>=0.80 HIGH / 0.50-0.79 MEDIUM /
<0.50 LOW) — it quantifies and optionally post-conditions the softmax
confidence for reporting/tooling.

    python -m app.tools.calibrate \
        [--model models/model.onnx] [--val data/station_capture_splits/val] \
        [--out-json models/calibration.json] [--report reports/calibration_report.md]
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.optimize import minimize_scalar
from sklearn.metrics import accuracy_score

from ..training.dataset import CLASSES, Sample
from ..training.train import load_onnx_session, onnx_predict_probs
from .common import utc_iso

NUM_BINS = 15


@dataclass
class CalibrationStats:
    ece: float
    brier: float
    nll: float
    accuracy: float
    mean_conf: float
    n: int


def _split_samples(split_root: Path) -> list[Sample]:
    samples: list[Sample] = []
    for cls_dir in sorted(split_root.iterdir()):
        if not cls_dir.is_dir() or cls_dir.name not in CLASSES:
            continue
        for path in sorted(cls_dir.rglob("*")):
            if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
                continue
            samples.append(
                Sample(path=path, label=cls_dir.name,
                       label_idx=CLASSES.index(cls_dir.name), source_class=cls_dir.name)
            )
    return samples


def expected_calibration_error(probs: np.ndarray, y_true: np.ndarray, bins: int = NUM_BINS) -> float:
    conf = probs.max(axis=1)
    pred = probs.argmax(axis=1)
    acc = (pred == y_true).astype(float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        idx = (conf >= lo) & (conf < hi)
        if idx.sum() == 0:
            continue
        ece += idx.sum() / len(conf) * abs(conf[idx].mean() - acc[idx].mean())
    return float(ece)


def brier_score(probs: np.ndarray, y_true: np.ndarray) -> float:
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(y_true)), y_true] = 1.0
    return float(np.mean(np.sum((probs - onehot) ** 2, axis=1)))


def nll(probs: np.ndarray, y_true: np.ndarray) -> float:
    p = probs[np.arange(len(y_true)), y_true]
    p = np.clip(p, 1e-9, 1.0)
    return float(-np.mean(np.log(p)))


def raw_stats(probs: np.ndarray, y_true: np.ndarray) -> CalibrationStats:
    return CalibrationStats(
        ece=expected_calibration_error(probs, y_true),
        brier=brier_score(probs, y_true),
        nll=nll(probs, y_true),
        accuracy=float(accuracy_score(y_true, probs.argmax(axis=1))),
        mean_conf=float(probs.max(axis=1).mean()),
        n=len(y_true),
    )


def _softmax(x: np.ndarray) -> np.ndarray:
    x = x - x.max(axis=1, keepdims=True)
    e = np.exp(x)
    return e / e.sum(axis=1, keepdims=True)


def temperature_scaled(probs: np.ndarray, T: float) -> np.ndarray:
    """Apply temperature scaling to softmax outputs via inverted-logits."""
    logits = np.log(np.clip(probs, 1e-12, 1.0))
    return _softmax(logits / T)


def _objective(T: float, probs: np.ndarray, y_true: np.ndarray) -> float:
    return nll(temperature_scaled(probs, T), y_true)


def fit_temperature(probs: np.ndarray, y_true: np.ndarray) -> float:
    result = minimize_scalar(
        _objective, args=(probs, y_true), bounds=(0.1, 10.0), method="bounded"
    )
    if not np.isfinite(result.fun):
        raise RuntimeError("temperature fit failed")
    return float(result.x)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", default="models/model.onnx")
    p.add_argument("--val", default="data/station_capture_splits/val")
    p.add_argument("--out-json", default="models/calibration.json")
    p.add_argument("--report", default="reports/calibration_report.md")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    model_path = Path(args.model)
    val_root = Path(args.val)
    if not model_path.exists():
        print(f"model not found: {model_path}")
        return 1
    if not val_root.is_dir():
        print(f"val split not found: {val_root} (run split_dataset first)")
        return 1

    samples = _split_samples(val_root)
    if not samples:
        print(f"no samples under {val_root}")
        return 1

    session = load_onnx_session(model_path)
    probs = onnx_predict_probs(session, [s.path for s in samples])
    y_true = np.asarray([s.label_idx for s in samples])

    before = raw_stats(probs, y_true)
    T = fit_temperature(probs, y_true)
    after = raw_stats(temperature_scaled(probs, T), y_true)

    payload = {
        "temperature": T,
        "fitted_on": {
            "source": "simulated-station-pilot",
            "split": "val",
            "root": str(val_root),
            "n": before.n,
            "model": str(model_path),
        },
        "before": {
            "ece": before.ece, "brier": before.brier, "nll": before.nll,
            "accuracy": before.accuracy, "mean_confidence": before.mean_conf,
        },
        "after": {
            "ece": after.ece, "brier": after.brier, "nll": after.nll,
            "accuracy": after.accuracy, "mean_confidence": after.mean_conf,
        },
        "timestamp": utc_iso(),
    }
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    report = [
        "# Confidence calibration report",
        "",
        "**WARNING:** These results validate the training/validation pipeline "
        "under simulated camera distribution shift. They do **NOT** establish "
        "performance on the real EcoLoop station camera.",
        "",
        f"- Model: `{model_path}`",
        f"- Fitted on: `{val_root}` (source=simulated-station-pilot, n={before.n})",
        f"- Temperature (fitted on val NLL): **T={T:.4f}**",
        "",
        "| metric | before (raw) | after (T-scaled) |",
        "|---|---|---|",
        f"| ECE (15 bins) | {before.ece:.4f} | {after.ece:.4f} |",
        f"| Brier | {before.brier:.4f} | {after.brier:.4f} |",
        f"| NLL | {before.nll:.4f} | {after.nll:.4f} |",
        f"| Accuracy | {before.accuracy:.4f} | {after.accuracy:.4f} |",
        f"| Mean confidence | {before.mean_conf:.4f} | {after.mean_conf:.4f} |",
        "",
        "Backend policy thresholds (`>=0.80` HIGH / `0.50-0.79` MEDIUM / "
        "`<0.50` LOW) are unchanged — calibration only post-conditions "
        "reported confidence.",
        "",
    ]
    out_report = Path(args.report)
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    print(f"Wrote {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())