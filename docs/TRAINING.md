# Model Training

The production Docker image intentionally uses CPU-only PyTorch. Google Colab
already provides a CUDA-enabled PyTorch build, so use the separate Colab
requirements file there.

## Local CPU

```bash
python -m pip install -r requirements-dev.txt
python -m core_ml.train --dataset-root /path/to/web_bot_detection_dataset --device cpu
```

## Google Colab GPU

Select a GPU runtime first, then run:

```python
!git clone https://github.com/btthanhk4/bot-detection.git
%cd bot-detection
!python -m pip install -r requirements-colab.txt

import torch
assert torch.cuda.is_available(), "Select a GPU runtime before training"
print(torch.cuda.get_device_name(0))
```

Mount Drive and start training:

```python
from google.colab import drive
drive.mount("/content/drive")

!python -m core_ml.train \
  --dataset-root "/content/drive/MyDrive/web_bot_detection_dataset" \
  --device cuda
```

Training publishes these files only after both models finish and evaluation
succeeds:

```text
core_ml/weights/tabular_model.joblib
core_ml/weights/behavioral_lstm.pt
core_ml/weights/model_manifest.json
```

The manifest records artifact hashes, feature schema, dataset fingerprint,
split membership, metrics, random seed, and training device. The API refuses
to load a missing, modified, or incompatible bundle.

## Frozen Evaluation

Evaluate without fitting the model again:

```bash
python -m core_ml.evaluate \
  --dataset-root /path/to/independent_dataset \
  --split all \
  --threshold 0.70 \
  --output evaluation.json
```

The evaluator rejects trajectories found in the model's training split unless
`--allow-training-overlap` is explicitly supplied for a diagnostic run.
