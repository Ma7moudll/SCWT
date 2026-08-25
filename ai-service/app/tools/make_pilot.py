"""Generate the `simulated-station-pilot` dataset for validation tooling.

Reads the local TrashNet images (`data/raw/dataset-resized`) and renders each
chosen source object into `data/station_capture` tagged
`source=simulated-station-pilot`. Augmented variants of a source object share a
`session_id`/`object_id` so the leakage-free split never separates them.

WARNING — read before running:
    This is a SIMULATION used to validate the data-collection / model-validation
    pipeline under a simulated camera distribution shift. It is NOT real
    station-camera data, and every sample is truthfully tagged
    `source=simulated-station-pilot`. Generated images are treated exactly like
    a real capture by downstream tools, which is precisely why the provenance
    tag exists.

Usage:
    python -m app.tools.make_pilot --objects 1200 --variants 4 --seed 7
"""
from __future__ import annotations

import argparse
import random
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

from ..training.dataset import CLASS_MAPPING, load_samples
from .common import (
    CLASSES,
    PILOT_SOURCE,
    new_image_id,
    simulate_station_augment,
    utc_iso,
    write_metadata,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-dir", default="data/raw/dataset-resized",
                   help="extracted TrashNet class folders")
    p.add_argument("--out-root", default="data/station_capture")
    p.add_argument("--objects", type=int, default=1200,
                   help="total source objects to draw (stratified per class)")
    p.add_argument("--variants", type=int, default=4,
                   help="rendered views per source object (incl. 1 clean copy)")
    p.add_argument("--seed", type=int, default=7)
    return p.parse_args(argv)


def _select_objects(samples, objects_per_class: int, seed: int):
    by_class: dict[str, list] = defaultdict(list)
    for s in samples:
        by_class[s.label].append(s)
    chosen: list = []
    for cls in CLASSES:
        pool = by_class.get(cls, [])
        if objects_per_class > len(pool):
            print(f"  ! class {cls}: only {len(pool)} objects available "
                  f"(requested {objects_per_class}) — using all")
        rng = random.Random(seed)
        picked = rng.sample(pool, min(objects_per_class, len(pool)))
        chosen.extend(picked)
    random.Random(seed).shuffle(chosen)
    return chosen


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source_dir = Path(args.source_dir)
    if not source_dir.is_dir():
        print(f"source dir not found: {source_dir}")
        return 1
    samples = load_samples(source_dir)
    per_class = max(1, args.objects // len(CLASSES))
    chosen = _select_objects(samples, per_class, args.seed)

    out_root = Path(args.out_root)
    lighting_choices = ("day", "led", "fluorescent")

    print(f"[PILOT] {len(chosen)} source objects, {args.variants} views each "
          f"-> {len(chosen) * args.variants} samples under {out_root} "
          f"(source={PILOT_SOURCE})")

    counts: Counter = Counter()
    rows: list[dict] = []
    for n, sample in enumerate(chosen):
        src_path = sample.path
        try:
            image = Image.open(src_path).convert("RGB")
        except Exception as exc:
            print(f"  ! skipped unreadable source {src_path}: {exc}")
            continue
        rng = random.Random(args.seed * 1_000_003 + n)
        session = f"pilot-{(n % 1_000_000):05d}-{n:07d}"
        object_meta = f"{session}-obj"
        for variant in range(args.variants):
            rng = random.Random(args.seed * 1_000_003 + n * 1000 + variant)
            if variant == 0:
                rendered = image
            else:
                rendered = simulate_station_augment(image, rng)
            image_id = new_image_id()
            target_dir = out_root / sample.label
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"{image_id}.jpg"
            rendered.convert("RGB").save(target, quality=92)
            rows.append({
                "image_id": image_id,
                "path": str(target.relative_to(out_root)),
                "class": sample.label,
                "source": PILOT_SOURCE,
                "camera": "simulated-station-top",
                "lighting": rng.choice(lighting_choices),
                "background": "tray",
                "occlusion": "none",
                "object_count": "1",
                "session_id": session,
                "object_id": object_meta,
                "timestamp": utc_iso(),
            })
            counts[sample.label] += 1

    write_metadata(out_root, rows)
    total = sum(counts.values())
    print(f"[PILOT] DONE — {total} images, distribution: "
          + ", ".join(f"{c}={counts[c]}" for c in CLASSES))
    print(f"[PILOT] provenance: source={PILOT_SOURCE} on every row of "
          f"{out_root / 'metadata.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())