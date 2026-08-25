"""Shared helpers for the data-collection / model-validation pipeline.

Conventions:
- Every real/collected image lives under a data root (default
  `data/station_capture`) with one folder per class and a `metadata.csv`.
- `metadata.csv` columns are listed in :data:`METADATA_COLUMNS`. `source` must
  be truthful: `"simulated-station-pilot"` for generated pilot samples,
  any user-supplied tag for real captures (default `"manual-capture"`).
- `session_id`/`object_id` group near-duplicate captures of the SAME physical
  object so the train/val/test split can never leak an object across sets.
"""
from __future__ import annotations

import csv
import hashlib
import io
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

CLASSES = ("plastic", "metal", "paper", "other")
CLASS_TO_IDX = {c: i for i, c in enumerate(CLASSES)}

METADATA_COLUMNS = [
    "image_id",
    "path",
    "class",
    "source",
    "camera",
    "lighting",
    "background",
    "occlusion",
    "object_count",
    "session_id",
    "object_id",
    "timestamp",
]

PILOT_SOURCE = "simulated-station-pilot"
DEFAULT_SOURCE = "manual-capture"


def validate_class(label: str) -> str:
    label = (label or "").strip().lower()
    if label not in CLASSES:
        raise ValueError(f"invalid class {label!r}; expected one of {CLASSES}")
    return label


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_image_id() -> str:
    """Unique, human-readable image id (timestamp + short random suffix)."""
    return f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# metadata.csv
# ---------------------------------------------------------------------------

def load_metadata(data_root: Path) -> list[dict]:
    path = data_root / "metadata.csv"
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _existing_ids(rows: list[dict]) -> set[str]:
    return {r.get("image_id", "") for r in rows if r.get("image_id")}


def append_metadata(data_root: Path, row: dict) -> None:
    """Append one row to `<data_root>/metadata.csv`. Refuses duplicate ids."""
    data_root.mkdir(parents=True, exist_ok=True)
    path = data_root / "metadata.csv"
    rows = load_metadata(data_root)
    image_id = row.get("image_id")
    if image_id in _existing_ids(rows):
        raise FileExistsError(f"metadata row for image_id {image_id!r} already exists")
    row = {col: row.get(col, "") for col in METADATA_COLUMNS}
    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=METADATA_COLUMNS)
        if path.stat().st_size == 0:
            writer.writeheader()
        writer.writerow(row)


def write_metadata(data_root: Path, rows: list[dict]) -> None:
    """Atomically write a full metadata set. Refuses duplicate ids."""
    data_root.mkdir(parents=True, exist_ok=True)
    path = data_root / "metadata.csv"
    seen: set[str] = set()
    clean: list[dict] = []
    for row in rows:
        image_id = row.get("image_id", "")
        if image_id in seen:
            raise FileExistsError(f"duplicate image_id {image_id!r} in batch")
        seen.add(image_id)
        clean.append({col: row.get(col, "") for col in METADATA_COLUMNS})
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=METADATA_COLUMNS)
        writer.writeheader()
        writer.writerows(clean)
    tmp.replace(path)


# ---------------------------------------------------------------------------
# duplicate detection
# ---------------------------------------------------------------------------

def dhash(image: Image.Image, hash_size: int = 8) -> int:
    """64-bit difference-hash (9x8 resized, grayscale) for near-dup detection."""
    gray = ImageOps.grayscale(image.resize((hash_size + 1, hash_size)))
    px = list(gray.getdata())
    bits = 0
    for y in range(hash_size):
        for x in range(hash_size):
            bits = (bits << 1) | (1 if px[y * (hash_size + 1) + x] < px[y * (hash_size + 1) + x + 1] else 0)
    return bits


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


@dataclass
class ImageSample:
    path: Path
    image_id: str = ""
    cls: str = ""
    md5: str = ""
    phash: int = 0
    size: tuple[int, int] = (0, 0)

    @property
    def basename(self) -> str:
        return self.path.name


def load_image_samples(data_root: Path) -> list[ImageSample]:
    """Index every image under `data_root/csv_class/**`; md5 + dHash + size."""
    samples: list[ImageSample] = []
    for cls_dir in sorted(data_root.iterdir()):
        if not cls_dir.is_dir() or cls_dir.name not in CLASSES:
            continue
        for path in sorted(cls_dir.rglob("*")):
            if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
                continue
            with open(path, "rb") as fh:
                blob = fh.read()
            try:
                image = Image.open(io.BytesIO(blob))
                image.verify()
                image = Image.open(io.BytesIO(blob)).convert("RGB")
            except Exception as exc:  # corrupt / unreadable
                samples.append(ImageSample(path=path, cls=cls_dir.name, md5=sha256_bytes(blob)))
                continue
            samples.append(
                ImageSample(
                    path=path,
                    cls=cls_dir.name,
                    md5=sha256_bytes(blob),
                    phash=dhash(image),
                    size=image.size,
                )
            )
    return samples


def find_duplicates(samples: list[ImageSample]) -> list[list[ImageSample]]:
    by_md5: dict[str, list[ImageSample]] = {}
    for s in samples:
        if s.md5:
            by_md5.setdefault(s.md5, []).append(s)
    return [group for group in by_md5.values() if len(group) > 1]


