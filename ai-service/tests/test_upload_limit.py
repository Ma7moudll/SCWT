"""Upload size limit for /predict (security hardening).

Invariant: received bytes > MAX_UPLOAD_BYTES  ->  immediate 413, no decode,
no quality gate, no inference. The endpoint streams in 1 MiB chunks, so an
oversized body never fully materializes in memory.
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import ai_settings


def _fixture_bytes(name: str) -> bytes:
    from tests.test_inference import _fixture

    return _fixture(name)


class _CountingReader:
    """Fake upload spool: yields `payload` in bounded chunks and records how
    many bytes were actually pulled — proves early termination without
    building a multi-gigabyte body."""

    def __init__(self, payload: bytes):
        self._payload = payload
        self._pos = 0
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = len(self._payload) - self._pos
        chunk = self._payload[self._pos : self._pos + size]
        self._pos += len(chunk)
        self.bytes_read += len(chunk)
        return chunk

    def close(self) -> None:  # pragma: no cover - interface parity
        pass


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def tiny_limit(monkeypatch):
    """Shrink the cap to just above the smallest real fixture so oversized
    payloads stay tiny while the boundary logic stays identical."""
    limit = len(_fixture_bytes("low_conf.png")) + 10
    monkeypatch.setattr(ai_settings, "max_upload_bytes", limit)
    return limit


def test_normal_image_below_limit_unchanged(client):
    r = client.post(
        "/predict",
        files={"image": ("capture.png", _fixture_bytes("high_conf_plastic.png"), "image/png")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["predicted_class"] in ("plastic", "metal", "paper", "other")


def test_exactly_at_limit_is_accepted(client, tiny_limit, monkeypatch):
    payload = _fixture_bytes("low_conf.png")  # == tiny_limit - 10
    assert len(payload) <= tiny_limit
    # A VALID frame at the boundary must reach the normal pipeline (not 413).
    r = client.post("/predict", files={"image": ("f.png", payload, "image/png")})
    assert r.status_code != 413


def test_one_byte_above_limit_rejected_before_gate_and_inference(
    client, tiny_limit, monkeypatch
):
    calls = {"gate": 0, "classifier": 0}

    def _boom_gate(self, data):  # pragma: no cover - must not run
        calls["gate"] += 1
        raise AssertionError("quality gate ran on an oversized upload")

    def _boom_classifier():  # pragma: no cover - must not run
        calls["classifier"] += 1
        raise AssertionError("inference ran on an oversized upload")

    monkeypatch.setattr("app.main.InputQualityGate.assess", _boom_gate)
    monkeypatch.setattr("app.main.get_classifier", _boom_classifier)

    payload = b"x" * (tiny_limit + 1)
    r = client.post("/predict", files={"image": ("big.bin", payload, "application/octet-stream")})
    assert r.status_code == 413, r.text
    assert "too large" in r.json()["detail"]
    assert calls == {"gate": 0, "classifier": 0}


def test_large_malformed_payload_rejected_before_decode(client, tiny_limit):
    # Random garbage well above the limit: decode would fail anyway, but the
    # SIZE guard must fire first (413, not the corrupt-image 422).
    payload = bytes(range(256)) * ((tiny_limit // 256) + 2)
    r = client.post("/predict", files={"image": ("junk.bin", payload, "application/octet-stream")})
    assert r.status_code == 413, r.text


def test_streaming_reader_never_pulls_beyond_limit_plus_chunk(client, monkeypatch):
    """Direct unit proof of memory safety: the chunked reader stops pulling
    once the counter exceeds the cap; total bytes touched stays below
    limit + chunk even for an arbitrarily large virtual payload."""
    from app.main import _CHUNK, _read_limited
    from fastapi import UploadFile

    huge = b"\xff" * (_CHUNK * 10)  # virtual 10-chunk body, never fully held
    limit = _CHUNK * 3
    monkeypatch.setattr(ai_settings, "max_upload_bytes", limit)

    reader = _CountingReader(huge)
    upload = UploadFile(filename="huge.bin", file=reader)

    with pytest.raises(Exception) as excinfo:
        _read_limited(upload)
    assert getattr(excinfo.value, "status_code", None) == 413
    assert reader.bytes_read <= limit + _CHUNK, (
        "reader must stop streaming immediately after exceeding the cap"
    )
