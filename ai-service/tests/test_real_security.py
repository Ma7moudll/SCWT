"""Real-model safety regression: open-set frames must not be accepted at the
HIGH routing threshold, and predictions must stay inside the supported class
set. Skipped cleanly when the trained artifact is absent (CI without model)."""
from __future__ import annotations

import io
import os
from pathlib import Path

import numpy as np
import pytest

from app.inference.real import RealInferenceClassifier

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "model.onnx"
VALID = {"plastic", "metal", "paper", "other"}
HIGH = 0.80

requires_model = pytest.mark.skipif(
    not MODEL_PATH.exists(),
    reason=f"trained model artifact not present at {MODEL_PATH}",
)


def _png_bytes(arr: np.ndarray) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def classifier():
    return RealInferenceClassifier(model_path=str(MODEL_PATH))


@requires_model
class TestRealOpenSet:

    def _conf(self, classifier, arr: np.ndarray) -> float:
        return classifier.predict(_png_bytes(arr)).confidence

    def test_uniform_noise_stays_below_high_threshold(self, classifier):
        rng = np.random.default_rng(0)
        noise = rng.integers(0, 256, (224, 224, 3), dtype=np.uint8)
        assert self._conf(classifier, noise) < HIGH

    def test_blank_grey_stays_below_high_threshold(self, classifier):
        grey = np.full((224, 224, 3), 128, dtype=np.uint8)
        assert self._conf(classifier, grey) < HIGH

    def test_blank_white_stays_below_high_threshold(self, classifier):
        white = np.full((224, 224, 3), 255, dtype=np.uint8)
        assert self._conf(classifier, white) < HIGH

    def test_prediction_stays_inside_supported_classes(self, classifier):
        rng = np.random.default_rng(5)
        for _ in range(5):
            arr = rng.integers(0, 256, (64, 64, 3), dtype=np.uint8)
            result = classifier.predict(_png_bytes(arr))
            assert result.predicted_class in VALID
            assert 0.0 <= result.confidence <= 1.0