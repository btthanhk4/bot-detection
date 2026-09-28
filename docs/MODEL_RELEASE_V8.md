# Model release v8

Bundle: `8f08cb1719c848baab521e8e6f1c50f9`. Policy: `8`.
Decision cutoffs: BOT `0.96`, SUSPECT `0.425`. These are uncalibrated risk
scores, not probabilities of bot ownership.

## Changes

- The training pipeline replays 100 collector-like windows across each complete
  validation and test trajectory. Phase 2 replay uses the original records,
  including sections beyond the 5,000-record training tail. Missing sessions or
  incomplete checkpoint coverage fail the release gate.
- BiLSTM's p75 override now requires a weighted mean of at least `0.70`.
- The gate rejects any held-out human window labeled BOT or bot window labeled
  HUMAN. It still limits human sessions that ever enter SUSPECT to 80%.
- A MongoDB-outage event is acknowledged only after a local SQLite WAL spool
  commits it. Docker Compose mounts that spool on a named persistent volume.

## Same-source results

The training corpus contains 449 labeled real sessions (109 human, 340 bot),
plus 300 synthetic training samples. The held-out validation split has 14
human and 46 bot sessions; test has 24 human and 66 bot sessions.

| Full-trajectory replay, 100 checkpoints/session | Validation | Test |
| --- | ---: | ---: |
| Human sessions ever BOT | 0/14 | 0/24 |
| Human BOT windows | 0/1,400 | 0/2,400 |
| Bot sessions ever HUMAN | 0/46 | 0/66 |
| Bot HUMAN windows | 0/4,600 | 0/6,600 |
| Human sessions ever SUSPECT | 8/14 | 17/24 |

At the final retained session snapshot, BOT precision is `1.0000` and BOT
recall is `0.8913` on validation, `0.9545` on test. Five validation bots and
three test bots remain SUSPECT rather than BOT; there are no observed human BOT
decisions in those snapshots. These windows are correlated and must not be
treated as thousands of independent subjects.

The SUSPECT cutoff was changed after inspecting the same test split: two bot
windows with risks `0.4495` and `0.4345` were HUMAN under cutoff `0.45`; the
new `0.425` cutoff makes them SUSPECT. The human sessions ever SUSPECT count
did not rise on validation or test. Because test observations informed this
choice, **the test split is no longer an unbiased final holdout**. A fresh,
independently labeled browser/site/device cohort is required before claiming
a real-world false-positive or false-negative rate. Do not automatically block
users solely from these same-source results.

## Reproduce

```powershell
python -m core_ml.train --dataset-root "../Tuần 3/repos/web_bot_detection_dataset" --weights-dir bot-lab/policy8-final/weights --device cpu
python -m core_ml.evaluate_robustness --dataset-root "../Tuần 3/repos/web_bot_detection_dataset" --weights-dir core_ml/weights --split val --desktop-fingerprint
python -m core_ml.evaluate_robustness --dataset-root "../Tuần 3/repos/web_bot_detection_dataset" --weights-dir core_ml/weights --split test --desktop-fingerprint
```

The replay samples 100 checkpoints; it does not prove that every possible
intermediate export is error-free. The local spool is durable across a process
restart on the same host, not a distributed queue or a substitute for a
MongoDB-outage drill with an actual container kill and disk-capacity alerting.
