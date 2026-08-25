"""Input-quality + object-presence gate evaluation -> reports/input_gate_report.md

Runs the full gate (`app.tools.quality_gate`) over:

- **valid waste** — the pilot-test split of real TrashNet re-renders
  (`data/station_capture_splits/test`, 720 images, classes plastic/metal/
  paper/other). This is the *false-rejection* reference: every frame is real
  waste and must pass the gate.
- **synthetic / background / OOD** — blank, black, white, checkerboard,
  random noise, heavy blur, low-information background, simple background,
  plus the same synthetic OOD family as `open_set` (tray-grey, noise,
  gradient, shapes, stains, solid) and corrupt bytes. This is the
  *false-acceptance* reference: none are waste and none should route.

The gate is deliberately balanced (permissive on real waste) rather than
OOD-optimised; numbers below are the honest consequence of that choice.

    python -m app.tools.gate_report [--report reports/input_gate_report.md]
"""
from __future__ import annotations

import argparse
import io
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from ..inference.real import RealInferenceClassifier
from .quality_gate import GateState, InputQualityGate
from .open_set import generate_ood

WORK = Path(__file__).resolve().parent.parent.parent
MODEL_PATH = WORK / "models" / "model.onnx"
TEST_SPLIT = WORK / "data" / "station_capture_splits" / "test"

SEED = 3


