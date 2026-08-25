"""Simulated station camera.

Picks a real training frame from `ai-service/data/station_capture/` (the same
bytes a future ESP32-CAM would snap) and uploads it to the backend
`POST /api/v1/deposit/capture` endpoint, authenticated with the station key.
The backend classifies the frame and issues the follow-up `route` command —
the simulator never decides the routing itself.
"""
from __future__ import annotations

import logging
from pathlib import Path

import httpx

from config import SimConfig

logger = logging.getLogger("sim.camera")


class CaptureUploader:
    """Snaps and uploads one real frame per `capture_request` command."""

    def __init__(self, cfg: SimConfig, client: httpx.Client | None = None) -> None:
        self.cfg = cfg
        self._client = client or httpx.Client(timeout=10.0)
        self._seq = 0

    def pick_frame(self) -> tuple[str, bytes]:
        """Returns (filename, bytes) of a real station-camera frame for the
        configured class, cycling through frames so captures differ."""
        frames = sorted((self.cfg.capture_dir / self.cfg.sim_capture_class).glob("*.jpg"))
        if not frames:
            raise FileNotFoundError(
                f"no frames in {self.cfg.capture_dir / self.cfg.sim_capture_class}"
            )
        frame = frames[self._seq % len(frames)]
        self._seq += 1
        return frame.name, frame.read_bytes()

    def upload(self, operation_id: str) -> dict:
        """POSTs the frame to the backend capture endpoint. Returns the parsed
        HTTP response so the caller can log/diagnose the classification result."""
        filename, data = self.pick_frame()
        url = f"{self.cfg.backend_url}/api/v1/deposit/capture"
        logger.info("[CAM] snap=%s class=%s upload op=%s", filename, self.cfg.sim_capture_class, operation_id)
        resp = self._client.post(
            url,
            files={"image": (filename, data, "image/jpeg")},
            data={"operation_id": operation_id, "station_code": self.cfg.station_code},
            headers={"X-Station-Key": self.cfg.station_api_key},
        )
        logger.info("[CAM] upload resp status=%s body=%s", resp.status_code, resp.text[:200])
        if resp.status_code == 401:
            logger.error("[CAM] station key rejected — check STATION_API_KEY vs backend station_api_key")
        return {
            "status_code": resp.status_code,
            "operation_id": operation_id,
            "body": resp.text,
        }