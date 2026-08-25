# Fine-tuning report — baseline vs fine-tuned (pilot test)

**WARNING:** These results validate the training/validation pipeline under simulated camera distribution shift. They do **NOT** establish performance on the real EcoLoop station camera.

- Baseline: served `models/model.onnx` (TrashNet-trained, untouched).
- Candidate: fine-tuned on `data/station_capture_splits/train` (source=simulated-station-pilot, seed 42, eager head + last-block, 6 epochs, lr=0.0001).
- Test: `data/station_capture_splits/test` (n=720).

| model | accuracy | macro-F1 | conf mean | size | latency ms (mean/med/p95) |
|---|---|---|---|---|---|
| baseline | 0.8986 | 0.8993 | 0.8656 | 4.32 MB | 18.0/17.8/21.9 |
| fine-tuned | 0.8806 | 0.8798 | 0.8956 | 4.32 MB | 17.6/17.4/21.0 |

## Fine-tuned per-class (pilot test)

| class | precision | recall | f1 | support |
|---|---|---|---|---|
| plastic | 0.935 | 0.800 | 0.862 | 180 |
| metal | 0.888 | 0.928 | 0.908 | 180 |
| paper | 0.877 | 0.950 | 0.912 | 180 |
| other | 0.831 | 0.844 | 0.837 | 180 |

## Decision

The served `models/model.onnx` is **retained** for now: swapping it live is a separate, explicit decision that needs a clear, justified improvement plus re-validation of the E2E chain.

