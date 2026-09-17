# AI Validation

The classifier ships as a trained ONNX artifact (`ai-service/models/model.onnx`)
with frozen preprocessing (`preprocess.json`) and temperature calibration
(`calibration.json`). Serving uses `onnxruntime` only — training dependencies
live in `requirements-training.txt`.

## Pipeline (serving path)

1. **Quality gate** — rejects non-food/non-waste frames, blur, extreme
   aspect ratios before inference (`input_gate_report.md`).
2. **Preprocessing** — the exact resize/normalization the model was trained
   with (`preprocess.json`).
3. **ONNX inference** — four classes: `plastic`, `metal`, `paper`, `other`.
4. **Confidence policy** — temperature-calibrated probabilities
   (`calibration.json`); low-confidence inputs route to `other` instead of
   guessing.

## Reports

Generated evaluation reports live in `ai-service/reports/`:

| Report | What it shows |
|---|---|
| `dataset_report.md` | training/validation split composition |
| `eval_report.md` | accuracy / per-class metrics on the validation set |
| `confusion_matrix.png` | per-class confusions |
| `model_compare.md` | candidate backbone comparison |
| `finetune_report.md` | fine-tuning pass results |
| `calibration_report.md` | temperature-scaling calibration quality |
| `open_set_report.md` | behavior on unseen/out-of-distribution items |
| `input_gate_report.md` | camera quality gate acceptance/rejection rates |

**Honest scope:** these validate the training/validation pipeline under
simulated camera conditions; they do not by themselves establish performance
on the physical station camera. `fixtures.json` pins deterministic test
fixtures consumed by the test suite.

## Reproduce

```bash
cd ai-service
pip install -r requirements.txt -r requirements-training.txt
pytest                    # includes inference + tool tests
python -m app.tools.calibrate --help     # calibration tooling
```
