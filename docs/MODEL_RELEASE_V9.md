# Model release v9

Bundle: `8ccd676191a64dd18d215d4af8326e23`. Policy: `9`.
Cutoffs: BOT `0.96`, SUSPECT `0.45`. Scores are uncalibrated risk indicators,
not probabilities of bot ownership.

## What changed

- A non-finite or out-of-range LSTM chunk output now fails inference instead of
  silently becoming a neutral score.
- The BOT decision uses the mean chunk score. The upper-quartile score can only
  move a would-be HUMAN to SUSPECT; strong LSTM mean and upper-quartile evidence
  also abstains when the tabular model disagrees. The mean and upper quartile are
  each monotonic in their chunk inputs.
- Training samples 32 collector-like windows across each full real training
  trajectory, with timing variants. No held-out window is added to training.
- The release gate replays 1,000 windows per full validation/test session and
  requires zero human-to-BOT and zero bot-to-HUMAN windows. It also requires at
  most 10% human SUSPECT windows overall and 25% in any human session. All 17
  previously failing windows in six sessions are mandatory regressions.
- Buffered telemetry keeps its original model metadata, and the SQLite spool
  uses non-reused IDs so an old flush cannot acknowledge a newer event.

## Same-source evaluation

The corpus contains 449 labeled real sessions (109 human, 340 bot) and 300
synthetic training samples. Validation has 14 human and 46 bot sessions; test
has 24 human and 66 bot sessions. Phase 2 replay uses full trajectories,
including data beyond the 5,000-record training tail.

| 1,000 checkpoints per session | Validation | Test |
| --- | ---: | ---: |
| Human BOT windows | 0 / 14,000 | 0 / 24,000 |
| Bot HUMAN windows | 0 / 46,000 | 0 / 66,000 |
| Human SUSPECT windows | 413 / 14,000 (2.95%) | 1,255 / 24,000 (5.23%) |
| Most SUSPECT windows in one human session | 11.9% | 14.7% |
| Human sessions ever SUSPECT | 12 / 14 | 21 / 24 |

At the retained final-session snapshot, BOT precision is 1.0000 on both
splits, and BOT recall is 0.8043 on validation and 0.9091 on test. A bot
classified SUSPECT is not counted as BOT recall. The 150,000 replay windows
are correlated observations from only 150 sessions, not 150,000 independent
users.

The split and the known failing test windows have informed this policy and
training design. **The test split is no longer an unbiased final holdout.**
These results do not establish production false-positive/false-negative rates
or justify automatic user blocking. Start in monitoring mode, collect an
independently labeled browser/site/device cohort, and evaluate calibration,
traffic drift, and error rates before enforcing BOT decisions.

## Reproduce

```powershell
python -m core_ml.train --dataset-root "../Tuần 3/repos/web_bot_detection_dataset" --weights-dir bot-lab/reproduce-v9/weights --device cpu
python -m pytest -q
python -m ruff check .
```

The release gate checks sampled collector exports, not every possible event
boundary. The durable spool is local to one host; it is not a distributed
queue, and deployment still requires an actual database-outage recovery drill.
