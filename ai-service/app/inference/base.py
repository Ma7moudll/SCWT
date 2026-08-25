"""Classifier contracts. The backend only depends on the `WasteClassifier`
interface; swapping `RealInferenceClassifier` for `DevelopmentClassifier` (and
later a different model) never changes the service contract."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ClassificationResult:
    predicted_class: str  # plastic | metal | paper | other
    confidence: float  # 0..1
    model: str  # 'real' | 'development'

    def to_dict(self) -> dict:
        return {
            "predicted_class": self.predicted_class,
            "confidence": round(float(self.confidence), 4),
            "model": self.model,
        }


class WasteClassifier(ABC):
    """Clean model interface. `predict` takes decoded RGB image bytes and
    returns a [ClassificationResult]. Implementations own model loading and
    preprocessing."""

    @abstractmethod
    def predict(self, image_data: bytes) -> ClassificationResult:
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...