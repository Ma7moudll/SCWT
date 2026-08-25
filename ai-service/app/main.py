from __future__ import annotations

import time

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from PIL import UnidentifiedImageError

from .config import ai_settings
from .inference import get_classifier
from .inference.real import ModelNotReadyError
from .tools.quality_gate import (
    REJECTION_MESSAGES,
    GateState,
    InputQualityGate,
)

app = FastAPI(title="Recycle Vision AI")

# Single stateless gate instance (lazily created on first use).
_gate: InputQualityGate | None = None


def _gate_instance() -> InputQualityGate:
    global _gate
    if _gate is None:
        _gate = InputQualityGate()
    return _gate


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "classifier": _classifier_mode()}


def _reject(state: GateState, detail: str) -> JSONResponse:
    """Structured gate rejection. `CORRUPT_IMAGE` and friends are 422 with a
    machine-readable `code` so callers can distinguish retake flows."""
    return JSONResponse(
        status_code=422,
        content={"code": state.value, "detail": detail},
    )


_CHUNK = 1024 * 1024  # 1 MiB streaming window


def _read_limited(image: UploadFile) -> bytes:
    """Stream the upload with a hard byte cap.

    At most `limit + _CHUNK` bytes ever touch memory: the moment the
    accumulated size exceeds the configured maximum, the request is rejected
    (413) — BEFORE decode, quality gate or inference see a single byte of it.
    """
    limit = ai_settings.max_upload_bytes
    chunks: list[bytes] = []
    received = 0
    while True:
        chunk = image.file.read(_CHUNK)
        if not chunk:
            break
        received += len(chunk)
        if received > limit:
            image.file.close()
            raise HTTPException(
                status_code=413,
                detail="The uploaded image is too large. Please try a smaller photo.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@app.post("/predict")
def predict(image: UploadFile = File(...)) -> dict:
    data = _read_limited(image)
    if not data:
        return _reject(GateState.CORRUPT_IMAGE, "Empty image")

    # Camera/input gate runs BEFORE the classifier: blank, blurred, corrupt
    # and empty-background frames never reach predict and can never be routed
    # as high-confidence waste.
    gate_result = _gate_instance().assess(data)
    if gate_result.state is not GateState.VALID_FRAME:
        return _reject(
            gate_result.state, REJECTION_MESSAGES[gate_result.state]
        )

    try:
        classifier = get_classifier()
    except ModelNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        start = time.perf_counter()
        result = classifier.predict(data)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    except UnidentifiedImageError as exc:
        return _reject(
            GateState.CORRUPT_IMAGE,
            REJECTION_MESSAGES[GateState.CORRUPT_IMAGE],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"inference failed: {exc}") from exc
    return {**result.to_dict(), "elapsed_ms": elapsed_ms}


def _classifier_mode() -> str:
    from .config import ai_settings

    return ai_settings.classifier