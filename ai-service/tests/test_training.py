"""Training pipeline tests (skip cleanly when the dataset/ML stack is absent).

Covers the dataset prep contract, the deterministic split, and — crucially —
that the deployed ONNX preprocessing is byte-for-byte the preprocessing the
serving `RealInferenceClassifier` applies (parity between train and serve)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

APP_DIR = Path(__file__).resolve().parent.parent
def _import_missing(name: str) -> bool:
    try:
        __import__(name)
        return False
    except ImportError:
        return True


DATA_ROOT = APP_DIR / "data" / "raw"
MODEL_PATH = APP_DIR / "models" / "model.onnx"

has_dataset = pytest.mark.skipif(
    not (DATA_ROOT / "dataset-resized").exists(),
    reason=f"TrashNet dataset not present at {DATA_ROOT}",
)
has_torch = pytest.mark.skipif(_import_missing("torch"), reason="torch not installed")
has_model = pytest.mark.skipif(not MODEL_PATH.exists(), reason="model artifact absent")


@has_dataset
@has_torch
class TestDatasetPrep:
    def test_class_mapping_covers_all_six_source_classes(self):
        from app.training.dataset import CLASS_MAPPING, CLASS_TO_IDX, CLASSES

        assert set(CLASS_MAPPING) == {
            "plastic", "metal", "paper", "glass", "cardboard", "trash",
        }
        assert CLASS_MAPPING["plastic"] == "plastic"
        assert CLASS_MAPPING["metal"] == "metal"
        assert CLASS_MAPPING["paper"] == "paper"
        assert CLASS_MAPPING["glass"] == "other"
        assert CLASS_MAPPING["cardboard"] == "other"
        assert CLASS_MAPPING["trash"] == "other"
        assert set(CLASS_TO_IDX) == set(CLASSES) == {"plastic", "metal", "paper", "other"}

    def test_indexes_all_2527_images_and_mapped_distribution(self):
        from app.training.dataset import load_samples

        samples = load_samples(DATA_ROOT / "dataset-resized")
        assert len(samples) == 2527
        from app.training.dataset import class_counts

        counts = dict(class_counts(samples))
        assert counts["plastic"] == 482
        assert counts["metal"] == 410
        assert counts["paper"] == 594
        assert counts["other"] == 501 + 403 + 137  # glass + cardboard + trash

    def test_stratified_split_is_deterministic_and_balanced(self):
        from app.training.dataset import class_counts, load_samples, stratified_split

        samples = load_samples(DATA_ROOT / "dataset-resized")
        tr1, va1 = stratified_split(samples, seed=42)
        tr2, va2 = stratified_split(samples, seed=42)
        assert len(tr1) == len(tr2) and len(va1) == len(va2)
        assert class_counts(va1) == class_counts(va2)
        # every class must appear in both splits
        for cls in {"plastic", "metal", "paper", "other"}:
            assert cls in class_counts(va1)
            assert cls in class_counts(tr1)


@has_model
@has_torch
class TestTrainServeParity:
    def test_real_preprocessing_matches_training_preprocessing(self):
        from app.training.train import onnx_preprocess

        from app.inference.real import RealInferenceClassifier

        image = (APP_DIR / "tests" / "fixtures" / "high_conf_plastic.png").read_bytes()
        real = RealInferenceClassifier(model_path=str(MODEL_PATH))

        train_tensor = onnx_preprocess(image)
        serve_tensor = real._preprocess(
            __import__("PIL").Image.open(io_bytes(image)).convert("RGB")
        )
        assert train_tensor.shape == serve_tensor.shape
        np.testing.assert_allclose(train_tensor, serve_tensor, atol=1e-6)

    def test_deployed_onnx_classifies_fixture_like_serving_path(self):
        from app.training.train import load_onnx_session, onnx_preprocess
        from app.inference.real import RealInferenceClassifier

        image = (APP_DIR / "tests" / "fixtures" / "high_conf_plastic.png").read_bytes()
        real = RealInferenceClassifier(model_path=str(MODEL_PATH))
        session = load_onnx_session(MODEL_PATH)
        probs = session.run(None, {"input": onnx_preprocess(image)})[0][0]

        serving = real.predict(image)
        from app.training.dataset import CLASSES

        raw_index = int(np.argmax(probs))
        serving_index = list(CLASSES).index(serving.predicted_class)
        assert serving_index == raw_index
        assert serving.predicted_class == "plastic"


def io_bytes(data):
    import io

    return io.BytesIO(data)