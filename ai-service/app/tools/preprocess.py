"""Single deterministic preprocessing path for the served classifier.

Every consumer that turns pixels into model input uses [to_model_input]:
the local probe script, the deployed FastAPI endpoint and (in the future) the
station camera driver. Centralising the geometry + normalization here means the
three paths can never diverge.

The math is fixed and mirrors the training pipeline exactly: resize to
`resize` (256) -> center-crop `input_size` (224) -> ImageNet normalize ->
NCHW float32. Geometry/mean/std default to the known constants and are
overridden by `preprocess.json` beside the model artifact when present.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

DEFAULT_GEOMETRY = {"input_size": 224, "resize": 256}
DEFAULT_MEAN = (0.485, 0.456, 0.406)
DEFAULT_STD = (0.229, 0.224, 0.225)


def load_preprocess_meta(model_path: str | Path) -> dict:
    """Read `preprocess.json` beside the model artifact (empty when absent)."""
    meta = Path(model_path).with_name("preprocess.json")
    if not meta.exists():
        return {}
    return json.loads(meta.read_text(encoding="utf-8"))


def decode_image(data: bytes) -> Image.Image:
    """Decode raw image bytes to an RGB [Image].

    Raises [UnidentifiedImageError] for corrupt/truncated payloads and
    [ValueError] for empty input — the same contract the gate relies on.
    """
    if not data:
        raise ValueError("Empty image data")
    return Image.open(io.BytesIO(data)).convert("RGB")


def to_model_input(
    image: Image.Image,
    model_path: str | Path = "models/model.onnx",
) -> np.ndarray:
    """PIL image -> NCHW float32 batch tensor, byte-for-byte the training path.

    Identity of output is guaranteed by reading the same `preprocess.json`
    the training pipeline wrote (see `app.training.train`), with fallback to
    the documented constants.
    """
    meta = load_preprocess_meta(model_path)
    size = int(meta.get("input_size", DEFAULT_GEOMETRY["input_size"]))
    resize = int(meta.get("resize", DEFAULT_GEOMETRY["resize"]))
    mean = np.asarray(meta.get("mean", DEFAULT_MEAN), dtype=np.float32)
    std = np.asarray(meta.get("std", DEFAULT_STD), dtype=np.float32)

    image = image.convert("RGB").resize((resize, resize))
    offset = (resize - size) // 2
    image = image.crop((offset, offset, offset + size, offset + size))
    arr = np.asarray(image, dtype=np.float32) / 255.0
    arr = (arr - mean) / std
    return arr.transpose(2, 0, 1)[None, ...]


def to_grayscale_work(image: Image.Image, target_size: int = 256) -> np.ndarray:
    """Grayscale uint8 array with the longest side clamped to `target_size`.

    Downscaling keeps the gate heuristics latency flat no matter the camera
    resolution while preserving the low-frequency structure the gate inspects
    (brightness, contrast, blur, edge layout).
    """
    image = image.convert("L")
    w, h = image.size
    scale = min(1.0, target_size / max(w, h))
    if scale < 1.0:
        image = image.resize((max(1, int(w * scale)), max(1, int(h * scale))))
    return np.asarray(image, dtype=np.uint8)
