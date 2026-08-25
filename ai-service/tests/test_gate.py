"""Camera/input-gate tests.

Pins the pre-classification pipeline contract:
    Camera -> Input Quality Gate -> Object Presence Gate -> Preprocessing
             -> Waste Classifier -> Calibration -> Routing

The critical property — proven by a spy classifier — is that the classifier is
NEVER invoked for frames the gate rejects (blank, dark, bright, blurry,
corrupt, empty): background frames can never reach classification or routing.

Test frames are synthetic/OOD (blank, checkerboard, noise, blur, gradient,
corrupt) plus real TrashNet waste images from the pilot-test split. They are
NOT real station-camera captures.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageFilter

from app.inference.base import ClassificationResult
from app.tools.quality_gate import (
    GateState,
    InputQualityGate,
    ObjectPresenceDetector,
    PresenceResult,
    classify_with_gate,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "model.onnx"
DATA_TEST = Path(__file__).resolve().parent.parent / "data" / "station_capture_splits" / "test"

requires_model = pytest.mark.skipif(
    not MODEL_PATH.exists(),
    reason=f"trained model artifact not present at {MODEL_PATH}",
)


def _png(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def _solid(gray: int, size: int = 224) -> bytes:
    return _png(np.full((size, size, 3), gray, np.uint8))


def _noise(seed: int = 0, size: int = 224) -> bytes:
    rng = np.random.default_rng(seed)
    return _png(rng.integers(0, 256, (size, size, 3), dtype=np.uint8))


def _checkerboard(side: int = 16, size: int = 224) -> bytes:
    tile = np.indices((side, side)).sum(axis=0) % 2
    arr = np.repeat(np.repeat(tile, size // side, axis=0), size // side, axis=1)
    arr = (arr * 255).astype(np.uint8)
    return _png(np.stack([arr, arr, arr], axis=2))


def _heavy_blur(seed: int = 1, size: int = 224) -> bytes:
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 256, (size, size, 3), dtype=np.uint8)
    blurred = Image.fromarray(base).filter(ImageFilter.GaussianBlur(18))
    return _png(np.asarray(blurred, dtype=np.uint8))


def _gradient(size: int = 224) -> bytes:
    v = np.linspace(0, 255, size).astype(np.float32)[:, None]
    v = np.clip(v, 0, 255).astype(np.uint8)
    arr = np.stack([v] * 3, axis=2).repeat(size, axis=1)
    return _png(arr)


def _fixture(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


GATE = InputQualityGate()


def _state(data: bytes) -> GateState:
    return GATE.assess(data).state


class SpyClassifier:
    """Records whether predict() is ever invoked."""

    def __init__(self) -> None:
        self.calls = 0

    def predict(self, image_data: bytes) -> ClassificationResult:
        self.calls += 1
        return ClassificationResult(
            predicted_class="plastic", confidence=0.95, model="spy"
        )


class TestQualityRejections:
    def test_blank_black_is_low_quality(self):
        assert _state(_solid(0)) is GateState.LOW_QUALITY

    def test_blank_white_is_low_quality(self):
        assert _state(_solid(255)) is GateState.LOW_QUALITY

    def test_blank_grey_is_low_quality(self):
        assert _state(_solid(128)) is GateState.LOW_QUALITY

    def test_checkerboard_is_low_quality(self):
        assert _state(_checkerboard()) is GateState.LOW_QUALITY

    def test_heavy_blur_is_low_quality(self):
        assert _state(_heavy_blur()) is GateState.LOW_QUALITY

    def test_corrupt_bytes_is_corrupt_image(self):
        junk = b"\xff\xd8\xff\xe0-not-a-jpeg" + np.random.default_rng(2).bytes(64)
        assert _state(junk) is GateState.CORRUPT_IMAGE

    def test_empty_bytes_is_corrupt_image(self):
        assert _state(b"") is GateState.CORRUPT_IMAGE

    def test_tiny_frame_is_low_quality(self):
        small = _png(np.full((8, 8, 3), 128, np.uint8))
        assert _state(small) is GateState.LOW_QUALITY

    def test_flat_grey_background_is_low_quality(self):
        assert _state(_solid(150)) is GateState.LOW_QUALITY


class TestPresenceNoObject:
    def test_gradient_frame_is_no_object(self):
        assert _state(_gradient()) is GateState.NO_OBJECT

    def test_detector_interface_shape(self):
        result = ObjectPresenceDetector().detect(
            np.full((64, 64), 128, dtype=np.uint8)
        )
        assert isinstance(result, PresenceResult)
        assert result.present is False
        assert result.reason == "no_object_detected"
        assert isinstance(result.score, float)


class TestNoisePassesGate:
    """Full-frame random noise carries real edge content, so the lightweight
    gate lets it through to the classifier — a documented limitation (the
    backend confidence policy is the backstop). The gate is balanced, not
    OOD-optimised."""

    def test_noise_passes_the_gate(self):
        assert _state(_noise()) is GateState.VALID_FRAME


class TestValidWasteAccepted:
    def test_real_plastic_fixture_passes_gate(self):
        assert _state(_fixture("high_conf_plastic.png")) is GateState.VALID_FRAME

    def test_real_medium_fixture_passes_gate(self):
        assert _state(_fixture("medium_conf.png")) is GateState.VALID_FRAME

    @pytest.mark.skipif(
        not DATA_TEST.is_dir(),
        reason="pilot-test split not present (gitignored data)",
    )
    def test_all_pilot_test_waste_passes_gate(self):
        """Zero false rejection of valid waste on the whole pilot test split."""
        rejected: list[str] = []
        used = 0
        for cls_dir in sorted(DATA_TEST.iterdir()):
            if not cls_dir.is_dir():
                continue
            for path in sorted(cls_dir.glob("*.jpg")):
                used += 1
                if _state(path.read_bytes()) is not GateState.VALID_FRAME:
                    rejected.append(str(path.relative_to(DATA_TEST)))
        assert used > 0, "pilot-test split empty"
        assert not rejected, f"{len(rejected)} valid waste frames rejected: {rejected[:5]}"


class TestSpyClassifierNeverCalledOnRejection:
    """Requirement: the classifier must NEVER execute when the gate rejects."""

    @pytest.mark.parametrize("frame", [
        _solid(128), _solid(0), _solid(255), _checkerboard(),
        _heavy_blur(), _gradient(),
        b"\xff\xd8\xff\xe0-junk" + np.random.default_rng(3).bytes(32),
        b"",
    ])
    def test_rejected_frame_never_reaches_predict(self, frame):
        spy = SpyClassifier()
        result, classification = classify_with_gate(frame, spy)
        assert result.state is not GateState.VALID_FRAME
        assert classification is None
        assert spy.calls == 0

    def test_valid_frame_reaches_predict(self):
        spy = SpyClassifier()
        result, classification = classify_with_gate(
            _fixture("high_conf_plastic.png"), spy
        )
        assert result.state is GateState.VALID_FRAME
        assert spy.calls == 1
        assert classification.predicted_class == "plastic"
        assert classification.confidence == 0.95


class TestLatency:
    def test_gate_reports_elapsed_ms(self):
        result = GATE.assess(_fixture("high_conf_plastic.png"))
        assert result.state is GateState.VALID_FRAME
        assert 0.0 < result.elapsed_ms < 500.0

    def test_gate_is_faster_than_classifier_budget(self):
        # station camera budget sanity: gate must stay light (~tens of ms).
        times = [
            GATE.assess(_fixture("high_conf_plastic.png")).elapsed_ms
            for _ in range(10)
        ]
        mean = float(np.mean(times))
        assert mean < 100.0, f"gate too slow: {mean:.1f} ms"


class TestPreprocessParity:
    """The shared preprocess used by the gate pipeline path (and the local
    probe) must be byte-identical to the classifier/training preprocesses."""

    @requires_model
    def test_to_model_input_matches_real_classifier_preprocess(self):
        from app.inference.real import RealInferenceClassifier
        from app.tools.preprocess import to_model_input

        image = Image.open(io.BytesIO(_fixture("high_conf_plastic.png")))
        classifier = RealInferenceClassifier(model_path=str(MODEL_PATH))
        np.testing.assert_array_equal(
            to_model_input(image, MODEL_PATH),
            classifier._preprocess(image),
        )

    @requires_model
    def test_to_model_input_matches_training_preprocess(self):
        from app.training.train import onnx_preprocess
        from app.tools.preprocess import to_model_input

        image = Image.open(io.BytesIO(_fixture("high_conf_plastic.png")))
        np.testing.assert_allclose(
            to_model_input(image, MODEL_PATH),
            onnx_preprocess(image),
            atol=1e-6,
        )