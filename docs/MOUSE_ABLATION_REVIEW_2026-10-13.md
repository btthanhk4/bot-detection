# Mouse Model Ablation Review

## Outcome

The first training experiment with the new local-motion measurements did not
improve unseen-generator detection. Do not promote these candidate weights.
Production BiLSTM, XGBoost, ensemble policy, collector and API are unchanged.
The implementation adds a reproducible offline experiment, not a new bot rule.

## Source Code Reviewed

All three repositories were already cloned outside the product tree under
`C:/Users/Admin/bot-detection-research`; their remotes, clean worktrees and
pinned commits were verified again. No third-party installation or upstream
training script was executed. The Python experiment is independently written.

| Repository / pinned revision | Source examined | Idea retained |
| --- | --- | --- |
| [DELBOT-Mouse](https://github.com/chrisgdt/DELBOT-Mouse/tree/712a00ea994738b680b0b11bb4b518979385d07b) | `delbot-core/src/data.ts`, `delbot-training/src/dataTraining.ts`, `models.ts` | Motion feature representations and controlled model comparisons |
| [bot-signal](https://github.com/okasi/bot-signal/tree/de9b554ecb5fd6f6af49cec5c5027abd24f41d1f) | `src/behavioral/analysis.ts` | Short sliding movement windows; test continuous descriptors instead of importing heuristic thresholds |
| [BeCAPTCHA-Mouse](https://github.com/BiDAlab/BeCAPTCHA-Mouse/tree/daaad5adc9235fdc3cf17ebf50c709eea790d10d) | `README.md`, benchmark description | Evaluate across generator families and timing variants, not just random windows |

DELBOT's `DataFeatures` has 8 motion features and `DataFeatures2` adds angle
and jerk. The current project already includes related statistical features;
blindly adding duplicate derivatives is not automatically an improvement.
Its training example concatenates chunks and shuffles their indices to split
train/test, which can put related chunks in both sets. That split procedure
was not adopted. Its README discusses GAN training, but no GAN was run here.

DELBOT and bot-signal include MIT license files in these clones. BeCAPTCHA's
clone contains documentation/images, not a ready-to-run classifier or the
licensed benchmark. Its access instructions require an institutional request.
No restricted dataset or weights were downloaded. None of the three is a
drop-in replacement proven to outperform the current model on this website.

## Predeclared Experiment

Entry point: `core_ml/experiments/mouse_ablation.py`.

1. Use Phase 2 mouse sessions with the existing timestamp/coordinate parser.
   Phase 1 is excluded because its timestamps are estimated. The Phase 2
   parser can also fall back for missing timestamps; this experiment does not
   introduce a provenance flag or certify that every parsed timestamp is real.
2. Deduplicate sessions and assign fixed train/validation/test partitions with
   the existing splitter before materializing windows over full trajectories.
3. Sample up to 32 collector-sized windows per dataset session. These are
   diagnostic checkpoints, not the 1,000-checkpoint release replay.
4. Load 18 runner-labeled browser bot captures. Use deduplicated eligible sent
   windows; exclude final probes, touch, fewer than 25 moves and degenerate
   spatial/temporal evidence. Do not label data using model predictions.
5. Leave out one complete generator family at a time: circular, heavy-wander,
   scrub-hover. Fixed/jitter variants remain in the same family. Six field
   runs are tested per fold, with the other twelve available for training.
6. Reject repeated session IDs and exact-window leakage across partitions,
   including trajectories duplicated with a shifted clock origin. Reject
   conflicting labels. Balance class mass and session mass within each class,
   so a longer session cannot dominate merely by contributing more windows.
7. Fit three XGBoost configurations per fold with the same fixed parameters:
   120 trees, depth 4, learning rate 0.05, seed 42, one CPU thread. No tuning,
   early stopping or threshold selection on the test set. Keep thresholds
   0.45/0.96 for all reported standalone classifiers; scores are uncalibrated.

The arms are:

- `frozen_tabular`: current XGBoost artifact, original 20 mouse features and
  zero environment columns. Reference only, not a fresh retraining arm.
- `refit_existing`: 20 mouse features, Phase 2 training sessions only.
- `refit_with_field`: same features plus training-family browser captures.
- `refit_with_field_local`: same data plus 5 local speed/straightness/turn
  features from `interaction_window_v2`. Missing descriptors remain NaN for
  native XGBoost missing-value handling, not invented zero measurements.

The refitted arms isolate data and feature additions under the same training
setup. Comparing any refit directly with the frozen artifact also changes
training history/hyperparameters; that is not a pure feature ablation.
No browser profile, HTTP metadata, filename, generator name or source label
is included in model inputs. No BiLSTM, profile rule or fusion result is used
to override the reported XGBoost verdicts.

## Dataset and Results

Phase 2: 299 sessions (59 HUMAN, 240 BOT). Fixed partitions:

| Partition | HUMAN | BOT | Dataset windows |
| --- | ---: | ---: | ---: |
| Train | 41 | 168 | 6,688 |
| Validation | 9 | 36 | 1,440 |
| Test | 9 | 36 | 1,440 |

Each fold adds twelve training-family bot runs. The three folds reuse the
same dataset partitions. There are nine test human sessions, not 27 distinct
humans. Participant identities are not available to enforce subject-level
splits; no same-site human browser captures are present. These restrictions
prevent a production false-positive claim.

Final outcomes on six held-out field runs per family, shown as BOT/HUMAN/SUSPECT:

| Held-out family | Frozen XGBoost | Refit existing | Refit + field | Refit + field + local |
| --- | --- | --- | --- | --- |
| Circular | 3 / 0 / 3 | 0 / 6 / 0 | 0 / 6 / 0 | 0 / 6 / 0 |
| Heavy-wander | 0 / 6 / 0 | 0 / 6 / 0 | 0 / 6 / 0 | 0 / 6 / 0 |
| Scrub-hover | 2 / 2 / 2 | 0 / 0 / 6 | 0 / 0 / 6 | 0 / 6 / 0 |

The 25-feature candidate therefore has 18/18 final HUMAN false negatives on
the held-out field runs in this experiment. Adding features did not fix the
blind spot. Even where a final dataset BOT classification looks correct,
intermediate windows can still be HUMAN: the 25-feature arm had 1, 1 and 2
such dataset bot sessions in the three test folds. Reports retain these
transient errors instead of reporting final accuracy alone.

No sampled HUMAN validation/test window was classified BOT in these runs;
this small, reused dataset is not evidence of zero production false positives.
The field data and generator families have been inspected in prior work, so
this is a development leave-family-out diagnostic, not a blind external test.

Results belong to the standalone XGBoost component. They must not be compared
as though they were ensemble verdicts from previous profile experiments.

## Reproduction and Verification

Local runtime: Python 3.10.9, NumPy 1.26.4, XGBoost 3.2.0.
Frozen bundle: `e3dd550e4d40453db0e17a743da7e992`.

```powershell
python -u -m core_ml.experiments.mouse_ablation `
  --dataset-root '../Tuần 3/repos/web_bot_detection_dataset' `
  --capture-dir C:/Users/Admin/bot-detection-test/captures-interactions-2026-10-02 `
  --artifact-dir C:/Users/Admin/bot-detection-research/mouse-ablation-new-run `
  --output docs/MOUSE_ABLATION_RESULTS_new_run.json
```

The artifact directory must be new and outside the product repository.
Nine UBJ models and an experiment manifest were saved locally under
`C:/Users/Admin/bot-detection-research/mouse-ablation-2026-10-13-v1`.
The [aggregate report](MOUSE_ABLATION_RESULTS_2026-10-13.json) records split
manifest hashes, artifact hashes, feature names, parameters, window coverage,
final/ever verdicts and feature importances. Raw identities are not exported.

27 new tests cover grouping, missing values, class/session weights, overlap,
clock-shifted duplicates, label conflicts, invalid predictions, missing
coverage, artifact location protection and model save/load replay equivalence.
The normal runtime does not import this experimental module.

Final verification: `python -m pytest -q` passed 444 tests with one existing
Starlette TestClient deprecation warning; Ruff passed. Passing software tests
does not overturn the negative model evaluation above.

## Decision and Next Steps

Retain the current production weights. Keep this experiment and its negative
result: they prevent an unjustified model replacement. Do not lower thresholds
or try successive candidates against these same test folds until one passes.

Next, collect same-site human controls and more independent bot generators,
audit collection/timestamp/coverage differences, and reserve fresh held-out
families. Then compare a motion-only baseline and feature additions again.
BiLSTM retraining or neuromotor decomposition should follow a validated data
protocol rather than be assumed to fix this result. This iteration neither
retrains BiLSTM nor implements the BeCAPTCHA neuromotor extractor.
