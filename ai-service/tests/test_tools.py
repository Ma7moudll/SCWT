"""Regression tests for the data-collection / model-validation pipeline tools.

Covers the deterministic, leakage-free split, metadata uniqueness, duplicate
detection, the simulated-station augmentation contract, and temperature-calibration
determinism. These mirror the rules the CLI tools enforce.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.tools.calibrate import (
    expected_calibration_error,
    fit_temperature,
    nll,
    temperature_scaled,
)
from app.tools.common import (
    GroupedItem,
    append_metadata,
    find_duplicates,
    find_near_duplicates,
    load_image_samples,
    new_image_id,
    session_aware_split,
    simulate_station_augment,
    validate_class,
)

CLASSES = ("plastic", "metal", "paper", "other")


@pytest.fixture
def sample_root(tmp_path: Path) -> Path:
    rng = np.random.default_rng(1)
    for cls in CLASSES:
        d = tmp_path / cls
        d.mkdir()
        for i in range(4):
            arr = rng.integers(0, 256, (32, 32, 3), dtype=np.uint8)
            Image.fromarray(arr).save(d / f"{cls}_{i}.png")
    return tmp_path


class TestClassValidation:
    def test_accepts_supported_classes(self):
        assert validate_class("plastic") == "plastic"
        assert validate_class("Metal") == "metal"

    def test_rejects_unsupported(self):
        for bad in ("glass", "banana", "mixed", ""):
            with pytest.raises(ValueError):
                validate_class(bad)


class TestMetadata:
    def test_append_then_load_roundtrip(self, tmp_path):
        row = {
            "image_id": new_image_id(), "path": "plastic/x.jpg", "class": "plastic",
            "source": "simulated-station-pilot", "camera": "c", "lighting": "led",
            "background": "tray", "occlusion": "none", "object_count": "1",
            "session_id": "s1", "object_id": "o1", "timestamp": "t",
        }
        append_metadata(tmp_path, row)
        rows = _load_rows(tmp_path)
        assert len(rows) == 1
        assert rows[0]["image_id"] == row["image_id"]
        assert rows[0]["source"] == "simulated-station-pilot"

    def test_duplicate_image_id_rejected(self, tmp_path):
        base = {
            "image_id": "dup-1", "path": "plastic/x.jpg", "class": "plastic",
            "source": "simulated-station-pilot", "camera": "", "lighting": "",
            "background": "", "occlusion": "", "object_count": "",
            "session_id": "", "object_id": "", "timestamp": "",
        }
        append_metadata(tmp_path, dict(base))
        with pytest.raises(FileExistsError):
            append_metadata(tmp_path, dict(base, path="plastic/y.jpg"))


def _load_rows(data_root):
    from app.tools.common import load_metadata

    return load_metadata(data_root)


class TestDuplicateDetection:
    def test_exact_duplicates_found(self, sample_root):
        src = sample_root / "metal" / "metal_0.png"
        dst_dir = sample_root / "plastic"  # existing class folder
        (dst_dir / "copy_a.png").write_bytes(src.read_bytes())
        (dst_dir / "copy_b.png").write_bytes(src.read_bytes())
        samples = load_image_samples(sample_root)
        groups = find_duplicates(samples)
        assert groups and max(len(g) for g in groups) == 3

    def test_unique_md5_no_false_positive(self, sample_root):
        samples = load_image_samples(sample_root)
        assert find_duplicates(samples) == []

    def test_near_duplicates_detection(self, tmp_path):
        import random

        rng = np.random.default_rng(9)
        noise = rng.integers(0, 256, (64, 64, 3), dtype=np.uint8)
        a = Image.fromarray(noise)
        # b is pixel-identical to a -> dHash(0), definitely proximity.
        b = Image.fromarray(np.array(a))
        far = Image.new("RGB", (64, 64), (10, 10, 10))
        d = tmp_path / "plastic"
        d.mkdir()
        a.save(d / "a.png")
        b.save(d / "b.png")
        far.save(d / "c.png")
        pairs = find_near_duplicates(load_image_samples(tmp_path))
        paths = {p[0].basename for p in pairs} | {p[1].basename for p in pairs}
        assert "a.png" in paths and "b.png" in paths
        assert "c.png" not in paths


class TestLesionFreeSplit:
    def _items(self, n_groups_per_class=3, variants=4):
        items = []
        for g in range(n_groups_per_class):
            for cls in CLASSES:
                key = f"session-{cls}-{g}"
                for v in range(variants):
                    items.append(GroupedItem(path=Path(f"{key}/{v}.jpg"), cls=cls,
                                             group_key=key))
        return items

    def test_total_counts_preserved(self):
        items = self._items()
        train, val, test = session_aware_split(items, seed=42)
        assert len(train) + len(val) + len(test) == len(items)

    def test_groups_never_straddle_splits(self):
        items = self._items()
        train, val, test = session_aware_split(items, seed=42)
        for name, part in (("train", train), ("val", val), ("test", test)):
            present = {i.group_key for i in part}
            assert len(present) * 4 == len(part), "a session must stay whole"

    def test_every_class_represented_in_every_split(self):
        items = self._items()
        train, val, test = session_aware_split(items, seed=42)
        for part in (train, val, test):
            assert set(i.cls for i in part) == set(CLASSES)

    def test_deterministic(self):
        items = self._items()
        t1, v1, te1 = session_aware_split(items, seed=7)
        t2, v2, te2 = session_aware_split([GroupedItem(**i.__dict__) for i in items], seed=7)
        assert ([i.path for i in t1] == [i.path for i in t2] and
                [i.path for i in v1] == [i.path for i in v2] and
                [i.path for i in te1] == [i.path for i in te2])


class TestSimulatedAugmentation:
    def test_returns_same_size_rgb(self):
        base = Image.new("RGB", (128, 96), (50, 80, 120))
        import random

        out = simulate_station_augment(base, random.Random(1))
        assert out.size == (128, 96)
        assert out.mode == "RGB"

    def test_deterministic_for_same_seed(self):
        import random

        base = Image.new("RGB", (128, 96), (50, 80, 120))
        a = simulate_station_augment(base, random.Random(7))
        b = simulate_station_augment(base, random.Random(7))
        assert list(a.getdata()) == list(b.getdata())


class TestCalibrationTools:
    def _synthetic(self, n=500, seed=0):
        rng = np.random.default_rng(seed)
        probs = rng.dirichlet(np.ones(4), size=n)
        probs[:, 0] = np.clip(probs[:, 0] + 0.15, 0.01, 0.99)
        probs = probs / probs.sum(axis=1, keepdims=True)
        y = probs.argmax(axis=1)
        return probs, y

    def test_ece_within_unit_interval(self):
        probs, y = self._synthetic()
        ece = expected_calibration_error(probs, y, bins=15)
        assert 0.0 <= ece <= 1.0

    def test_nll_finite(self):
        probs, y = self._synthetic()
        assert np.isfinite(nll(probs, y))

    def test_temperature_fit_deterministic(self):
        probs, y = self._synthetic(seed=3)
        t1 = fit_temperature(probs, y)
        t2 = fit_temperature(probs, y)
        assert t1 == pytest.approx(t2, abs=1e-9)
        assert 0.1 <= t1 <= 10.0

    def test_calibration_improves_or_keeps_nll(self):
        from app.tools.calibrate import raw_stats, temperature_scaled

        probs, y = self._synthetic(seed=5)
        T = fit_temperature(probs, y)
        before = raw_stats(probs, y)
        after = raw_stats(temperature_scaled(probs, T), y)
        assert after.nll <= before.nll + 1e-6


def test_calibration_probs_helper_shape():
    probs = np.ones((4, 4)) / 4
    scaled = temperature_scaled(probs, 2.0)
    assert scaled.shape == probs.shape
    assert np.allclose(scaled.sum(axis=1), 1.0)