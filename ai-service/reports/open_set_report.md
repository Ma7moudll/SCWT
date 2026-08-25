# Open-set report — synthetic OOD false-acceptance

**WARNING:** These results validate the training/validation pipeline under simulated camera distribution shift. They do **NOT** establish performance on the real EcoLoop station camera.

- Served model: `models/model.onnx`
- OOD samples: 300 synthetic non-waste frames (tray-grey, noise, gradient, shapes, stains, solid).

| threshold | meaning | false-accept rate |
|---|---|---|
| >= 0.80 | HIGH (auto deposit route) | **21.3%** |
| >= 0.50 | MEDIUM+ (human review route) | **70.0%** |

Per-domain breakdown (max confidence >= 0.50):

| domain | count | >=0.50 |
|---|---|---|
| gradient | 25 | 6 |
| noise | 25 | 25 |
| shapes | 25 | 22 |
| solid | 100 | 52 |
| stains | 25 | 24 |
| tray-grey | 100 | 81 |

  NOTE: worst offender 'stains' scored 0.98. The model was trained only on waste images — background-only frames are out of training distribution and should be handled by the camera motion/detection stage, not the classifier (see docs/ai-validation.md).

