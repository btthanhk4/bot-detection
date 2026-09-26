# Policy v6 release review

Date: 2026-09-26. Source commit: `fab75e50374b6328f57722cb88ebd10ad1671b5f`.
Frozen model bundle: `2151c04e5a304021a0e86f037d84a848`.

## Release recommendation

Do not enable automatic blocking from the current model's BOT verdict yet.
The endpoint reports and passing unit tests do not cover errors during the
middle of a session. New validation replay exposes human-to-BOT errors and
timing sensitivity. Address the ingestion failure below before expanding a
monitoring-only deployment.

This review covers collector source and bundling, feature extraction, both ML
models, fusion, dataset loading, training, evaluation, experiments, simulator,
API ingestion/storage/query flows, dashboard JavaScript, container configuration,
and CI/deployment. Existing tests were inspected and executed. Security/HTTPS
and capacity benchmarking are outside this review's scope. Ten actionable
findings are listed below; this is not a claim that every possible defect has
been enumerated.

No model fitting, application-code changes, push, or deployment was performed
as part of this review. Diagnostic scripts/results are in the gitignored
`bot-lab/` directory.

## Fresh verification

- Python suite: 205 passed, one dependency deprecation warning.
- Collector lifecycle tests: passed.
- Ruff: passed.
- Loaded and verified the current frozen bundle.
- Read-only validation replay: 60 sessions, 14 human and 46 bot, 25 checkpoints
  per session, 1,500 windows per fingerprint scenario.
- Checked malformed telemetry with FastAPI TestClient and a patched database
  connection, release-evidence edge cases, normalized trajectory degeneracy,
  and cross-origin response headers.

The dataset contains 150 Phase 1 sessions with estimated event timing and 299
Phase 2 sessions parsed from browser timestamps. Validation contains 5 Phase 1
and 9 Phase 2 humans, and 10 Phase 1 and 36 Phase 2 bots.

## Diagnostic results

For each validation session, choose 25 evenly spaced move checkpoints after
the 25th move. Apply the collector's bounded record-buffer length and exported
move/other-event selection to the dataset events, then run the frozen detector.
This approximates record-window selection; it is not a live browser replay,
does not recreate down/up events missing from the dataset, and does not
reproduce the 15-second network heartbeat cadence. For Phase 2, the loader
retains only the last 5,000 records plus a separate true-start prefix, so the
rolling replay covers the retained segment, not every original event.

| Known label | Windows | HUMAN | SUSPECT | BOT |
| --- | ---: | ---: | ---: | ---: |
| Human | 350 | 296 | 45 | 9 |
| Bot | 1,150 | 0 | 111 | 1,039 |

Three of fourteen human sessions have at least one BOT window. Two are Phase 2
sessions, so the result is not confined to reconstructed Phase 1 timestamps.
A fixed plausible desktop fingerprint gives exactly the same human counts;
bot counts become 0 HUMAN, 120 SUSPECT, 1,030 BOT. Using the server's simple last
100-event window without the collector event selection still yields 8 BOT
windows among the 350 human windows. Forty-nine of sixty sessions change
verdict across the sampled checkpoints; changes include legitimate evidence
updates, so the transition count alone is not an error count.

Affected human sessions:

| Session | Source | BOT checkpoints | Last-window verdict |
| --- | --- | ---: | --- |
| `ufaj0lbcmqa0l022l9jan5n87l` | Phase 1 | 1/25 | HUMAN |
| `8is1s1cv7tu0c13vcqka04ck8m` | Phase 2 | 7/25 | SUSPECT |
| `viq1vmgres2bhnholc4p3a76lh` | Phase 2 | 1/25 | HUMAN |

Timing sensitivity on the true first 100 moves, with coordinates unchanged:

| Timestamp multiplier | Human: H/S/B | Bot: H/S/B |
| --- | --- | --- |
| 0.25 | 14 / 0 / 0 | 25 / 17 / 4 |
| 0.5 | 14 / 0 / 0 | 14 / 24 / 8 |
| 1.0 | 13 / 1 / 0 | 0 / 4 / 42 |
| 2.0 | 9 / 5 / 0 | 0 / 16 / 30 |
| 4.0 | 13 / 1 / 0 | 0 / 32 / 14 |

