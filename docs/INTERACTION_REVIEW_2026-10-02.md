# Interaction Measurements Review (2026-10-02)

## Scope

Decision policy 10 and bundle `e3dd550e4d40453db0e17a743da7e992` are unchanged.
No retraining, new classifier, threshold adjustment, or automatic blocking was
performed. The user cannot provide real-human same-site controls yet, so this
phase remains an offline experiment plus production measurement collection.

The existing collector already exports movement, down/up/click and wheel events.
`breakdown.interaction_shadow` now exposes eleven versioned measurements from
those events. This object has no verdict, probability, or heuristic rule;
`release_approved` is false. The existing 50-column XGBoost input is unchanged.

The new feature contract is `interaction_window_v1`:

| Measurement | Minimum support and interpretation |
| --- | --- |
| Move interval median / CV | Two moves for median, three for CV |
| Zero move interval ratio | At least two moves; millisecond quantization is not automation proof |
| Click interval median / CV | Two clicks for median, three for CV |
| Press duration median | Complete, unambiguous down/up pair of the same source |
| Pre-click pause median | Click with an earlier retained mouse move; includes time holding the button |
| Scroll interval median / CV | Two / three nonzero wheel events |
| Scroll magnitude CV | Two nonzero wheel events; browser delta units, not assumed pixels |
| Vertical scroll reversal ratio | Two nonzero vertical wheel events |

Timing values are milliseconds; CV is population standard deviation divided by
mean. Zero mean or insufficient observations produces `null`, not a synthetic
zero score. Features describe a retained window, **not whole-session totals**.
Each click is paired with the latest earlier retained move, not a future point.
Touch events are excluded from mouse timing. Orphaned/overlapping presses cannot
invent dwell time. Invalid values, booleans, NaN and infinity are handled; mouse
records are capped at 100 and wheel events at 50. Sorting is chronological and
stable for equal timestamps. Input objects are not mutated.

## Repaired Offline Capture Contract

`core_ml/dataset/field_captures.py` previously replaced `mouse` with only
`records`, silently removing `scrollEvents`. Both BOT and HUMAN loaders now
retain validated wheel events when present. Missing wheel data stays missing;
invalid or oversized wheel arrays cause a clear error rather than silently
erasing evidence. Training still uses the existing mouse-vector contract.

Eight new regression cases failed before the repair: wheel data disappeared and
malformed wheel data was accepted. The same cases now pass.

## Browser Protocol

The private runner `bot-detection-test/benchmark-interactions.js` generated
18 independently BOT-labeled runs: heavy-wander, circular and scrub-hover,
each with fixed and jittered pacing and three seeds (7000-7002).

Browser: Chromium `153.0.8010.12`, Playwright Extra plus stealth, HTTP local
fixture `datacat-test.invalid` resolved to localhost. Client Hints are unavailable
on this insecure origin. No traffic was sent to the production website.

Each run executes 240 mouse moves, six clicks and 18 wheel notifications using
browser input APIs, rather than dispatching synthetic DOM events. Actual UMD
collector POST payloads are captured: 90 sent snapshots total, plus one unsent
probe per run. No page errors were observed. Source labels, browser version,
seed, pacing, SDK hash, script hash and observed transport UA are saved privately.
Script SHA-256: `dcf952e702c94ac2b2f418134469ead9cbabe4f880c82358c113492b2e5c7fcf`.
An initial run with a mistyped UA was discarded and is not used in this report.

The probe is excluded from the evaluation. Final feature distributions count
each run once, not each correlated snapshot. Capture/session ID reuse across
label sets is rejected. Raw captures and bot tooling are not committed.

## Findings

