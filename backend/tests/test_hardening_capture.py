"""Capture upload cap (T6): oversized bodies are rejected with 413 BEFORE the
image is buffered, and tiny caps prove the limit is enforced server-side."""
from __future__ import annotations

from .conftest import FakeAi, FakePublisher, _predict
from .test_deposit import create_session


def _install_fake_capture_ai(monkeypatch) -> FakePublisher:
    """Capture uploads run the REAL PredictService; swap in the stub."""
    from app.routers import deposit as deposit_router
    from app.services.deposit_service import DepositService
    from app.services.predict_service import PredictService

    fp = FakePublisher()
    monkeypatch.setattr(deposit_router, "_publisher", fp)
    monkeypatch.setattr(
        deposit_router,
        "DepositService",
        lambda pub: DepositService(pub, predictor=PredictService(ai=FakeAi("plastic", 0.95))),
    )
    return fp


def test_oversized_capture_rejected_413(client, auth, demo_session, publisher, monkeypatch):
    _install_fake_capture_ai(monkeypatch)
    from app.routers import deposit as deposit_router

    # Shrink the cap so the test does not allocate 8 MiB.
    monkeypatch.setattr(deposit_router.settings, "max_upload_bytes", 1024)

    pred = _predict(client, demo_session, FakeAi("plastic", 0.95), monkeypatch)
    session = create_session(client, auth, pred)

    r = client.post(
        "/api/v1/deposit/capture",
        headers={**auth, "X-Station-Key": "ecolamp-dev-station-key"},
        data={
            "operation_id": session["operation_id"],
            "station_code": "ST-001",
        },
        files={"image": ("frame.jpg", b"x" * 2048, "image/jpeg")},
    )
    assert r.status_code == 413
    assert r.json()["error"] == "payload_too_large"


def test_content_length_precheck_rejects_before_read(client, auth, demo_session, publisher, monkeypatch):
    import httpx

    _install_fake_capture_ai(monkeypatch)
    from app.routers import deposit as deposit_router

    monkeypatch.setattr(deposit_router.settings, "max_upload_bytes", 10)
    pred = _predict(client, demo_session, FakeAi("plastic", 0.95), monkeypatch)
    session = create_session(client, auth, pred)

    r = client.post(
        "/api/v1/deposit/capture",
        headers={**auth, "X-Station-Key": "ecolamp-dev-station-key"},
        data={
            "operation_id": session["operation_id"],
            "station_code": "ST-001",
        },
        files={"image": ("frame.jpg", b"y" * 64, "image/jpeg")},
    )
    assert isinstance(r, httpx.Response)
    assert r.status_code == 413


def test_normal_size_capture_still_accepted(client, auth, demo_session, publisher, monkeypatch):
    _install_fake_capture_ai(monkeypatch)
    from app.routers import deposit as deposit_router

    monkeypatch.setattr(deposit_router.settings, "max_upload_bytes", 8 * 1024 * 1024)
    pred = _predict(client, demo_session, FakeAi("plastic", 0.95), monkeypatch)
    session = create_session(client, auth, pred)

    r = client.post(
        "/api/v1/deposit/capture",
        headers={**auth, "X-Station-Key": "ecolamp-dev-station-key"},
        data={
            "operation_id": session["operation_id"],
            "station_code": "ST-001",
        },
        files={"image": ("frame.jpg", b"z" * 512, "image/jpeg")},
    )
    assert r.status_code == 200, r.text
