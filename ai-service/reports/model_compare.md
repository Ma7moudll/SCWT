# Model comparison — pilot test split

**WARNING:** These results validate the training/validation pipeline under simulated camera distribution shift. They do **NOT** establish performance on the real EcoLoop station camera.

- Test: `data/station_capture_splits/test` (n=720, source=simulated-station-pilot).
- Candidate trained on `data/station_capture_splits/train` (6 epochs, lr=0.0001, seed 42).

| model | accuracy | macro-F1 | mean conf | size (MB) | latency ms (mean/med/p95) |
|---|---|---|---|---|---|
| MobileNetV3-Small (served) | 0.8986 | 0.8993 | 0.8656 | 4.32 | 18.2/17.7/22.9 |
| SqueezeNet1.1 (candidate) | 0.7681 | 0.7642 | 0.7617 | 2.92 | 23.1/20.2/44.7 |

## Per-class F1

| model | plastic | metal | paper | other |
|---|---|---|---|---|
| MobileNetV3-Small (served) | 0.899 | 0.904 | 0.938 | 0.856 |
| SqueezeNet1.1 (candidate) | 0.680 | 0.852 | 0.870 | 0.655 |

The served model is unchanged; a model swap is a separate explicit decision documented in this report.

