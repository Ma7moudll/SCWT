"""Real /health (T4): reports component truth — never a hardcoded ok."""
from __future__ import annotations


def test_health_reports_db_ok_and_mqtt_down_as_degraded(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"ok", "degraded"}
    # In the test env nothing listens on the broker port -> degraded, and
    # the response must SAY so instead of pretending.
    assert body["db"] == "ok"
    if body["status"] == "degraded":
        assert body["mqtt"] != "ok"


def test_health_shape_has_all_components(client):
    body = client.get("/health").json()
    assert {"db", "mqtt", "ai"} <= set(body.keys())
