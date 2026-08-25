"""AI-service tests.

- `DevelopmentClassifier`: isolated test fixture with deterministic behavior +
  honest labeling. Its force knobs are tested HERE as a fixture, they must never
  reach the real classifier.
- `RealInferenceClassifier`: loads the trained ONNX artifact (skipped cleanly
  when the artifact is absent) and MUST ignore DEVELOPMENT_FORCE_* variables.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from PIL import Image

from app.inference import DevelopmentClassifier, build_classifier, get_classifier
from app.inference.real import ModelNotReadyError, RealInferenceClassifier

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "model.onnx"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
VALID = {"plastic", "metal", "paper", "other"}


def _image_png(color) -> bytes:
    img = Image.new("RGB", (64, 64), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _fixture(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


def _make_real() -> RealInferenceClassifier:
    return RealInferenceClassifier(model_path=str(MODEL_PATH))


requires_model = pytest.mark.skipif(
    not MODEL_PATH.exists(),
    reason=f"trained model artifact not present at {MODEL_PATH}",
)


class TestDevelopmentClassifier:
    def test_blue_image_is_plastic(self):
        result = DevelopmentClassifier().predict(_image_png((20, 40, 200)))
        assert result.predicted_class == "plastic"
        assert result.model == "development"

    def test_red_bright_image_is_metal(self):
        result = DevelopmentClassifier().predict(_image_png((230, 160, 60)))
        assert result.predicted_class == "metal"

    def test_light_grey_image_is_paper(self):
        result = DevelopmentClassifier().predict(_image_png((230, 230, 230)))
        assert result.predicted_class == "paper"

    def test_dark_image_is_other(self):
        result = DevelopmentClassifier().predict(_image_png((40, 40, 40)))
        assert result.predicted_class == "other"

    def test_deterministic(self):
        data = _image_jpeg((20, 40, 200))
        a = DevelopmentClassifier().predict(data)
        b = DevelopmentClassifier().predict(data)
        assert a.to_dict() == b.to_dict()

    def test_confidence_clamped_to_unit_interval(self):
        result = DevelopmentClassifier(force_class="plastic", force_confidence=2.0).predict(_image_png((0, 0, 0)))
        assert 0.0 <= result.confidence <= 1.0

    def test_force_class_override_is_a_fixture_knob(self):
        result = DevelopmentClassifier(force_class="metal", force_confidence=0.88).predict(_image_png((0, 0, 0)))
        assert result.predicted_class == "metal"
        assert result.confidence == 0.88

    def test_model_name(self):
        assert DevelopmentClassifier().model_name == "development"


def _image_jpeg(color) -> bytes:
    img = Image.new("RGB", (64, 64), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class TestRealClassifierMissingArtifact:
    def test_raises_when_no_artifact(self):
        with pytest.raises(ModelNotReadyError):
            RealInferenceClassifier(model_path="/nonexistent/model.onnx")

    def test_message_explains_how_to_fix(self):
        with pytest.raises(ModelNotReadyError) as exc:
            RealInferenceClassifier(model_path="")
        assert "AI_MODEL_PATH" in str(exc.value)
        assert "development" in str(exc.value)


@requires_model
class TestRealClassifierWithArtifact:
    def test_loads_real_model_and_reports_name(self):
        assert _make_real().model_name == "real"

    def test_predict_returns_valid_wire_shape(self):
        result = _make_real().predict(_fixture("high_conf_plastic.png"))
        d = result.to_dict()
        assert d["model"] == "real"
        assert d["predicted_class"] in VALID
        assert 0.0 <= d["confidence"] <= 1.0

    def test_high_fixture_is_plastic_with_high_confidence(self):
        result = _make_real().predict(_fixture("high_conf_plastic.png"))
        assert result.predicted_class == "plastic"
        assert result.confidence >= 0.80

    def test_medium_fixture_lands_in_medium_band(self):
        result = _make_real().predict(_fixture("medium_conf.png"))
        assert 0.50 <= result.confidence < 0.80

    def test_low_fixture_lands_in_low_band(self):
        result = _make_real().predict(_fixture("low_conf.png"))
        assert result.confidence < 0.50

    def test_deterministic_on_identical_bytes(self):
        data = _fixture("high_conf_plastic.png")
        a = _make_real().predict(data)
        b = _make_real().predict(data)
        assert a.to_dict() == b.to_dict()


@requires_model
class TestProductionDoesNotDependOnDevelopmentOverrides:
    """The DEVELOPMENT_FORCE_* knobs are an isolated DevelopmentClassifier test
    fixture. Production (real) inference must ignore them entirely."""

    HIGH = _fixture("high_conf_plastic.png")

    def test_predict_is_identical_with_and_without_force_env(self, monkeypatch):
        baseline = _make_real().predict(self.HIGH)

        monkeypatch.setenv("DEVELOPMENT_FORCE_CLASS", "metal")
        monkeypatch.setenv("DEVELOPMENT_FORCE_CONFIDENCE", "0.99")
        forced = _make_real().predict(self.HIGH)

        assert forced.to_dict() == baseline.to_dict()
        assert forced.predicted_class != "metal", "force env must not leak in"

    def test_predict_image_driven_not_override_driven(self, monkeypatch):
        monkeypatch.setenv("DEVELOPMENT_FORCE_CLASS", "paper")
        monkeypatch.setenv("DEVELOPMENT_FORCE_CONFIDENCE", "0.97")
        result = _make_real().predict(self.HIGH)
        assert result.predicted_class == "plastic"
        assert result.confidence >= 0.80


class TestFactory:
    def test_development_env_returns_development_fixture(self):
        # conftest pins AI_SERVICE_CLASSIFIER=development for the fixture suite.
        assert get_classifier().model_name == "development"

    @requires_model
    def test_build_classifier_with_real_settings_returns_real(self, monkeypatch):
        from app import config as cfg

        monkeypatch.setattr(cfg.ai_settings, "classifier", "real")
        monkeypatch.setattr(cfg.ai_settings, "model_path", str(MODEL_PATH))
        classifier = build_classifier()
        assert isinstance(classifier, RealInferenceClassifier)
        assert classifier.model_name == "real"

    def test_result_has_wire_shape(self):
        result = get_classifier().predict(_image_png((20, 40, 200)))
        d = result.to_dict()
        assert d == {
            "predicted_class": "plastic",
            "confidence": result.confidence,
            "model": "development",
        }


class TestHttpContract:
    def test_health(self):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as c:
            r = c.get("/health")
            assert r.status_code == 200
            assert r.json()["classifier"] == "development"  # test env default

    def test_predict_returns_wire_contract(self):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as c:
            # A real waste frame (passes the camera gate) keeps the wire shape.
            r = c.post("/predict", files={"image": ("capture.png", _fixture("high_conf_plastic.png"), "image/png")})
            assert r.status_code == 200
            body = r.json()
            assert body["predicted_class"] in ("plastic", "metal", "paper", "other")
            assert 0.0 <= body["confidence"] <= 1.0
            assert body["model"] == "development"
            assert "elapsed_ms" in body

    def test_empty_image_rejected(self):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as c:
            r = c.post("/predict", files={"image": ("empty.jpg", b"", "image/jpeg")})
            assert r.status_code == 422
            assert r.json()["code"] == "CORRUPT_IMAGE"

    def test_corrupt_image_rejected_422_not_500(self):
        from fastapi.testclient import TestClient

        from app.main import app

        junk = b"\xff\xd8\xff\xe0-corrupted-not-a-jpeg" + os.urandom(64)
        with TestClient(app) as c:
            r = c.post("/predict", files={"image": ("corrupt.jpg", junk, "image/jpeg")})
            assert r.status_code == 422, r.text
            assert r.json()["code"] == "CORRUPT_IMAGE"

    def test_gate_rejects_grey_frame_before_classifier(self):
        from fastapi.testclient import TestClient

        from app.main import app

        grey = _image_jpeg((128, 128, 128))
        with TestClient(app) as c:
            r = c.post("/predict", files={"image": ("grey.jpg", grey, "image/jpeg")})
            assert r.status_code == 422, r.text
            assert r.json()["code"] in ("NO_OBJECT", "LOW_QUALITY")

    def test_gate_rejects_blank_black_frame(self):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as c:
            r = c.post("/predict", files={"image": ("black.jpg", _image_jpeg((0, 0, 0)), "image/jpeg")})
            assert r.status_code == 422
            assert r.json()["code"] == "LOW_QUALITY"