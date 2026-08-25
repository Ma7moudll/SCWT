# Trained waste-classification model artifact (production inference path)

`AI_SERVICE_CLASSIFIER=real` loads `model.onnx` (+ `preprocess.json`) through
`RealInferenceClassifier`. These files are produced by the training pipeline:

    cd ai-service
    pip install -r requirements-training.txt
    python -m app.training.train --data-dir data/raw          # full re-train
    python -m app.training.train --eval-only                  # re-eval existing artifact

## Artifacts

| file | description |
|---|---|
| `model.onnx` | MobileNetV3-Small, ImageNet-pretrained, 4-class softmax head, opset 13, batch=1 (4.3 MB) |
| `preprocess.json` | input geometry (resize 256, center-crop 224), mean/std, class order — read at load time |
| `fixtures.json` | curated HIGH/MEDIUM/LOW confidence fixture provenance |
| `calibration.json` | temperature-scaling factor + before/after ECE/Brier (written by `app.tools.calibrate`; **not** applied to the served predictions) |

Trained on **TrashNet** (CC BY 4.0, garythung/trashnet): plastic/metal/paper +
glass+cardboard+trash→other. See `../reports/eval_report.md` for the
evaluation, confusion matrix, and limitations. The data-collection / model
validation pipeline is documented in `../../docs/ai-validation.md`.

## Raw data / checkpoints (gitignored)

The 42.8 MB `dataset-resized.zip` and the `.pt` checkpoint live under the
gitignored `../data/` — the dataset is intentionally **not** committed.