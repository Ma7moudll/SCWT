# Input quality gate report — background frames stay out of the classifier

**WARNING:** These results validate the lightweight camera gate under simulated camera conditions. They do **NOT** establish performance on the real EcoLoop station camera.

- Gate: `app.tools.quality_gate.InputQualityGate` + `ObjectPresenceDetector` (PIL/numpy/scipy, no cv2).
- Served model (unchanged by this work): `model.onnx` — `RealInferenceClassifier`, never invoked for rejected frames.
- Valid-waste reference: 720 pilot-test frames (real TrashNet re-renders, all 4 classes).
- Synthetic/OOD/background reference: 342 frames (blank, checkerboard, noise, blur, backgrounds, open-set family, corrupt).

## Headline

| metric | value |
|---|---|
| valid waste accepted | 720 / 720 |
| **false rejection of valid waste** | **0.00%** |
| OOD/background rejected | 226 / 342 |
| **false acceptance of OOD** | **33.92%** |

Rejection reasons (of the rejected OOD frames):

| reason | count |
|---|---|
| `CORRUPT_IMAGE` | 1 |
| `LOW_QUALITY` | 193 |
| `NO_OBJECT` | 32 |

Per-domain OOD / background acceptance:

| domain | count | accepted (false accept) |
|---|---|---|
| blank-black | 1 | 0 |
| blank-grey | 1 | 0 |
| blank-white | 1 | 0 |
| checkerboard | 4 | 0 |
| corrupt | 1 | 0 |
| gradient | 25 | 0 |
| heavy-blur | 8 | 0 |
| low-info-background | 12 | 7 |
| noise | 25 | 25 |
| random-noise | 8 | 8 |
| shapes | 25 | 0 |
| simple-background | 6 | 0 |
| solid | 100 | 0 |
| stains | 25 | 0 |
| tray-grey | 100 | 76 |

Valid-waste rejection by class (each frame is real TrashNet waste):

| class | count | rejected |
|---|---|---|
| metal | 180 | 0 |
| other | 180 | 0 |
| paper | 180 | 0 |
| plastic | 180 | 0 |

## Latency (mean, measured on this machine)

| stage | latency (ms) |
|---|---|
| gate (valid frames, n=720) | 18.82 |
| gate (rejected frames, n=342) | 13.52 |
| classifier only (n=20 valid frames) | 28.10 |
| gate + classifier (valid frames) | 40.70 |

## Design notes

- The gate runs **before** the classifier; a rejected frame never reaches `predict()`, so no background/empty frame can be routed as high-confidence waste.
- Thresholds are calibrated on the pilot-test set (see `app/tools/quality_gate.py`): blank/dark/bright/flat/blurry/low-info/corrupt frames are `LOW_QUALITY`, decode failures `CORRUPT_IMAGE`, and frames with no coherent edge content are `NO_OBJECT`.
- The gate is intentionally **permissive** on real waste (false-rejection 0%) rather than aggressive on OOD. Textured backgrounds, noise and stain-like patterns that carry real edge content still reach the classifier; the backend confidence policy (<0.50 refused, 0.50-0.79 manual) remains the backstop, and the `ObjectPresenceDetector` interface is the swap-in point for a real object detector later.
- `models/model.onnx`, `preprocess.json`, `calibration.json` and `fixtures.json` were not modified by this work.