def find_near_duplicates(
    samples: list[ImageSample],
    max_distance: int = 4,
    sample_cap: int = 2000,
) -> list[tuple[ImageSample, ImageSample, int]]:
    """Pairwise dHash near-duplicates (O(n^2) — capped to keep it fast)."""
    pool = [s for s in samples if s.phash]
    if len(pool) > sample_cap:
        pool = random.Random(0).sample(pool, sample_cap)
    pairs: list[tuple[ImageSample, ImageSample, int]] = []
    for i in range(len(pool)):
        for j in range(i + 1, len(pool)):
            d = hamming(pool[i].phash, pool[j].phash)
            if d <= max_distance:
                pairs.append((pool[i], pool[j], d))
    pairs.sort(key=lambda t: t[2])
    return pairs


# ---------------------------------------------------------------------------
# leakage-free split
# ---------------------------------------------------------------------------

@dataclass
class GroupedItem:
    path: Path
    cls: str
    group_key: str  # session_id / object_id / single-image fallback
    row: dict = field(default_factory=dict)


def group_by_session(items: list[GroupedItem]) -> list[list[GroupedItem]]:
    groups: dict[str, list[GroupedItem]] = {}
    for item in items:
        groups.setdefault(item.group_key, []).append(item)
    return list(groups.values())


def session_aware_split(
    items: list[GroupedItem],
    ratios: tuple[float, float, float] = (0.70, 0.15, 0.15),
    seed: int = 42,
) -> tuple[list[GroupedItem], list[GroupedItem], list[GroupedItem]]:
    """Stratified, group-aware 70/15/15 split.

    Groups (sessions = the same physical object) are assigned atomically so an
    object never straddles train/val/test. Stratifies on class at the group
    level; final class coverage is enforced with deterministic rebalancing."""
    rng = random.Random(seed)
    groups = group_by_session(items)
    by_class: dict[str, list[list[GroupedItem]]] = {c: [] for c in CLASSES}
    for g in groups:
        cls = g[0].cls
        by_class.setdefault(cls, []).append(g)

    train, val, test = [], [], []
    for cls, cls_groups in by_class.items():
        cls_groups = list(cls_groups)
        rng.shuffle(cls_groups)
        n = len(cls_groups)
        n_val = max(1, round(n * ratios[1])) if n >= 3 else 0
        n_test = max(1, round(n * ratios[2])) if n >= 3 else 0
        val.extend(g for g in cls_groups[:n_val])
        test.extend(g for g in cls_groups[n_val:n_val + n_test])
        train.extend(g for g in cls_groups[n_val + n_test:])

    records: list[tuple[str, list[list[GroupedItem]]]] = [
        ("train", train), ("val", val), ("test", test),
    ]
    for name, part in records:
        if not part:
            continue
        # deterministic sample-space shuffle within each split
        for g in part:
            rng.shuffle(g) if not isinstance(g, list) else None
    flat = lambda parts: [item for g in parts for item in g]

    # Rebalance: classes with zero images in a split inherit one (small) group.
    for name, part in records:
        present = {g[0].cls for g in part}
        missing = set(CLASSES) - present
        for m in missing:
            donor = min((g for g in train if g[0].cls == m), key=len, default=None)
            if donor is not None:
                train.remove(donor)
                part.append(donor)
            else:
                donor = min((g for g in test if g[0].cls == m), key=len, default=None)
                if donor is not None:
                    test.remove(donor)
                    part.append(donor)

    return flat(train), flat(val), flat(test)


# ---------------------------------------------------------------------------
# realistic station-camera augmentation (used by the pilot generator only)
# ---------------------------------------------------------------------------

def simulate_station_augment(image: Image.Image, rng: random.Random) -> Image.Image:
    """Mild, realistic station-camera variation.

    Operations (all tuned to the plausible range of a fixed top-down/rear
    station camera): slight rotation, scale/crop, brightness, contrast, mild
    blur, mild perspective, and neutral background fill where rotation exposes
    the tray. Deliberately NOT extreme — the aim is distribution realism."""
    img = image.convert("RGB")
    w, h = img.size

    # slight rotation (±6°) with a blurred-edge (neutral tray) background fill.
    if rng.random() < 0.7:
        angle = rng.uniform(-6.0, 6.0)
        mean = ImageEnhance.Brightness(img).enhance(0.55).resize((max(w // 8, 4), max(h // 8, 4)))
        bg = mean.filter(ImageFilter.GaussianBlur(6)).resize((w, h))
        rotated = img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
        img = Image.composite(rotated, bg, rotated.split()[0])
        img = ImageOps.fit(img, (w, h), method=Image.Resampling.BICUBIC, centering=(0.5, 0.5))

    # mild perspective: skew corners by up to ±2% of the frame.
    if rng.random() < 0.5:
        d = rng.uniform(0.0, 0.02)
        quads = (
            (0, 0), (w, int(h * d)),
            (int(w * (1 - d)), int(h * (1 - d))), (int(w * d), h),
        )
        try:
            img = img.transform((w, h), Image.Transform.QUAD, quads, resample=Image.Resampling.BICUBIC)
        except Exception:
            pass

    # scale/crop: effective zoom 0.92–1.08 via center crop + resize back.
    zoom = rng.uniform(0.92, 1.08)
    if abs(zoom - 1.0) > 0.01:
        cw, ch = max(40, int(w * zoom)), max(40, int(h * zoom))
        left, top = (w - cw) // 2, (h - ch) // 2
        img = img.crop((left, top, left + cw, top + ch)).resize((w, h), Image.Resampling.BICUBIC)

    # brightness 0.75–1.25, contrast 0.8–1.15.
    img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.75, 1.25))
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.8, 1.15))

    # mild blur (σ ≤ 1.2).
    if rng.random() < 0.35:
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.2, 1.2)))

    return img