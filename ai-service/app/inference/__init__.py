from __future__ import annotations

from functools import lru_cache

from ..config import ai_settings  # noqa: F401
from .base import ClassificationResult, WasteClassifier
from .development import DevelopmentClassifier
from .real import ModelNotReadyError, RealInferenceClassifier


def build_classifier() -> WasteClassifier:
    """Factory. `real` is the production path and raises [ModelNotReadyError]
    when no trained artifact exists, so the system can never silently claim an
    untrained model is accurate.

    `development` is an explicitly isolated test fixture (clearly labelled
    `model=development` -> backend `source=demo`). Its force knobs are NEVER
    passed to the real classifier; production inference reads only the model
    artifact."""
    mode = ai_settings.classifier.lower()
    if mode == "real":
        return RealInferenceClassifier(model_path=ai_settings.model_path or None)
    if mode == "development":
        return DevelopmentClassifier(
            force_class=ai_settings.development_force_class,
            force_confidence=ai_settings.development_force_confidence,
        )
    raise ValueError(f"Unknown classifier mode {mode!r}")


@lru_cache
def get_classifier() -> WasteClassifier:
    return build_classifier()