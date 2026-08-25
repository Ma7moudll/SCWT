"""AI prediction policy tests: confidence levels, routing table, wire shape."""
from __future__ import annotations

from .conftest import FakeAi, _predict


def _predict_conf(client, demo_session, monkeypatch, cls, conf):
    return _predict(client, demo_session, FakeAi(cls, conf), monkeypatch)


def test_high_confidence_plastic_routes_to_position_1(client, demo_session, monkeypatch):
    pred = _predict_conf(client, demo_session, monkeypatch, "plastic", 0.96)
    assert pred["predicted_class"] == "plastic"
    assert pred["confidence_level"] == "high"
    assert pred["destination_position"] == 1
    assert pred["potential_points"] == 5
    assert pred["recyclable"] is True


def test_metal_routes_to_position_2_points_10(client, demo_session, monkeypatch):
    pred = _predict_conf(client, demo_session, monkeypatch, "metal", 0.91)
    assert pred["destination_position"] == 2
    assert pred["potential_points"] == 10


def test_paper_other_routing(client, demo_session, monkeypatch):
    paper = _predict_conf(client, demo_session, monkeypatch, "paper", 0.9)
    assert paper["destination_position"] == 3
    other = _predict_conf(client, demo_session, monkeypatch, "other", 0.9)
    assert other["destination_position"] == 4
    assert other["recyclable"] is False
    assert other["potential_points"] == 0


def test_medium_confidence_level(client, demo_session, monkeypatch):
    pred = _predict_conf(client, demo_session, monkeypatch, "plastic", 0.60)
    assert pred["confidence_level"] == "medium"


def test_low_confidence_level(client, demo_session, monkeypatch):
    pred = _predict_conf(client, demo_session, monkeypatch, "plastic", 0.40)
    assert pred["confidence_level"] == "low"


def test_exact_confidence_boundaries(client, demo_session, monkeypatch):
    assert _predict_conf(client, demo_session, monkeypatch, "plastic", 0.80)["confidence_level"] == "high"
    assert _predict_conf(client, demo_session, monkeypatch, "plastic", 0.50)["confidence_level"] == "medium"
    assert _predict_conf(client, demo_session, monkeypatch, "plastic", 0.49)["confidence_level"] == "low"


def test_prediction_wire_has_prediction_id(client, demo_session, monkeypatch):
    pred = _predict_conf(client, demo_session, monkeypatch, "plastic", 0.9)
    for key in (
        "prediction_id", "operation_id", "predicted_class", "confidence",
        "confidence_level", "recyclable", "destination_position",
        "potential_points", "expires_at", "source",
    ):
        assert key in pred, key


def test_development_model_marked_as_demo_source(client, demo_session, monkeypatch):
    pred = _predict(client, demo_session, FakeAi("plastic", 0.9, model="development"), monkeypatch)
    assert pred["source"] == "demo"
    real = _predict(client, demo_session, FakeAi("plastic", 0.9, model="real"), monkeypatch)
    assert real["source"] == "ai"


def test_unknown_class_rejected(client, demo_session, monkeypatch):
    from app.routers import ai as ai_router
    from app.services.predict_service import PredictService

    monkeypatch.setattr(
        ai_router, "PredictService", lambda: PredictService(ai=FakeAi("cardboard", 0.9))
    )
    r = client.post(
        "/api/v1/ai/predict",
        headers={"Authorization": f"Bearer {demo_session}"},
        files={"image": ("capture.jpg", b"data", "image/jpeg")},
    )
    assert r.status_code == 422


def test_gate_rejection_passthrough(client, auth, monkeypatch):
    """A gate-rejected frame (NO_OBJECT / LOW_QUALITY / CORRUPT_IMAGE) from
    the AI service becomes a structured 422 with a machine-readable code and a
    user-facing `error` — so no prediction is persisted and no deposit session
    can be created, and the mobile app can show the right retake message."""
    from app.routers import ai as ai_router
    from app.services.ai_client import AiGateRejection

    class _Rejecting:
        def predict(self, *args, **kwargs):
            raise AiGateRejection(
                "LOW_QUALITY",
                "Image quality is too low. Move closer or improve the lighting.",
            )

    monkeypatch.setattr(ai_router, "PredictService", _Rejecting)
    r = client.post(
        "/api/v1/ai/predict",
        headers=auth,
        files={"image": ("grey.jpg", b"data", "image/jpeg")},
    )
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "LOW_QUALITY"
    assert "improve the lighting" in body["error"]


def test_gate_rejection_no_prediction_persisted(client, auth, monkeypatch):
    """Gate rejections must not leave any ai_prediction row behind."""
    from app.routers import ai as ai_router
    from app.services.ai_client import AiGateRejection
    from app.models import AiPrediction

    class _Rejecting:
        def predict(self, *args, **kwargs):
            raise AiGateRejection("NO_OBJECT", "No waste detected.")

    monkeypatch.setattr(ai_router, "PredictService", _Rejecting)
    r = client.post(
        "/api/v1/ai/predict",
        headers=auth,
        files={"image": ("bg.jpg", b"data", "image/jpeg")},
    )
    assert r.status_code == 422
    from app.database import SessionLocal

    with SessionLocal() as db:
        assert db.query(AiPrediction).count() == 0, "gate rejection must not persist a prediction"


def test_predict_requires_auth(client):
    r = client.post(
        "/api/v1/ai/predict",
        files={"image": ("capture.jpg", b"data", "image/jpeg")},
    )
    assert r.status_code == 401


def test_empty_image_rejected(client, auth):
    r = client.post(
        "/api/v1/ai/predict", headers=auth, files={"image": ("empty.jpg", b"", "image/jpeg")}
    )
    assert r.status_code == 422