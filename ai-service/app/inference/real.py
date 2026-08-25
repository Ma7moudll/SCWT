"""Deep-learning classifier backed by a trained ONNX artifact.

The default production path (`AI_SERVICE_CLASSIFIER=real`). Requires a trained
artifact at `AI_MODEL_PATH` (default: `ai-service/models/model.onnx`) with its
`preprocess.json` (input geometry, normalization and class order written by the
training pipeline). If the artifact is missing a clear [ModelNotReadyError] is
raised — the service never pretends an untrained model works, and the
development classifier is never reachable from this path.

The DEVELOPMENT_FORCE_* environment variables (used only as an isolated test
fixture for `DevelopmentClassifier`) are deliberately NOT read here.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path

import numpy as np
import PIL.Image

from .base import ClassificationResult, WasteClassifier

# Adversarial classes the service can never report.
VALID = {"plastic", "metal", "paper", "other"}
DEFAULT_CLASSES = ("plastic", "metal", "paper", "other")


class ModelNotReadyError(RuntimeError):
    pass


class RealInferenceClassifier(WasteClassifier):
    def __init__(self, model_path: str | None = None, backend: str = "auto") -> None:
        self.model_path = Path(model_path or os.environ.get("AI_MODEL_PATH", "") or "")
        self.backend_name = self._detect_backend(self.model_path, backend)
        if self.backend_name is None:
            raise ModelNotReadyError(
                "No trained model artifact found at "
                f"{self.model_path or '<unset>'}. Train/export a model (see "
                "app/training/train.py) and set AI_MODEL_PATH, or run the "
                "isolated DevelopmentClassifier (AI_SERVICE_CLASSIFIER=development) "
                "which is explicitly labeled as non-real."
            )
        self._session = self._load(self.model_path, self.backend_name)
        self.classes = self._load_metadata(self.model_path)
        if len(self.classes) != 4 or any(c not in VALID for c in self.classes):
            raise ModelNotReadyError(
                f"model classes {self.classes} must be exactly the 4 production "
                f"classes {list(VALID)} (see preprocess.json)"
            )

    @staticmethod
    def _detect_backend(model_path: Path, backend: str) -> str | None:
        if not model_path.exists():
            return None
        if model_path.suffix == ".onnx":
            try:
                import onnxruntime  # noqa: F401

                return "onnx"
            except ImportError:
                return None
        if model_path.suffix == ".tflite":
            try:
                import tflite_runtime  # noqa: F401

                return "tflite"
            except ImportError:
                return None
        if model_path.suffix in (".pt", ".pth"):
            try:
                import torch  # noqa: F401

                return "torch"
            except ImportError:
                return None
        return None

    @staticmethod
    def _load(model_path: Path, backend: str):
        if backend == "onnx":
            import onnxruntime as ort

            return ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        if backend == "tflite":
            import tflite_runtime.interpreter as tflite

            interp = tflite.Interpreter(model_path=str(model_path))
            interp.allocate_tensors()
            return interp
        if backend == "torch":
            import torch

            return torch.jit.load(str(model_path), map_location="cpu")
        raise ModelNotReadyError(f"Unsupported backend {backend}")

    @staticmethod
    def _load_metadata(model_path: Path) -> tuple[str, ...]:
        """Read class order + geometry from `preprocess.json` beside the model
        (written by the training pipeline); fall back to known defaults."""
        meta = model_path.with_name("preprocess.json")
        if meta.exists():
            data = json.loads(meta.read_text(encoding="utf-8"))
            classes = tuple(data.get("classes") or DEFAULT_CLASSES)
            return classes
        return DEFAULT_CLASSES

    @property
    def model_name(self) -> str:
        return "real"

    def predict(self, image_data: bytes) -> ClassificationResult:
        image = PIL.Image.open(io.BytesIO(image_data)).convert("RGB")
        tensor = self._preprocess(image)
        probabilities = self._forward(tensor)
        if probabilities.ndim == 2:
            probabilities = probabilities[0]
        if probabilities.size != len(self.classes):
            raise ModelNotReadyError(
                f"model output width {probabilities.size} != classes "
                f"{len(self.classes)} — stale artifact?"
            )
        idx = int(np.argmax(probabilities).item())
        predicted = self.classes[idx]
        confidence = float(np.clip(probabilities[idx], 0.0, 1.0))
        return ClassificationResult(
            predicted_class=predicted if predicted in VALID else "other",
            confidence=round(confidence, 4),
            model="real",
        )

    def _preprocess(self, image: PIL.Image.Image) -> np.ndarray:
        """Shared deterministic preprocess: resize -> center-crop -> normalize
        -> NCHW. Delegates to `app.tools.preprocess.to_model_input` so the
        deployed API and the camera probe use byte-identical pixel math (see
        docs/ai-validation.md)."""
        from ..tools.preprocess import to_model_input

        return to_model_input(image, self.model_path)

    def _forward(self, tensor: np.ndarray) -> np.ndarray:
        if self.backend_name == "onnx":
            input_name = self._session.get_inputs()[0].name
            outputs = self._session.run(None, {input_name: tensor})
            return np.asarray(outputs[0], dtype=np.float32)
        if self.backend_name == "tflite":
            det = self._session.get_input_details()
            out = self._session.get_output_details()
            self._session.set_tensor(det[0]["index"], tensor)
            self._session.invoke()
            return np.asarray(self._session.get_tensor(out[0]["index"]), dtype=np.float32)
        import torch

        with torch.no_grad():
            logits = self._session(torch.from_numpy(tensor))
            return torch.softmax(logits, dim=1).squeeze(0).numpy()