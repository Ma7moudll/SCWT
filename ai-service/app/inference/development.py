"""Development-only classifier. Clearly isolated and NEVER presented as real
model inference: the wire payload carries `model: "development"` and the
backend maps that to `source=demo` so the UI's subtle DEMO badge stays honest.

Uses cheap color/greyscale statistics — a deterministic stand-in so the whole
pipeline can be exercised before the real model exists. Every predicted class
is derived from the image, not a hardcoded breakthrough.
"""
from __future__ import annotations

import io
import os

import numpy as np
import PIL.Image

from .base import ClassificationResult, WasteClassifier


class DevelopmentClassifier(WasteClassifier):
    def __init__(
        self,
        force_class: str = "",
        force_confidence: float = 0.0,
    ) -> None:
        # Scenario/test reproducibility knobs (never the default path).
        self.force_class = force_class or os.environ.get("DEVELOPMENT_FORCE_CLASS", "")
        raw = os.environ.get("DEVELOPMENT_FORCE_CONFIDENCE", "")
        self.force_confidence = force_confidence if force_confidence > 0 else (float(raw) if raw else 0.0)

    @property
    def model_name(self) -> str:
        return "development"

    def predict(self, image_data: bytes) -> ClassificationResult:
        image = PIL.Image.open(io.BytesIO(image_data)).convert("RGB")
        arr = np.asarray(image.resize((64, 64)), dtype=np.float32)

        if self.force_class:
            cls = self.force_class
            conf = self.force_confidence if self.force_confidence > 0 else 0.96
        else:
            cls, conf = self._heuristic(arr)

        return ClassificationResult(
            predicted_class=cls,
            confidence=round(float(max(0.0, min(1.0, conf))), 4),
            model="development",
        )

    def _heuristic(self, arr: np.ndarray) -> tuple[str, float]:
        """Deterministic, documented dev heuristic:
        - strong blue/cyan tint            -> plastic
        - strong yellow/orange tint        -> metal
        - bright/grey-ish (low saturation) -> paper
        - otherwise                        -> other
        Baseline confidence 0.9, tuned by how decisive the dominant channel is.
        """
        r, g, b = arr[:, :, 0].mean(), arr[:, :, 1].mean(), arr[:, :, 2].mean()
        saturation = (max(r, g, b) - min(r, g, b)) / 255.0
        brightness = (r + g + b) / (3.0 * 255.0)

        if b > r * 1.15 and b > 110:
            return "plastic", 0.9 + 0.06 * min(1.0, saturation * 2)
        if r > b * 1.1 and g > 150 and r > 190:
            return "metal", 0.9 + 0.05 * min(1.0, saturation)
        if saturation < 0.18 and brightness > 0.55:
            return "paper", 0.9 + 0.05 * min(1.0, brightness)
        return "other", 0.88 if brightness < 0.4 else 0.7