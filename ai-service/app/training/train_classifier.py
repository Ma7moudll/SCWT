"""[legacy] Training CLI alias.

The real training pipeline lives in `app.training.train`:

    python -m app.training.train [--data-dir data/raw] [--epochs-head 8] ...

Run it from the `ai-service` directory. It prepares the dataset, trains a
MobileNetV3-Small head on TrashNet (mapped to plastic/metal/paper/other),
exports ONNX for the serving `RealInferenceClassifier`, writes the model
evaluation report + confusion matrix, and curates the confidence-band fixture
images used by tests and the E2E proof.
"""
from __future__ import annotations

from .train import main

if __name__ == "__main__":
    main()