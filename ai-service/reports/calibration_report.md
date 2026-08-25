# Confidence calibration report

**WARNING:** These results validate the training/validation pipeline under simulated camera distribution shift. They do **NOT** establish performance on the real EcoLoop station camera.

- Model: `models/model.onnx`
- Fitted on: `data/station_capture_splits/val` (source=simulated-station-pilot, n=720)
- Temperature (fitted on val NLL): **T=0.7902**

| metric | before (raw) | after (T-scaled) |
|---|---|---|
| ECE (15 bins) | 0.0473 | 0.0252 |
| Brier | 0.1642 | 0.1648 |
| NLL | 0.2962 | 0.2862 |
| Accuracy | 0.8833 | 0.8833 |
| Mean confidence | 0.8597 | 0.8934 |

Backend policy thresholds (`>=0.80` HIGH / `0.50-0.79` MEDIUM / `<0.50` LOW) are unchanged — calibration only post-conditions reported confidence.