All 14 bot-to-HUMAN outcomes at multiplier 0.5 are Phase 2 samples. These are
controlled transformations of labeled validation trajectories, not observed
production error rates or independent evidence. Windows from one session are
correlated and must not be counted as independent users for confidence bounds.

Local evidence: `bot-lab/release_review_v6.py` and
`bot-lab/release_review_v6_extended.json`. Reproduce from the repository root:

```powershell
python -c "import runpy; runpy.run_path('bot-lab/release_review_v6.py', run_name='__main__')"
```

## Findings and fixes

### F01 - P1: Per-window decisions miss human false positives inside sessions

Locations: `core_ml/train.py:480`, `core_ml/features/mouse_features.py:18`,
`core_ml/models/ensemble.py:199`, `api_service/database.py:350`.

Release evaluation tests the first 25/50/100 moves and the final retained
window. "Full session" evaluation still reaches a feature extractor capped at
100 records. Each heartbeat replaces the session's current decision, without
decision history or a validated temporal policy. A benign final window cannot
undo a block already applied to an earlier false-positive window. The replay
above demonstrates this gap using the actual released weights.

Fix: add reproducible replay across session windows to the release evaluator.
Report the proportion of human sessions ever called BOT, bot sessions ever
called HUMAN, verdict transitions, and time to a supported decision. Train on
representative middle windows from TRAIN sessions only, with per-session
weighting so long sessions do not dominate. Compare a temporal policy using
fresh, nonduplicated evidence with the current instantaneous policy. Do not
permanently latch BOT after one spike or count repeated idle heartbeats as new
independent evidence. Store current-window and session decision metadata
separately if that policy is adopted.

### F02 - P1: Decision quality is sensitive to movement timing

Locations: `core_ml/features/mouse_features.py:166`,
`core_ml/dataset/loader.py:69`, `core_ml/train.py:704`.

Halving event timestamps changes the first-100-move bot verdict distribution
from 0 HUMAN / 4 SUSPECT / 42 BOT to 14 HUMAN / 24 SUSPECT / 8 BOT. The XGBoost
artifact assigns about 52.85% of its reported feature importance to
`std_speed`. Importance is supporting context, not proof of the cause.

Fix: add a validation stress matrix for plausible timing scales, event
coalescing/downsampling, pauses, viewport changes, and real browser input
devices. Compare Phase-2-only training against mixed-source training; retain
timing provenance and avoid treating estimated timestamps as measured timing.
Evaluate bounded timing augmentation and relative motion features using only
training data for fitting. Select using validation, freeze the candidate, and
evaluate a separately reserved test set. More epochs alone does not address
this distribution sensitivity.

### F03 - P1: Malformed mouse records can poison the persistence replay queue

Locations: `api_service/main.py:360`, `api_service/database.py:294`,
`api_service/main.py:300`.

`mouse` accepts an arbitrary dictionary, so `{"mouse":{"records":7}}` passes
payload validation. Inference treats it as empty input, but persistence then
iterates the integer and raises. The API returns HTTP 200, `recorded:true`,
`buffered:true`. Two replay attempts leave the same bad event queued. The
generic persistence exception path requeues it at the front and breaks,
preventing later buffered events from progressing through that flush.
An additional queue probe placed `valid-after-bad` after `bad-head`: only
`bad-head` reached the save call, and both events remained queued afterwards.

Fix: validate nested record types at the API boundary and apply the same
canonical input rules during inference and persistence. Distinguish invalid
events from transient database failures; quarantine or explicitly reject
unrecoverable events with observable counters. Add a regression where a bad
event is followed by a valid event and verify that the valid event progresses.

### F04 - P1: Release metrics do not assess all three product verdicts

Locations: `core_ml/train.py:507`, `core_ml/evaluate.py:34`.

