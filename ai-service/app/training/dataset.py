"""Dataset preparation for the 4-class waste classifier.

Source
------
TrashNet — Gary Thung & Mindy Yang (Stanford University).
https://github.com/garythung/trashnet  ·  License: CC BY 4.0
Distributed by the authors as `dataset-resized.zip` (42,834,870 bytes).
Obtained from the canonical Hugging Face mirror of the same repository:
https://huggingface.co/datasets/garythung/trashnet

The authors' README asks for a citation of the repository when using the
dataset (doi/paper: "TrashNet: A Dataset for Image Classification of
Household Trash", www.air.csail.mit.edu/trashnet).

Class mapping (6 TrashNet classes -> the 4 production classes)
--------------------------------------------------------------
    plastic   -> plastic
    metal     -> metal
    paper     -> paper
    glass     -> other
    cardboard -> other
    trash     -> other
"""
from __future__ import annotations

import random
import zipfile
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

# The 4 production classes, in the exact index order the classifier emits.
CLASSES = ("plastic", "metal", "paper", "other")
CLASS_TO_IDX = {name: i for i, name in enumerate(CLASSES)}

CLASS_MAPPING = {
    "plastic": "plastic",
    "metal": "metal",
    "paper": "paper",
    "glass": "other",
    "cardboard": "other",
    "trash": "other",
}

# Integrity pin for the exact artifact we trained from.
DATASET_ZIP_SHA256 = "c060e8abfe5d6de0578ca15be1ed8ad0794a865d333c3473d53d1d9ad6e38b8c"
RAW_ZIP_NAME = "dataset-resized.zip"
RESIZED_DIR_NAME = "dataset-resized"


@dataclass(frozen=True)
class Sample:
    path: Path
    label: str  # 4-class production label
    label_idx: int  # index into CLASSES
    source_class: str  # original TrashNet folder name


def _sha256_file(path: Path) -> str:
    h = sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_or_extract(raw_root: Path) -> Path:
    """Return the extracted class-folder root, verifying download integrity."""
    raw_root.mkdir(parents=True, exist_ok=True)
    zip_path = raw_root / RAW_ZIP_NAME
    if not zip_path.exists():
        raise FileNotFoundError(
            f"{zip_path} missing — download the canonical TrashNet "
            f"`{RAW_ZIP_NAME}` (see module docstring) into {raw_root}"
        )
    actual = _sha256_file(zip_path)
    if actual != DATASET_ZIP_SHA256:
        raise RuntimeError(
            f"checksum mismatch for {zip_path.name}: got {actual}, "
            f"expected {DATASET_ZIP_SHA256}. Re-download the dataset."
        )
    out = raw_root / RESIZED_DIR_NAME
    if out.exists():
        return out
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(raw_root)
    if not out.exists():
        raise RuntimeError(f"expected {out.name} after extraction of {zip_path}")
    return out


def load_samples(data_root: Path) -> list[Sample]:
    """Index every image into a Sample; errors on unexpected classes."""
    samples: list[Sample] = []
    for src_dir in sorted(data_root.iterdir()):
        if not src_dir.is_dir():
            continue
        source_class = src_dir.name
        if source_class not in CLASS_MAPPING:
            raise ValueError(f"unexpected dataset folder {source_class!r}")
        label = CLASS_MAPPING[source_class]
        for image in sorted(src_dir.iterdir()):
            if image.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                continue
            samples.append(
                Sample(path=image, label=label, label_idx=CLASS_TO_IDX[label],
                       source_class=source_class)
            )
    if not samples:
        raise RuntimeError(f"no images found under {data_root}")
    return samples


def class_counts(samples: list[Sample]) -> Counter:
    return Counter(s.label for s in samples)


def stratified_split(
    samples: list[Sample],
    val_ratio: float = 0.20,
    seed: int = 42,
) -> tuple[list[Sample], list[Sample]]:
    """Stratified train/val split preserving per-class ratios (deterministic)."""
    rng = random.Random(seed)
    by_label: dict[str, list[Sample]] = {c: [] for c in CLASSES}
    for s in samples:
        by_label[s.label].append(s)

    train, val = [], []
    for label, group in by_label.items():
        group = list(group)
        rng.shuffle(group)
        n_val = max(1, round(len(group) * val_ratio))
        val.extend(group[:n_val])
        train.extend(group[n_val:])
    rng.shuffle(train)
    rng.shuffle(val)
    return train, val
