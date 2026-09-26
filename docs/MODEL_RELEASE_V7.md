# Model release v7

Bundle: `f30c17d04e984569aa409a87355ca7ac`. Policy: `7`.
Decision thresholds: BOT `0.93`, SUSPECT `0.45`. Scores are not calibrated probabilities.

## What changed

- Train-only collector-like rolling windows and timestamp factors `0.5`, `1.0`, `2.0`
  augment both XGBoost and BiLSTM. Validation/test sessions are not augmented.
- XGBoost trains on the 20 labeled mouse-statistic columns. Its 30 environment
  columns remain in the serving schema but are constant during fitting. The
  real labeled mouse sessions have no browser fingerprints, so synthetic-only
  environment fields previously caused severe domain shift. BotD still
  contributes positive browser-automation evidence in the ensemble.
- The decision evidence gate counts distinct positions after the same
  coordinate normalization as feature extraction, and requires at least five
  distinct timestamps. Degenerate trajectories stay SUSPECT.
- The release gate checks intermediate windows for each held-out session, not
  only the first 25/50/100 and final window. The manifest records this evidence.

## Same-source replay

The real dataset has 449 sessions: 109 human and 340 bot. The frozen split has
60 validation sessions (14 human, 46 bot) and 90 test sessions (24 human, 66 bot).
For each session, 25 checkpoints from the 25th move through the retained
trajectory approximate the collector's bounded 100-event export. Windows from
one session are correlated; the denominators below are sessions unless noted.

| Measure | v6 validation | v7 validation | v6 test | v7 test |
| --- | ---: | ---: | ---: | ---: |
| Human sessions ever BOT | 3/14 | 0/14 | 2/24 | 0/24 |
| Human BOT windows | 9/350 | 0/350 | 4/600 | 0/600 |
| Bot BOT windows | 1039/1150 | 1101/1150 | 1495/1650 | 1580/1650 |
| Bot sessions ever HUMAN | 0/46 | 0/46 | 1/66 | 1/66 |
| Bot classified HUMAN after first 100 moves at 0.5x time | 14/46 | 2/46 | 11/66 | 0/66 |

The v7 validation replay is identical for an empty fingerprint and a plausible
desktop fingerprint. The first candidate, which trained XGBoost on synthetic
environment fields, classified **zero** of 46 validation bots as BOT with that
desktop fingerprint; it was rejected and never released.

The unchanged threshold gives v7 full-session ensemble test AUC `1.0000`, F1
`0.9846`, and FPR `0.0000` on this same-source split. At the first 25 moves,
validation has 0/14 human BOT decisions and 45/46 bot BOT decisions. The
release gate also requires zero human sessions ever BOT across sampled windows,
limits HUMAN-to-SUSPECT and BOT-to-HUMAN session friction, and binds the
fingerprint-training and collector-window contract.

Reproduce the frozen-bundle replay from the repository root:

```powershell
python -m core_ml.evaluate_robustness --dataset-root "../Tuần 3/repos/web_bot_detection_dataset" --weights-dir core_ml/weights --split val
python -m core_ml.evaluate_robustness --dataset-root "../Tuần 3/repos/web_bot_detection_dataset" --weights-dir core_ml/weights --split test
python -m core_ml.evaluate_robustness --dataset-root "../Tuần 3/repos/web_bot_detection_dataset" --weights-dir core_ml/weights --split val --desktop-fingerprint
```

## Release boundary

This is a better candidate for **monitoring and human review**, not proof of a
production false-positive rate. The held-out split is from the same research
dataset and was inspected during development; it is no longer a blind external
test. No independently labeled live browser traffic, deployment-specific
fingerprints, touch labels, or score calibration are available. Do not auto-block
users solely from a BOT verdict. Before enforcement, collect consented real
sessions, label disputed decisions, evaluate by site/device/time cohort, and
set a rollback criterion from observed false positives.