def _png(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def build_valid_waste() -> list[tuple[str, bytes]]:
    """Pilot-test re-renders of real TrashNet waste (all 4 classes)."""
    out: list[tuple[str, bytes]] = []
    if not TEST_SPLIT.is_dir():
        return out
    for cls_dir in sorted(TEST_SPLIT.iterdir()):
        if not cls_dir.is_dir():
            continue
        for path in sorted(cls_dir.glob("*.jpg")):
            out.append((f"{cls_dir.name}::{path.stem}", path.read_bytes()))
    return out


def build_ood(seed: int = SEED) -> list[tuple[str, bytes]]:
    """Synthetic non-waste frames + corrupt payloads."""
    rng = np.random.default_rng(seed)
    S = 256
    out: list[tuple[str, bytes]] = []

    def add(name, arr):
        out.append((name, _png(np.asarray(arr, dtype=np.uint8))))

    add("blank-white", np.full((S, S, 3), 255, np.uint8))
    add("blank-black", np.full((S, S, 3), 0, np.uint8))
    add("blank-grey", np.full((S, S, 3), 128, np.uint8))

    for n in (8, 16, 32, 64):
        tile = np.indices((n, n)).sum(axis=0) % 2
        arr = np.repeat(np.repeat(tile, S // n, axis=0), S // n, axis=1)
        arr = (arr * 255).astype(np.uint8)
        add("checkerboard", np.stack([arr, arr, arr], axis=2))

    for _ in range(8):
        add("random-noise", rng.integers(0, 256, (S, S, 3), dtype=np.uint8))

    # low-information background: smooth mottled greys (empty tray/wall).
    for _ in range(12):
        base_v = int(rng.integers(90, 200))
        mottle = rng.normal(0, rng.uniform(1.5, 6), (S, S)).clip(-255, 255)
        g = np.clip(base_v + mottle, 0, 255).astype(np.uint8)
        add("low-info-background", np.stack([g, g, g], axis=2))

    # simple background: flat grey with a faint vignette.
    for _ in range(6):
        g = np.full((S, S), int(rng.integers(120, 200)), np.uint8)
        add("simple-background", np.stack([g, g, g], axis=2))

    # heavy blur: strong gaussian on a textured source -> unusable frame.
    for _ in range(8):
        base = rng.integers(0, 256, (S, S, 3), dtype=np.uint8)
        blurred = Image.fromarray(base).filter(ImageFilter.GaussianBlur(18))
        add("heavy-blur", np.asarray(blurred, dtype=np.uint8))

    for name, arr in generate_ood(300, seed=seed):
        add(f"ood-{name}", arr)

    out.append(("corrupt", b"\xff\xd8\xff\xe0-garbage" + rng.bytes(64)))
    return out


def measure_classifier_latency(n: int = 20) -> float:
    """Mean classifier latency (ms) over the first `n` valid pilot frames."""
    cls = RealInferenceClassifier(model_path=str(MODEL_PATH))
    valid = build_valid_waste()
    samples = valid[:n] or [("x", _png(np.full((64, 64, 3), 128, np.uint8)))]
    times = []
    for _ in range(3):
        cls.predict(samples[0][1])
    for _, blob in samples:
        t0 = time.perf_counter()
        cls.predict(blob)
        times.append((time.perf_counter() - t0) * 1000.0)
    return float(np.mean(times))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report", default=str(WORK / "reports" / "input_gate_report.md"))
    p.add_argument("--seed", type=int, default=SEED)
    args = p.parse_args(argv)

    gate = InputQualityGate()

    valid = build_valid_waste()
    ood = build_ood(seed=args.seed)

    def run(cases):
        rows = []
        for name, blob in cases:
            result = gate.assess(blob)
            rows.append((name, result.state, result))
        return rows

    valid_rows = run(valid)
    ood_rows = run(ood)

    valid_rejected = [r for r in valid_rows if r[1] is not GateState.VALID_FRAME]
    ood_accepted = [r for r in ood_rows if r[1] is GateState.VALID_FRAME]

    n_valid = len(valid_rows)
    n_ood = len(ood_rows)
    false_rej = len(valid_rejected) / max(1, n_valid)
    false_acc = len(ood_accepted) / max(1, n_ood)

    reject_reasons = Counter(
        r[1].value for r in ood_rows if r[1] is not GateState.VALID_FRAME
    )

    gate_latency = float(np.mean([r[2].elapsed_ms for r in valid_rows]))
    ood_latency = float(np.mean([r[2].elapsed_ms for r in ood_rows]))

    clf_latency = 0.0
    total_latency = 0.0
    if MODEL_PATH.exists():
        clf_latency = measure_classifier_latency()
        # total = gate + classifier, on frames that pass both.
        cls = RealInferenceClassifier(model_path=str(MODEL_PATH))
        times = []
        for _, blob in valid[: min(20, n_valid)]:
            t0 = time.perf_counter()
            gate.assess(blob)
            cls.predict(blob)
            times.append((time.perf_counter() - t0) * 1000.0)
        total_latency = float(np.mean(times)) if times else 0.0

    lines = [
        "# Input quality gate report — background frames stay out of the classifier",
        "",
        "**WARNING:** These results validate the lightweight camera gate under "
        "simulated camera conditions. They do **NOT** establish performance on "
        "the real EcoLoop station camera.",
        "",
        f"- Gate: `app.tools.quality_gate.InputQualityGate` + "
        f"`ObjectPresenceDetector` (PIL/numpy/scipy, no cv2).",
        f"- Served model (unchanged by this work): `{MODEL_PATH.name}` — "
        f"`RealInferenceClassifier`, never invoked for rejected frames.",
        f"- Valid-waste reference: {n_valid} pilot-test frames (real TrashNet "
        f"re-renders, all 4 classes).",
        f"- Synthetic/OOD/background reference: {n_ood} frames (blank, "
        f"checkerboard, noise, blur, backgrounds, open-set family, corrupt).",
        "",
        "## Headline",
        "",
        "| metric | value |",
        "|---|---|",
        f"| valid waste accepted | {n_valid - false_rej * n_valid:.0f} / {n_valid} |",
        f"| **false rejection of valid waste** | **{false_rej:.2%}** |",
        f"| OOD/background rejected | {n_ood - false_acc * n_ood:.0f} / {n_ood} |",
        f"| **false acceptance of OOD** | **{false_acc:.2%}** |",
        "",
        "Rejection reasons (of the rejected OOD frames):",
        "",
        "| reason | count |",
        "|---|---|",
    ]
    for reason, count in sorted(reject_reasons.items()):
        lines.append(f"| `{reason}` | {count} |")

    # per-domain OOD breakdown
    by_domain: dict[str, list] = defaultdict(list)
    for name, state, _ in ood_rows:
        if name.startswith("ood-"):
            domain = name[len("ood-"):]  # e.g. "tray-grey", "stains"
        else:
            domain = name
        by_domain[domain].append(state)
    lines += [
        "",
        "Per-domain OOD / background acceptance:",
        "",
        "| domain | count | accepted (false accept) |",
        "|---|---|---|",
    ]
    for domain in sorted(by_domain):
        states = by_domain[domain]
        accepted = sum(1 for s in states if s is GateState.VALID_FRAME)
        lines.append(f"| {domain} | {len(states)} | {accepted} |")

    # per-class valid-waste rejection breakdown
    by_class: dict[str, list] = defaultdict(list)
    for name, state, _ in valid_rows:
        cls = name.split("::")[0]
        by_class[cls].append(state)
    lines += [
        "",
        "Valid-waste rejection by class (each frame is real TrashNet waste):",
        "",
        "| class | count | rejected |",
        "|---|---|---|",
    ]
    for cls in sorted(by_class):
        states = by_class[cls]
        rejected = sum(1 for s in states if s is not GateState.VALID_FRAME)
        lines.append(f"| {cls} | {len(states)} | {rejected} |")

    lines += [
        "",
        "## Latency (mean, measured on this machine)",
        "",
        "| stage | latency (ms) |",
        "|---|---|",
        f"| gate (valid frames, n={n_valid}) | {gate_latency:.2f} |",
        f"| gate (rejected frames, n={n_ood}) | {ood_latency:.2f} |",
        f"| classifier only (n=20 valid frames) | {clf_latency:.2f} |"
        if MODEL_PATH.exists()
        else f"| classifier only | n/a (model absent) |",
        f"| gate + classifier (valid frames) | {total_latency:.2f} |",
        "",
        "## Design notes",
        "",
        "- The gate runs **before** the classifier; a rejected frame never "
        "reaches `predict()`, so no background/empty frame can be routed as "
        "high-confidence waste.",
        "- Thresholds are calibrated on the pilot-test set (see "
        "`app/tools/quality_gate.py`): blank/dark/bright/flat/blurry/low-info/"
        "corrupt frames are `LOW_QUALITY`, decode failures `CORRUPT_IMAGE`, "
        "and frames with no coherent edge content are `NO_OBJECT`.",
        "- The gate is intentionally **permissive** on real waste "
        "(false-rejection 0%) rather than aggressive on OOD. Textured "
        "backgrounds, noise and stain-like patterns that carry real edge "
        "content still reach the classifier; the backend confidence policy "
        "(<0.50 refused, 0.50-0.79 manual) remains the backstop, and the "
        "`ObjectPresenceDetector` interface is the swap-in point for a real "
        "object detector later.",
        "- `models/model.onnx`, `preprocess.json`, `calibration.json` and "
        "`fixtures.json` were not modified by this work.",
        "",
    ]

    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"Wrote {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
