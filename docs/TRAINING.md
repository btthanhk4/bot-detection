# Model Training

The production Docker image intentionally uses CPU-only PyTorch. Google Colab
already provides a CUDA-enabled PyTorch build, so use the separate Colab
requirements file there.

## Local CPU

```bash
python -m pip install -r requirements-dev.txt
python -m core_ml.train --dataset-root /path/to/web_bot_detection_dataset --device cpu
```

Training fails before writing artifacts when no real labeled sessions are
loaded or the real data does not contain both human and bot labels.
`--allow-synthetic-only` exists only for diagnostics and its output must not
be deployed.

Synthetic-only diagnostics must use a separate artifact directory so they
cannot overwrite the production bundle:

```bash
python -m core_ml.train --allow-synthetic-only --weights-dir /tmp/bot-diagnostic-model
```

## Browser-run bot captures

The external `all-mouse-bots.js` runner can write each browser run to a local
directory with `MOUSE_CAPTURE_DIR`. A file contains the collector requests
actually sent, a separate final probe, and a BOT label supplied by the runner.
Keep this directory private:
it may contain browser fingerprints and page URLs. A run is one sample;
repeated heartbeats from that run are correlated windows, not independent
sessions. A basic no-mouse run is useful for evaluating BotD but contributes
no mouse training windows. Recent captures also include the User-Agent observed
on each HTTP request; offline replay uses that transport value for the
headless-browser rule. Older captures without it cannot validate that rule.

From the separate `bot-detection-test` directory on Windows PowerShell:

```powershell
$env:MOUSE_CAPTURE_DIR = 'C:\Users\Admin\bot-detection-test\captures'
$env:RUNS_PER_SCENARIO = '5'
node all-mouse-bots.js
```

Inspect the current bundle before training:

```powershell
python -m core_ml.evaluate_field_captures --capture-dir 'C:\Users\Admin\bot-detection-test\captures'
```

Train an isolated candidate, holding out at least one whole generator family:

```powershell
python -m core_ml.train --dataset-root 'C:\path\to\web_bot_detection_dataset' --capture-dir 'C:\Users\Admin\bot-detection-test\captures' --capture-holdout-family mouse-scrub-hover --tabular-only --diagnostic-only --weights-dir 'bot-lab\field-candidate\weights' --device cpu
```

The candidate manifest is marked `diagnostic_only`, so the serving release
check rejects it. Compare its held-out family report with the frozen bundle,
the existing human replay, and independently collected human sessions before
considering a production retrain. Several seeds of one generator do not
constitute an unseen bot family. Human sessions from the actual site should
include ordinary mouse use, touchpad, scrolling, hovering, and drag selection.
During this diagnostic run, each captured training window gets four times the
tabular sample weight of a legacy training window; the value is recorded in
the manifest and must be evaluated against human false positives.
Omit `--tabular-only` to retrain BiLSTM too. In that diagnostic mode, BiLSTM
chunk weights are normalized by the number of chunks per session, with a
fourfold weight for each captured bot session. This prevents a long browser
run from counting as many independent users.

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
