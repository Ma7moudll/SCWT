"""Open-set (out-of-distribution) probe for the served classifier.

Generates synthetic OOD images that are NOT waste but plausibly appear on a
station camera frame (empty tray / neutral background, stains, textures,
patterns, gradients, shapes) and reports what fraction the served model
falsely accepts at the backend thresholds (>=0.80 HIGH auto-route, >=0.50
MEDIUM+ human route).

OOD coverage is deliberate and synthetic — it estimates false-acceptance of
non-waste frames, the main open-set risk for an unattended station camera.

    python -m app.tools.open_set [--n 300]
"""
from __future__ import annotations

import argparse
import io
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from ..training.dataset import CLASSES
from ..training.train import load_onnx_session, onnx_predict_probs

HIGH_CONFIDENCE = 0.80
MEDIUM_CONFIDENCE = 0.50


def _to_blobs(arrays: list[tuple[str, np.ndarray]]) -> list[bytes]:
    blobs = []
    for i, (name, arr) in enumerate(arrays):
        buf = io.BytesIO()
        Image.fromarray(arr).save(buf, format="PNG")
        blobs.append(buf.getvalue())
    return blobs


def generate_ood(n: int, seed: int = 3, size: int = 256) -> list[tuple[str, np.ndarray]]:
    rng = np.random.default_rng(seed)
    out: list[tuple[str, np.ndarray]] = []

    # 1) empty-tray neutrals (uniform + mottled greys) — most realistic OOD.
    for _ in range(n // 3):
        base = int(rng.integers(90, 200))
        mottle = rng.normal(0, rng.uniform(2, 9), (size, size)).clip(-255, 255)
        grey = np.clip(base + mottle, 0, 255).astype(np.uint8)
        arr = np.stack([grey, grey, grey], axis=2)
        out.append(("tray-grey", arr))

    # 2) noise / gradients / shapes — clearly non-waste patterns.
    for i in range(n // 3):
        kind = i % 4
        if kind == 0:
            arr = rng.integers(0, 256, (size, size, 3), dtype=np.uint8)
            name = "noise"
        elif kind == 1:
            v = np.linspace(0, 255, size).astype(np.float32)[:, None]
            v = np.clip(v * rng.uniform(0.5, 1.2), 0, 255).astype(np.uint8)
            arr = np.stack([v] * 3, axis=2).repeat(size, axis=1)
            name = "gradient"
        elif kind == 2:
            img = Image.new("RGB", (size, size), (120, 120, 125))
            d = ImageDraw.Draw(img)
            bg = int(rng.integers(100, 220))
            img = Image.new("RGB", (size, size), (bg, bg, bg + 5))
            d = ImageDraw.Draw(img)
            for _ in range(rng.integers(3, 9)):
                x0 = int(rng.integers(0, size - 24))
                y0 = int(rng.integers(0, size - 24))
                side = int(rng.integers(12, 80))
                col = tuple(int(v) for v in rng.integers(0, 256, 3))
                d.rectangle((x0, y0, x0 + side, y0 + side), fill=col)
            arr = np.asarray(img)
            name = "shapes"
        else:
            img = Image.new("RGB", (size, size), (128, 128, 128))
            d = ImageDraw.Draw(img)
            for _ in range(rng.integers(4, 14)):
                col = tuple(int(v) for v in rng.integers(160, 256, 3))
                cx, cy = int(rng.integers(0, size)), int(rng.integers(0, size))
                r = int(rng.integers(4, 40))
                d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)
            arr = np.asarray(img)
            name = "stains"
        out.append((name, arr))

    # 3) solid saturated colours — very unlikely waste, plausible camera glitch.
    for _ in range(n - len(out)):
        col = tuple(int(v) for v in rng.integers(0, 256, 3))
        arr = np.full((size, size, 3), col, dtype=np.uint8)
        out.append(("solid", arr))
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", default="models/model.onnx")
    p.add_argument("--n", type=int, default=300)
    p.add_argument("--seed", type=int, default=3)
    p.add_argument("--report", default="reports/open_set_report.md")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    model_path = Path(args.model)
    if not model_path.exists():
        print(f"model not found: {model_path}")
        return 1
    session = load_onnx_session(model_path)

    ood = generate_ood(args.n, seed=args.seed)
    blobs = _to_blobs(ood)
    probs = onnx_predict_probs(session, blobs)
    conf = probs.max(axis=1)

    rate_high = float((conf >= HIGH_CONFIDENCE).mean())
    rate_medium = float((conf >= MEDIUM_CONFIDENCE).mean())

    lines = [
        "# Open-set report — synthetic OOD false-acceptance",
        "",
        "**WARNING:** These results validate the training/validation pipeline "
        "under simulated camera distribution shift. They do **NOT** establish "
        "performance on the real EcoLoop station camera.",
        "",
        f"- Served model: `{model_path}`",
        f"- OOD samples: {args.n} synthetic non-waste frames "
        f"(tray-grey, noise, gradient, shapes, stains, solid).",
        "",
        "| threshold | meaning | false-accept rate |",
        "|---|---|---|",
        f"| >= 0.80 | HIGH (auto deposit route) | **{rate_high:.1%}** |",
        f"| >= 0.50 | MEDIUM+ (human review route) | **{rate_medium:.1%}** |",
        "",
        "Per-domain breakdown (max confidence >= 0.50):",
        "",
        "| domain | count | >=0.50 |",
        "|---|---|---|",
    ]
    groups: dict[str, list[float]] = defaultdict(list)
    for name, prob in zip([x[0] for x in ood], conf):
        groups[name].append(float(prob))
    for name, confs in sorted(groups.items()):
        acc = sum(1 for c in confs if c >= MEDIUM_CONFIDENCE)
        lines.append(f"| {name} | {len(confs)} | {acc} |")

    model_out = ""
    if rate_high or rate_medium:
        idx = int(conf.argmax())
        model_out = (f"  NOTE: worst offender '{ood[idx][0]}' scored "
                     f"{conf[idx]:.2f}. The model was trained only on waste "
                     f"images — background-only frames are out of training "
                     f"distribution and should be handled by the camera "
                     f"motion/detection stage, not the classifier (see "
                     f"docs/ai-validation.md).")
    lines += ["", model_out, ""] if model_out else ["", ""]

    out_report = Path(args.report)
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"Wrote {out_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())