Binary `is_bot` metrics combine HUMAN and SUSPECT. A controlled detector that
returns SUSPECT for all 14 humans and BOT for all 46 bots passes every release
gate with AUC/F1/precision/recall/accuracy of 1.0. Its HUMAN recognition rate is
zero. `decision_coverage` also remains 1.0 when these SUSPECT decisions have
`decision_state=FINAL`.

Fix: keep binary metrics, but add the full true-label by three-verdict table,
human-to-SUSPECT friction, bot-to-HUMAN escape rate, supported-input coverage,
and explicit insufficient-evidence counts. Set acceptance limits per supported
cohort and use session-level denominators for operational metrics.

### F05 - P2: Release evidence is not bound to the complete runtime contract

Locations: `core_ml/model_bundle.py:15`, `api_service/main.py:144`,
`api_service/config.py:70`, `core_ml/train.py:907`.

The evidence check binds policy version and two thresholds but not the
minimum-point setting, preprocessing version, input-window policy, or full
fusion configuration. Changing the supported minimum from 25 to 100 still
accepts the old evidence. Metric checks also accept impossible values such as
AUC/precision/recall=2 and FPR=-1. Zero decision coverage is not inspected.
The current manifest's normal values are not alleged to be corrupt; the
validator fails to detect these constructed invalid cases.

Fix: persist and compare a complete inference contract, metric domains,
sample counts, per-class support, confusion counts, evidence provenance, and
required cohort coverage. Reject mismatches before serving. Verify the exact
candidate code/bundle combination, not merely the presence of passing numbers.

### F06 - P2: Evidence sufficiency is checked before canonical coordinates

Locations: `core_ml/models/ensemble.py:91`,
`core_ml/features/mouse_features.py:151`,
`core_ml/features/mouse_features.py:347`.

Thirty distinct negative coordinates pass the distinct-position check. Feature
normalization then clips all of them to the same position. The frozen model
still reports `usable_trajectory:true`, `decision_state:FINAL` (SUSPECT,
score 0.5021 in the probe). A trajectory with 29 events at timestamp zero and
one at 1 ms is also accepted as usable and produces BOT at 0.9689. Merely having
positive total duration does not establish adequate valid transitions.

Fix: make the sufficiency gate consume the same normalized coordinates and
time transitions as both models. Define duplicate timestamp handling, minimum
usable transitions, and how invalid coordinate domains are rejected. Keep
quality failures SUSPECT with a reason, then rerun release evaluation because
the preprocessing/evidence contract changes.

### F07 - P2: Training and browser feature contracts still differ

Locations: `collector/src/mouse.js:266`, `collector/src/botd.js:143`,
`core_ml/dataset/loader.py:746`, `core_ml/train.py:621`.

The SDK preserves move events plus at most 20 other events; the Python feature
path simply retains the last 100 valid events from dataset input. Event-heavy
training windows therefore need not match collector windows. Synthetic BotD
scores use flagged_count/10, while the browser uses detector weights and 13
detectors. Synthetic human UA/platform/languages are sampled independently
while all inconsistency flags stay false. Real labeled trajectories provide
empty fingerprint fields, so ordinary validation does not validate the
fingerprint model on matched real browser environments.

Fix: define one versioned event-selection contract and fixture-based parity
checks. Generate synthetic environment flags and scores through the same
detector rules as the SDK, preserve missing-feature indicators, and compare a
mouse-only XGBoost candidate with the combined candidate. Treat synthetic
environment variation as augmentation; verify it with labeled browser data
before relying on it to reject users.

### F08 - P2: The E8 short-session experiment still uses the retained tail

Locations: `core_ml/experiments/run_all.py:764`,
`core_ml/experiments/run_all.py:632`, `core_ml/dataset/loader.py:391`.

E5 receives `early_records`, but E8 still receives `all_records` and truncates
its beginning. For a Phase 2 session longer than 5,000 events, this is the
beginning of a tail segment, not the beginning of the visit. E8 also drops all
non-move events and trains a separate XGBoost model, so its results must not be
presented as the deployed ensemble's early-session accuracy.

