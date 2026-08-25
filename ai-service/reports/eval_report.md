# Waste classifier — model evaluation report

Trained artifact for the real inference path (`AI_SERVICE_CLASSIFIER=real`, `RealInferenceClassifier`, ONNX).

## Dataset

- **Source:** TrashNet (Gary Thung & Mindy Yang, Stanford) — https://github.com/garythung/trashnet
- **License:** CC BY 4.0 (authors' repository); fetched from the official Hugging Face mirror (`garythung/trashnet`, `dataset-resized.zip`, sha256 `c060e8abfe5d6de0578ca15be1ed8ad0794a865d333c3473d53d1d9ad6e38b8c`).
- **Images:** 2,527 (512×384 RGB).

Class mapping: plastic→plastic, metal→metal, paper→paper, glass+cardboard+trash→other.

### Class distribution (after mapping)

| class | count |
|---|---|
| plastic | 482 |
| metal | 410 |
| paper | 594 |
| other | 1041 |

Train/val split: stratified, val_ratio=0.2 (seed 42).

| split | samples | per class |
|---|---|---|
| train | 2022 | paper=475, plastic=386, metal=328, other=833 |
| val | 505 | paper=119, metal=82, other=208, plastic=96 |

## Model

- **Architecture:** MobileNetV3-Small (ImageNet-pretrained) + 2-layer head (1.08M params) transfer-learned on ImageNet.
- **Task head:** Linear(576,256) -> ReLU -> Dropout(0.2) -> Linear(256,4)
- **Export:** ONNX opset 13, batch=1, softmax output node, CPU (onnxruntime).
- **Artifact size:** 4.32 MB.

## Training

- epochs_head: 8
- epochs_finetune: 4
- batch_size: 32
- lr_head: 0.001
- lr_finetune: 0.0001
- val_ratio: 0.2
- seed: 42
- device: mps

## Validation results (ONNX artifact, val set)

- **Accuracy:** 0.8772
- **Mean confidence:** 0.8620
- **Samples:** 505

| class | precision | recall | f1 | support |
|---|---|---|---|---|
| plastic | 0.862 | 0.844 | 0.853 | 96 |
| metal | 0.807 | 0.866 | 0.835 | 82 |
| paper | 0.925 | 0.933 | 0.929 | 119 |
| other | 0.887 | 0.865 | 0.876 | 208 |
| **macro avg** | | | **0.873** | |

```
Confusion matrix (val):
                plastic    metal    paper    other
plastic             81        4        3        8
metal                1       71        0       10
paper                1        2      111        5
other               11       11        6      180
```

Confusion matrix rendered in `confusion_matrix.png`.

## Inference latency (onnxruntime, CPU)

- mean **38.2 ms**, median **35.7 ms**, p95 **63.0 ms** (n=100, single 512×384 JPEG, M-series Mac).

## Limitations (read before claiming production-readiness)

- **Small, single-source dataset** (2,527 images, one camera setup). Real station-top captures will differ in lighting, angle and distance — expect distribution shift.
- **`other` is a heterogeneous dump** (glass + cardboard + trash): its precision/recall understates real-world open-set rejection.
- Confidence is the raw softmax probability, **not a calibrated** probability; the backend policy thresholds are the authority, not an ML guarantee.
- Background clutter (hands, bins, carriers) is not represented; the simulated scanner feed is idealised.
- The model was trained on a single stratified split, not cross-validated; numbers are on that held-out val set.
