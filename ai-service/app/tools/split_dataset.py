"""Leakage-free train/val/test split for the station-capture dataset.

Groups by `session_id` (then `object_id`) from `metadata.csv` so augmented or
re-photographed views of the SAME physical object never cross the split
boundary. Writes 70/15/15 copies (hardlink first, copy fallback) into
`<data-root>_splits/{train,val,test}/<class>/` and records the group assignment
in `splits.json`.

    python -m app.tools.split_dataset [--data-root data/station_capture] [--seed 42]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from collections import Counter
from pathlib import Path

from .common import CLASSES, load_metadata, session_aware_split, GroupedItem

WARN_BELOW = 30


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-root", default="data/station_capture")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args(argv)


def _group_key(row: dict, path: Path) -> str:
    if row.get("session_id"):
        return f"session:{row['session_id']}"
    if row.get("object_id"):
        return f"object:{row['object_id']}"
    return f"file:{path.name}"  # near-dup grouping unavailable -> warn per file


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    data_root = Path(args.data_root)
    rows = load_metadata(data_root)
    items: list[GroupedItem] = []
    for row in rows:
        cls = (row.get("class") or "").strip().lower()
        if cls not in CLASSES:
            print(f"  ! skipping invalid class row {row.get('image_id')}: {cls!r}")
            continue
        path = data_root / row.get("path", "")
        if not path.exists():
            print(f"  ! metadata points to missing file: {path}")
            continue
        items.append(GroupedItem(path=path, cls=cls, group_key=_group_key(row, path), row=row))

    if not items:
        print(f"no labeled images in {data_root} (metadata.csv empty?)")
        return 0

    per_file = sum(1 for i in items if i.group_key.startswith("file:"))
    if per_file:
        print(f"  ! {per_file}/{len(items)} items lack a session/object id — "
              "near-identical captures may leak across splits (fix via collect.py --session)")

    train, val, test = session_aware_split(items, seed=args.seed)
    print(f"[SPLIT] {len(train)} train / {len(val)} val / {len(test)} test "
          f"(seed {args.seed})")
    for name, part in (("train", train), ("val", val), ("test", test)):
        print(f"  {name}: " + ", ".join(f"{c}={n}" for c, n in sorted(Counter(i.cls for i in part).items())))

    if len(items) < WARN_BELOW:
        print(f"  ! dataset has only {len(items)} images (< {WARN_BELOW}) — "
              "numbers are indicative, not production-readiness evidence")

    # write split on disk (hardlink -> copy fallback)
    out_root = data_root.parent / f"{data_root.name}_splits"
    for name, part in (("train", train), ("val", val), ("test", test)):
        for item in part:
            dst = out_root / name / item.cls / item.path.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(item.path, dst)
            except OSError:
                shutil.copy2(item.path, dst)

    assignment = {
        str(name): [{"path": str(i.path.relative_to(data_root)), "class": i.cls,
                     "group": i.group_key, "image_id": i.row.get("image_id", "")}
                    for i in part]
        for name, part in (("train", train), ("val", val), ("test", test))
    }
    (out_root / "splits.json").write_text(
        json.dumps({"seed": args.seed, "splits": assignment}, indent=2), encoding="utf-8"
    )
    print(f"[SPLIT] wrote {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())