| Family / pacing | Runs | Baseline final BOT / SUSPECT / HUMAN | Median click interval CV |
| --- | ---: | --- | ---: |
| Circular / fixed | 3 | 0 / 3 / 0 | 0.026363 |
| Circular / jitter | 3 | 0 / 3 / 0 | 0.055756 |
| Heavy-wander / fixed | 3 | 0 / 0 / 3 | 0.066219 |
| Heavy-wander / jitter | 3 | 0 / 0 / 3 | 0.045604 |
| Scrub-hover / fixed | 3 | 0 / 3 / 0 | 0.019301 |
| Scrub-hover / jitter | 3 | 0 / 1 / 2 | 0.038766 |

The frozen baseline still produces **0 BOT, 10 SUSPECT, 8 HUMAN** at the final
sent snapshot. Nine runs have at least one interim HUMAN decision. This new
fixture differs from earlier browser pilots; these are not before/after accuracy
improvements and should not be combined into a production false-negative rate.

All 18 runs have click/scroll cadence available, and retain six complete mouse
presses and 18 nonzero wheel events at the final snapshot. In contrast, the
earlier 24-run profile benchmark has zero runs with click cadence or scroll
cadence available: each run made only one click and no wheel interactions.

Fixed and jittered click-CV distributions overlap. The browser scheduler and
combined move/click/scroll sequence influence the observed intervals. Therefore
a rule such as "low CV means BOT" is not justified. Scroll cadence includes long
gaps between bursts; a fixed script does not necessarily have low global CV.
Human interactions can also be repetitive. Client telemetry remains spoofable.

The aggregate evidence is in `INTERACTION_RESULTS_2026-10-02.json`, with feature
availability, medians and ranges per source label/family. No classifier has been
fitted, and this measurement phase has not improved the above verdicts.

## Verification

- 339 Python tests passed, with one existing Starlette/httpx deprecation warning.
- Collector lifecycle/profile tests and Ruff passed; generated UMD is unchanged.
- API detect/telemetry round-trip preserves the measurement object and verdict.
- Regression coverage includes missing data, same-time events, malformed input,
  large timestamps, bounded windows, touch, orphan/ambiguous presses, duplicate
  identities and exclusion of the unsent probe.
- Stub-model tests verify exact preservation of verdict, score and fusion
  weights for insufficient and mature trajectories.
- All 90 new sent browser snapshots were replayed against both the pre-change
  ensemble source and the updated source with the same loaded models. Every
  output is exactly equal after removing the newly added measurement object.
- Historical 90,000-window release replay was not rerun; no candidate bundle is
  being approved or promoted by this diagnostic-only change.

## Reproduce

```powershell
# Private browser tools; writes private raw captures only.
cd C:/Users/Admin/bot-detection-test
node benchmark-interactions.js

cd 'C:/Users/Admin/Khóa luận tốt nghiệp/bot-detection-core'
python -m core_ml.evaluate_interactions --capture-dir C:/Users/Admin/bot-detection-test/captures-interactions-2026-10-02 --output docs/INTERACTION_RESULTS_2026-10-02.json
python -m pytest -q
python -m ruff check .
cd collector
npm test
```

Use `--human-capture-dir` once independently labeled controls are available.
The evaluator reports participants separately from sessions and measures final
windows per run, including coverage when features remain unknown.

## Next Experiment

1. Keep policy 10 frozen while expanding private generators, seeds, viewports
   and pacing. Do not label model predictions as ground truth.
2. Before fitting interaction features, obtain same-site HUMAN controls using
   ordinary input. Existing Phase 1 inferred timestamps cannot be used as real
   interaction timing; Phase 2 can also contain fallback timing and lacks the
   current down/up/wheel contract. Do not fill missing cadence with zero or train
   a model to distinguish those data formats instead of humans and bots.
3. Split by participant/session and generator family before creating windows.
   Compare mouse-only, interaction-only and combined candidates on validation,
   keeping an unseen family out of training and tuning.
4. Promote only after independent human false BOT, bot false HUMAN, SUSPECT
   duration and dense replay all pass. Until then, expose measurements without
   changing production verdicts.
