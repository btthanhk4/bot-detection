# Production Logic Audit and Optimization Plan

Date: 2026-09-26

Audited baseline: `3929609d784122a5b33f919f0cd20dfbc51895c3`.
Local model bundle: `2bf12fb8ecab4fa7b7c70e9cf1f0d3cf`, decision policy 5.

## Scope and conclusion

Reviewed the collector, feature extraction, ensemble, model wrappers,
training/evaluation pipeline, API, persistence, dashboard decision display,
configuration, and deployment gates. Ran the existing tests and additional
read-only fault/edge-case probes. No production traffic was generated, no server
was inspected, no model was retrained, and no application code was changed.

This is not proof that every possible defect has been found. In particular,
browser/device compatibility, real MongoDB crash recovery, independent field
accuracy, and production load have not been certified in this audit.

Recommendation: keep the existing three-signal architecture. Do not add GNN or
increase model complexity now. Fix correctness and evaluation validity first.
The current evidence does not justify unattended blocking or treating HUMAN as
proof of a legitimate user. Use monitoring/shadow decisions while fixing and
validating the issues below.

## Confirmed findings

### B01 - P1: Collector stops heartbeats after retry exhaustion

- Location: `collector/src/index.js:175`, `:281`.
- After the initial failure and three failed retries, `scheduleRetry()` returns
  at attempt 4 without clearing `pendingRetry`; `retryTimer` is already null.
- Every subsequent heartbeat sees pending work and returns without sending.
- Probe against the committed SDK: four failed transmissions, then network
  recovery; the heartbeat returned false and transmission count remained four.
- Fix: explicitly terminate the exhausted retry cycle and allow a later
  heartbeat to start a new bounded cycle. Preserve lifecycle and in-flight
  identity guards; respect Retry-After and avoid a busy retry loop.
- Acceptance: outage beyond the retry budget, recovery, changed/unchanged
  activity, zero retries, destroy/restart, and new activity during an in-flight
  retry all have deterministic outcomes and no permanent stall.

### B02 - P1: Positive heuristic evidence can reduce fused risk

- Location: `core_ml/models/ensemble.py:57`, `:158`, `:173`.
- With fixed LSTM=1 and tabular=1, heuristic 0 yields 0.9455/BOT; heuristic 0.2
  yields 0.9298/SUSPECT at the configured 0.93 threshold.
- These are controlled model stubs isolating fusion, not measured field rates.
  The score-dependent heuristic weight increases the denominator enough to
  dilute stronger model evidence, contradicting its positive-evidence role.
- Fix: compare a fixed nonnegative-weight baseline with a monotonic evidence
  fusion policy. Fit/calibrate only on training/validation data, not test data.
  Do not patch this by lowering the BOT threshold alone.
- Acceptance: increasing positive evidence cannot lower risk when other
  signals are fixed. Sweep model-score combinations and threshold boundaries;
  revalidate the complete policy before promotion.

### B03 - P1: Invalid model output can produce a final HUMAN decision

- Location: `core_ml/models/ensemble.py:150`, `:180`;
  `core_ml/models/behavioral_lstm.py:146`; `api_service/main.py:469`.
- Injecting LSTM NaN with tabular=0.01 and 25 moves produced FINAL/HUMAN,
  risk=0.0941. NaN is replaced by 0.5 without invalidating model availability.
- The health probe checks the already-sanitized fused value, so it may also
  miss this failure. This does not show that current weights contain NaN.
- Fix: validate each required model output before fusion; raise an inference
  error or mark the decision unavailable. Never silently interpret corrupt
  output as valid human evidence. Apply the same rule to schema/shape failures.
- Acceptance: NaN, infinity, invalid shape, model exceptions, and incompatible
  feature dimensions cannot produce a successful final HUMAN/BOT result;
  health reports the failure. Preserve existing API error semantics.

### B04 - P1: Degenerate records satisfy the behavioral evidence gate

- Location: `core_ml/features/mouse_features.py:63`, `:331`;
  `core_ml/models/ensemble.py:180`.
- Using the actual local bundle, 25 identical move records at time=0,
  x=y=0.2, with no fingerprint, produced FINAL/HUMAN with risk=0.1019.
- Twenty-five stationary points with increasing timestamps also produced
  FINAL/HUMAN (0.1001). Event count alone is not evidence of mouse dynamics.
- Fix: define evidence quality separately from raw count: duplicate handling,
  positive elapsed time, meaningful transitions, and supported pointer source.
  Derive tolerances from supported browser sampling and validation data.
  Do not classify accessibility users or stationary users as bots by default.
- Acceptance: duplicated/zero-duration/degenerate windows remain SUSPECT with
  an explicit reason; valid low-speed movement is not accidentally discarded.

### B05 - P1: Early-session evaluation can use the middle/end of a session

- Location: `core_ml/dataset/loader.py:380`;
  `core_ml/train.py:318`, `:510`; `core_ml/evaluate.py:155`.
- Phase 2 keeps only the last 5,000 records before prefix extraction. The
  first 25/50/100 retained moves need not be the actual first moves.
