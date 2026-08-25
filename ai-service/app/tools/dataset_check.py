"""Data-quality gate for `data/station_capture`.

Detects corrupted images, exact duplicates (md5), near-duplicates (dHash),
anomalous dimensions, empty classes, extreme class imbalance and invalid
labels, then writes `reports/dataset_report.md`.

    python -m app.tools.dataset_check [--data-root data/station_capture] [--out reports/dataset_report.md]
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from .common import CLASSES, find_duplicates, find_near_duplicates, load_image_samples

VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
IMBALANCE_WARN_RATIO = 5.0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-root", default="data/station_capture")
    p.add_argument("--out", default="reports/dataset_report.md")
    return p.parse_args(argv)


def run_checks(data_root: Path) -> dict:
    samples = load_image_samples(data_root)
    by_class: Counter = Counter(s.cls for s in samples if s.cls)
    for _ in CLASSES:
        by_class.setdefault(_, 0)

    corrupted = [s for s in samples if not s.md5]
    errors_by_class: Counter = Counter(s.cls for s in corrupted)

    dup_groups = find_duplicates(samples)
    dup_extra_images = sum(len(g) - 1 for g in dup_groups)

    near_dup_pairs = find_near_duplicates(samples)
    near_dup_affected = sorted({p[0].path for p in near_dup_pairs} | {p[1].path for p in near_dup_pairs})

    dims = Counter(s.size for s in samples if s.size)
    corrupt_dims = sum(1 for s in samples if not s.size)

    empty_classes = [c for c in CLASSES if by_class[c] == 0]
    max_count = max(by_class.values()) if by_class else 0
    min_count = min(by_class.values()) if by_class else 0
    max_ratio = (max_count / min_count) if min_count else 0.0
    imbalanced = max_ratio >= IMBALANCE_WARN_RATIO

    percent = {c: (100.0 * by_class[c] / len(samples)) if samples else 0.0 for c in CLASSES}

    invalid_labels = [
        d for d in (data_root.iterdir() if data_root.exists() else [])
        if d.is_dir() and d.name not in CLASSES
    ]

    dim_summary = {}
    for size, n in dims.most_common():
        dim_summary[f"{size[0]}x{size[1]}"] = n
    if corrupt_dims:
        dim_summary["unreadable"] = corrupt_dims

    return {
        "total": len(samples),
        "by_class": dict(by_class),
        "percent": percent,
        "corrupted": corrupted,
        "corrupt_by_class": dict(errors_by_class),
        "dup_groups_count": len(dup_groups),
        "dup_extra_images": dup_extra_images,
        "near_dup_pairs_count": len(near_dup_pairs),
        "near_dup_affected": len(near_dup_affected),
        "dims": dim_summary,
        "empty_classes": empty_classes,
        "imbalanced": imbalanced,
        "max_to_min_ratio": max_ratio,
        "invalid_label_folders": [str(p) for p in invalid_labels],
    }


def render_report(res: dict, data_root: Path) -> str:
    lines = [
        "# Station-capture dataset report",
        "",
        f"Data root: `{data_root}`",
        "",
        f"**Total images:** {res['total']}",
        "",
        "## Images per class",
        "",
        "| class | count | % |",
        "|---|---|---|",
    ]
    for c in CLASSES:
        lines.append(f"| {c} | {res['by_class'][c]} | {res['percent'][c]:.1f}% |")
    lines.append("")
    lines.append("## Image dimensions")
    lines.append("")
    for size, n in res["dims"].items():
        lines.append(f"- `{size}`: {n}")
    lines.append("")
    lines.append("## Integrity checks")
    lines.append("")
    lines.append(f"- **Corrupted/unreadable:** {len(res['corrupted'])} "
                 f"{dict(res['corrupt_by_class'])}")
    lines.append(f"- **Exact duplicates (md5):** {res['dup_groups_count']} group(s), "
                 f"{res['dup_extra_images']} redundant image(s)")
    lines.append(f"- **Near-duplicates (dHash, dist≤4):** {res['near_dup_pairs_count']} pair(s), "
                 f"{res['near_dup_affected']} image(s) affected")
    lines.append("")
    lines.append("## Quality gates")
    lines.append("")
    lines.append(f"- Empty classes: {res['empty_classes'] if res['empty_classes'] else 'none'}")
    lines.append(f"- Extreme imbalance (max/min ratio {res['max_to_min_ratio']:.1f}, "
                 f"warn ≥ {IMBALANCE_WARN_RATIO:.1f}): "
                 f"{'YES' if res['imbalanced'] else 'no'}")
    invalid = res["invalid_label_folders"]
    lines.append(f"- Invalid label folders: {invalid if invalid else 'none'}")
    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    data_root = Path(args.data_root)
    res = run_checks(data_root)
    report = render_report(res, data_root)
    out = Path(args.out)
    if out.parent and not out.parent.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())