Fix: pass true prefixes to E8, preserve the intended event-selection contract,
label separate-model experiments explicitly, and add a long-session regression.

### F09 - P2: Cross-origin collectors cannot read Retry-After

Locations: `api_service/main.py:116`, `collector/src/index.js:244`.

A local cross-origin rate-limit probe returns HTTP 429 with `Retry-After:60`
and an allowed origin but no `Access-Control-Expose-Headers`. Browser fetch
therefore cannot expose Retry-After to the SDK; its intended server-directed
cooldown works for same-origin requests but not an otherwise allowed external
website integration.

Fix: expose Retry-After in CORS responses and add a real cross-origin browser
test for 429/503 cooldown and recovery. Preserve latest telemetry during the
cooldown without unbounded buffering.

### F10 - P2: Dashboard explanations do not consistently describe evidence

Locations: `api_service/dashboard.html:1924`, `:2474`, `:2596`, `:2614`, `:2700`.

The drawer calls the architecture "LSTM BiGRU" despite the actual BiLSTM;
it still describes confidence-adaptive weights after v6 switched fusion.
A high tabular score is described as forged hardware even though this
classifier also uses twenty motion features. Plugins Empty reads
`botd.pluginsLength` instead of the SDK's fingerprint/detector field. The
overview model bar renders the LSTM placeholder 0.5 as a measured 50% when no
window exists. The trajectory plot includes touch move events while inference
excludes them, without distinguishing the two sources.

Fix: render documented model/evidence fields, display unavailable inputs as
unavailable, distinguish touch from mouse, and replace causal claims with
statements supported by actual flags/features. Add focused browser assertions
for missing mouse input, touch-only input, plugin flags, and v6 fusion text.

## Ordered optimization plan

| Stage | Work | Exit criteria |
| --- | --- | --- |
| 1. Ingestion and evidence correctness | F03, F06, F09; add regression probes before fixes. | Invalid telemetry gets a deterministic response; bad events cannot stall valid replay; normalized degeneracy stays SUSPECT; cross-origin cooldown works. |
| 2. Evaluation that matches operation | F01 evaluation, F04, F05, F08. | Frozen, reproducible rolling/session/cohort reports; three-verdict metrics; complete inference contract checked; true-prefix tests pass. |
| 3. Controlled candidate training | F02, F07 and F01 middle-window training. | Compare baseline, corrected-window candidate, timing-robust candidate, and mouse-only/tabular ablations using validation only. No production weights overwritten. |
| 4. Session policy and presentation | Evaluate fresh-evidence temporal aggregation; F10. | No duplicate-heartbeat evidence inflation; explicit reset/expiry semantics; current/session decisions explained correctly; replay reports cover label changes. |
| 5. Release in stages | Deploy selected bundle for observation, obtain independent browser labels, then consider enforcement. | Frozen code/bundle, independent evidence, explicit false-block budget, per-cohort metrics, rollback, and monitoring for false HUMAN/SUSPECT/BOT outcomes. |

Retain HUMAN/SUSPECT/BOT and the existing BiLSTM + XGBoost + BotD architecture.
Use internal reason codes to distinguish insufficient data, unsupported input,
ambiguous scores, and inference errors. Do not use model predictions as ground
truth labels. Keep all windows/augmentations of one session in the same split;
group by person/device when reliable metadata exists. Cap or weight windows
per session to prevent long visits from dominating training or evaluation.

Choose the candidate by reducing session-level human false blocks while
constraining bot-to-HUMAN escapes, human-to-SUSPECT friction, and detection
delay. Do not make the apparent accuracy improve by moving every difficult
case into SUSPECT. The 14 validation humans and 24 existing test humans are
too few to establish a small production false-block rate, and the old test
has already informed development. Reserve fresh labeled data for the final
decision.

Additional operational limits: touch/mobile/keyboard-only and very short
visits remain outside validated mouse classification; the acknowledged
fallback telemetry queue is RAM-only and can be lost on process termination.
These limits require explicit product behavior. Raw bot traffic that never
executes the collector is not observable by this browser-telemetry model.