- Local dataset probe: 449 deduplicated real sessions; 220 Phase 2 sessions
  retained exactly 5,000 records with a positive starting timestamp.
- Affected assignments: train 154, validation 32, test 34. Of these, validation
  includes 4 humans/28 bots; test includes 5 humans/29 bots.
- Fix: retain original session boundaries and extract true prefixes before
  any tail cap. Use bounded views/caches for training efficiency without losing
  provenance. Version preprocessing and preserve session-level split ownership
  when content hashes change.
- Acceptance: sessions longer than 5,000 events yield prefixes identical to
  the raw source prefix. Recompute early-session reports and retrain candidate
  artifacts separately. Existing early reports are not reliable evidence for
  true first-arrival behavior on the affected sessions.

### B06 - P2: Click events can evict the movement needed for a decision

- Location: `collector/src/mouse.js:268`;
  `core_ml/features/mouse_features.py:132`, `:331`.
- The rolling cap is 100 mixed events, not 100 moves. Twenty-five moves
  followed by 80 clicks leave only 20 moves in the server window.
- Controlled probe: a previously sufficient FINAL decision becomes
  INSUFFICIENT_EVIDENCE/SUSPECT. The latest persisted decision replaces the old
  one; there is no separate retained evidence summary.
- Fix: specify a bounded movement window and independently bounded click
  context, preserving the click/move feature definition. Add freshness and
  evidence-history rules instead of permanently locking any old verdict.
- Acceptance: click bursts, idle periods, touch/mouse switches, reloads, and
  long sessions behave consistently. Any changed feature/window semantics
  require training/serving parity and candidate re-evaluation.

### B07 - P2: Persistence removes pointer source and recomputes different stats

- Location: `api_service/database.py:295`;
  `core_ml/features/mouse_features.py:91`;
  `core_ml/models/ensemble.py:83`.
- Inference excludes touch records, but storage sanitization drops `source`
  and computes mouse statistics over the retained touch trajectory.
- Probe: 25 touch moves give zero inference mouse points, while stored stats
  report 25. Re-running the sanitized records with controlled benign models
  treats them as mouse and returns a different decision.
- The production replay buffer uses the original event; this finding concerns
  stored detail/raw telemetry and later offline reuse, not that buffer.
- Fix: preserve source and share canonical evidence selection across inference,
  persistence, dashboard, and offline export. Mark legacy source as unknown;
  do not invent mouse provenance during migration.
- Acceptance: mixed/touch-only/legacy records have matching counts and domain
  eligibility before and after storage round trips.

### B08 - P2: Stale dashboard state overrides a newer final detail response

- Location: `api_service/dashboard.html:2454`.
- `deferred` ORs the old row's decision state with the fresh detail state.
- Executing the current expression with a stale insufficient row and a fresh
  FINAL/BOT detail returns true, displaying SUSPECT and hiding the fresh score.
- Fix: choose one authoritative revision for the complete decision object;
  only fall back to the row when detail is unavailable. Keep selection guards.
- Acceptance: insufficient-to-BOT/HUMAN transitions and delayed/out-of-order
  detail responses display one consistent revision.

### B09 - P2: Long browser URLs violate the SDK/API contract

- Location: `collector/src/index.js:123`;
  `api_service/main.py:371`.
- The SDK sends full page URL/referrer without bounds; both API fields have
  a 2,048-character limit. A URL containing a 3,000-character query is rejected
  by TelemetryPayload with `string_too_long`, losing the whole event.
- Fix: define bounded URL metadata in the SDK, with explicit truncation or
  query normalization, while preserving API request limits. Do not endlessly
  retry permanent validation failures. Keep meaningful path information.
- Acceptance: long/encoded query strings and long referrers still deliver
  valid telemetry; malformed payloads remain rejected.

## Model and release risks

### R01 - Training/serving environment mismatch

Real training and evaluation sessions use an empty fingerprint and no BotD
flags (`train.py:627`, `evaluate.py:160`). Synthetic human fingerprints use
25-45 fonts (`dataset/loader.py:706`), whereas the browser probe checks only 13
font names (`collector/src/fingerprint.js:131`). This is a confirmed feature
distribution mismatch; its production error rate is not measured by this audit.

Compare mouse-only tabular, full tabular, and each signal's contribution on
controlled browser data. Repair synthetic feature ranges and missingness;
do not invent labels for live sessions from the same ensemble being evaluated.
Include legitimate privacy-restricted browsers, touch-capable laptops, remote
desktops, and different sampling rates. Mobile/keyboard-only users remain
unsupported evidence, not automatic bots.

### R02 - Current accuracy evidence is too narrow for a production guarantee

The committed `heldout_evaluation.json` reports 90 same-dataset test sessions:
24 humans, 66 bots, TN=24, FP=0, FN=10, TP=56, BOT recall=84.85%.
These are existing report values, not a fresh benchmark in this audit.
The ten non-BOT bot sessions are not necessarily HUMAN; binary evaluation
combines HUMAN and SUSPECT as non-BOT. Add a complete 2-label by 3-verdict table.

Zero false positives among 24 humans does not establish near-zero field false
positives. The fused score is explicitly uncalibrated, and `confidence` is a
distance from 0.5, not empirical correctness probability.

Measure false-HUMAN bot escapes, human-to-BOT errors, human-to-SUSPECT friction,
decision coverage, time to decision, and session-level ever-blocked rates over
all update windows. Keep test data frozen after choosing the policy and gather
an independently labeled browser set. Track source/group leakage and the
estimated timing in Phase 1 separately from real Phase 2 timing.

### R03 - Health is not a model-quality release gate

`api_service/main.py:157` checks presence of metric dictionaries and some policy
settings. The deployment workflow accepts a healthy service without requiring
quality evidence to pass. Runtime health and statistical model quality need
separate gates. Add preprocessing version, minimum-point policy, evaluation
provenance, minimum sample sizes, and explicit metric checks to release evidence.
Validate the exact candidate bundle and code combination before deployment.

### R04 - Persistence reliability remains limited

The acknowledged fallback buffer is process-local RAM (`main.py:168`). A crash
can lose buffered telemetry. Worker scaling is intentionally restricted to one
and does not solve durability. If loss is unacceptable, add a durable queue or
return a retryable failure until persistence is available. This can follow the
decision-logic work, but the delivery guarantee must be documented now.

## Ordered implementation plan

| Stage | Work | Completion gate |
| --- | --- | --- |
| 1: Regressions and targeted repairs | Turn B01/B03/B04/B07/B08/B09 probes into tests; repair retry, invalid-output handling, evidence validity, provenance, fresh detail selection, and bounded metadata. | Every new regression fails on baseline and passes on the fix; existing Python/collector tests pass; API compatibility reviewed. |
| 2: Canonical online evidence | Resolve B06; define movement/click windows, freshness, source and session lifecycle; reuse the same preprocessing for serving and training. | Round-trip feature parity, no click-driven accidental evidence loss, bounded memory, and replay of every session update. |
| 3: Trustworthy dataset/evaluation | Resolve B05/R01; regenerate true-prefix views, preserve splits by source/session identity, record source timing and feature versions. | No session leakage; prefix provenance tests; browser feature contract tests; candidate reports generated in a separate directory. |
| 4: Fusion and model optimization | Resolve B02; compare simple monotonic fusion and signal ablations; tune thresholds using validation, then evaluate frozen test and independent browser cohorts. | No positive-evidence inversion; explicit error/coverage targets met without hiding SUSPECT; no test-driven threshold tuning. |
| 5: Controlled release | Resolve R03; deploy only an approved bundle in shadow mode, compare old/new outcomes, then canary with rollback. Address R04 according to loss tolerance. | Exact bundle/preprocessing/policy traceability; known-good rollback; field monitoring; no automatic block rollout without sufficient evidence. |

Changes to input windows, evidence gates, or fusion alter policy behavior even
when neural weights are unchanged. Increment the policy/preprocessing version
and rerun evaluation instead of reusing the old release evidence.

Keep the visible states HUMAN, SUSPECT, BOT. Internally retain reason codes for
insufficient evidence, unsupported input, conflicting signals, and inference
failure. SUSPECT is not a bot label and must not silently become an automatic
block or a supervised training label.

Useful optimizations after correctness: avoid computing SDK chunks immediately
discarded by getPayload; reuse canonical preprocessing within one prediction;
cache predictions only for identical evidence plus bundle/policy versions;
consider batching only after profiling. None of these should change semantics.

## Verification performed

- `python -m pytest -q`: 201 passed; one dependency deprecation warning.
- `node collector/test.js`: collector lifecycle tests passed.
- `python -m ruff check .`: passed.
- Read-only probes: retry exhaustion/recovery, fusion monotonicity, NaN output,
  duplicate/stationary input using actual weights, mixed-event eviction,
  touch storage round-trip, stale drawer state, and long-URL schema rejection.
- Loaded local dataset and counted affected capped Phase 2 sessions.
- Existing tests passing does not cover the newly reproduced failures above.

No push/deployment is part of this review. Application fixes and candidate
training should be separate, tested changes, not bundled into a documentation
update that automatically triggers production deployment.

## Follow-up implementation

Policy 6 repairs B01-B09 and adds tests for retry recovery, invalid model
outputs, degenerate movement, real early-session prefixes, touch provenance,
and request metadata bounds. A separate candidate was trained, passed the
validation release gate, and was published as bundle
`2151c04e5a304021a0e86f037d84a848`.

Frozen same-source evaluation on 90 test sessions: TN=24, FP=0, FN=4, TP=62.
The true 25-move validation view: TN=14, FP=0, FN=7, TP=39. These do not
resolve R01/R02; the test set was used during prior development and the
browser-fingerprint probe is a controlled sensitivity check, not field labels.
The runtime release gate now validates metric values and the policy version.
R04 durability and independently labeled field validation remain open work.
