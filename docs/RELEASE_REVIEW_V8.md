# Policy v8 release review

Review date: 2026-09-28.
Source commit: `82ea0aad6204d1803b5febfe73a3904df0fba509`.
Bundle: `8f08cb1719c848baab521e8e6f1c50f9`; decision policy: `8`.

## Decision

Do not approve unattended blocking or an unrestricted production release.
The existing deployment can supply supervised/shadow observations, but a healthy
endpoint does not establish classification quality or durable ingestion in all
interleavings. Resolve the implementation defects below before treating its
acknowledged telemetry as reliable during database outages.

This review covers collector/export alignment, feature construction, model
aggregation, training/release evidence, and inference/persistence boundaries.
It is not a proof that every possible input or production failure is covered.
No production source, model weights, thresholds, or remote data were changed.

## Reproduced findings

### P1: The frozen production bundle still misclassifies intermediate windows

Locations: `core_ml/models/ensemble.py:181-226`,
`core_ml/evaluate_robustness.py:99-161`.

Full-trajectory test replay at 1,000 checkpoints per session, using the exact
v8 weights, p75 guard 0.70, BOT threshold 0.96 and SUSPECT threshold 0.425:

| Measure | Result |
| --- | ---: |
| Human sessions ever classified BOT | 2 / 24 |
| Human windows classified BOT | 2 / 24,000 |
| Bot sessions ever classified HUMAN | 4 / 66 |
| Bot windows classified HUMAN | 15 / 66,000 |
| Human sessions ever classified SUSPECT | 19 / 24 |

The two human errors are Phase 1 sessions `0oa2dua3mli7mrr32c0gd4o0i2`
at relative time 36,818 ms (risk 0.9733) and `7jbhkuigmbeo5m7ei6h4eefrmk`
at 38,589 ms (risk 0.9628). Both LSTM and tabular scores exceed 0.95 on
both windows, so simply requiring agreement above 0.95 does not fix them.

The four bot sessions are `jfmilo33fin84baeh3k6bcnh3v` (Phase 1),
`777aid4b8r0bh5do5ujttgh7me`, `av66aadi59rs6j2njfq9ka2ab9` and
`094i85crhkpkhqpi3rl4athrn4` (Phase 2). Incorrect HUMAN risks span
0.2146 to 0.4248. This is not just a rounding issue next to the threshold.

These are observed errors on the existing labeled dataset, not simulated model
outputs. However, Phase 1 timestamps are estimated by the loader, and this is
not an independent live-user cohort. The session fractions describe whether
any sampled window failed, not a calibrated production error probability.
The 90,000 windows are correlated and do not represent 90,000 users.

Fix: freeze these windows for regression coverage; audit per-source input
assumptions; train on better-distributed windows from full TRAIN trajectories
instead of relying on a few retained-tail windows. Evaluate conservative
decision/temporal evidence rules on validation data. Do not fit or augment
training with these held-out trajectories, and do not claim a threshold-only
patch fixes the underlying generalization problem. A fresh final holdout is
still required after the previously disclosed test-informed policy tuning.

### P1: Sparse release evidence misses the observed errors

Locations: `core_ml/train.py:974`, `core_ml/model_bundle.py:73-84`.

The current gate and manifest certify 100 sampled checkpoints per session.
The deeper run above finds errors in the same bundle despite that certificate.
Sampling more points exposed failures; it did not introduce a new threshold,
model or training run. Increasing the count to 1,000 alone would still not
prove coverage of every possible collector export.

Fix: make known failing fixtures blocking, add dense/all-eligible-window
coverage with exact evaluated counts, and include click/other-event export
boundaries. Ensure a known failed deep evaluation for a bundle cannot be
overridden by a sparse pass. Record the replay configuration and dataset
fingerprint with the release evidence, and evaluate any changed policy anew.

### P1: Invalid chunk output becomes a valid HUMAN decision

Location: `core_ml/models/behavioral_lstm.py:158-174`.

Fault injection into the real multi-chunk aggregation with outputs `[NaN, 0.99]`
returns `0.5`. The sum of weights is NaN, so the fallback mean becomes 0.5 and
the NaN quantile does not activate the override. The ensemble's final scalar
validation cannot detect the original invalid chunk.

With the tabular score fixed at 0.1 and a valid 37-move input, this produces
`HUMAN`, risk `0.3`, decision state `FINAL`. This is a reproduced fault-handling
defect, not evidence that the deployed weights normally emit NaN.

Fix: validate the shape, count, finiteness and range of every chunk prediction
before aggregation. Invalid output must fail inference explicitly, not become
a neutral score. Add single- and multi-chunk NaN/Inf/invalid-shape regression
tests and a multi-chunk readiness probe. The current readiness input has only
25 moves and exercises the one-chunk path.

### P1: Spool row-ID reuse can delete a newly acknowledged event

Locations: `api_service/spool.py:25`, `api_service/main.py:279-362`.

The spool uses `INTEGER PRIMARY KEY`; deleting the highest row permits reuse.
An in-flight flush owns event A with ID 1. An administrative purge deletes A,
then a new event B is committed and accepted with ID 1. A's late completion
deletes ID 1 and therefore removes B from disk, although B remains in RAM.
A subsequent process crash loses B despite successful acceptance.

The local interleaving probe produced `old_id=1`, `new_id=1`, acceptance true,
zero durable rows, and B still in the in-memory queue. Database writes were
mocked; the actual spool and flush code were used with a temporary database.

Fix: use a never-reused event identity and migrate existing spool files safely.
Make acknowledgements delete only the exact owned event; coordinate purge and
in-flight ownership. Test purge/clear + enqueue + late success/failure + restart.
Do not solve this by disabling durable acknowledgement or ignoring failures.

### P2: Buffered decisions are relabeled with the current model bundle

Locations: `api_service/main.py:228-231`, `api_service/main.py:329`.

Replaying an existing `_buffered_analysis` invokes `_attach_model_metadata`
again. A decision made before a deployment is consequently persisted with the
new bundle ID, while the original verdict, risk and policy remain unchanged.
The probe persisted policy 7 with the newly configured bundle ID.

Fix: retain the original decision's complete provenance. Attach current
metadata only when running new inference. Define an explicit legacy/unknown
case rather than asserting a bundle identity that was never recorded. Test
bundle-A enqueue followed by bundle-B restart/replay and persistence failure.

### P2: Chunk aggregation is not monotonic in bot evidence

Location: `core_ml/models/behavioral_lstm.py:164-173`.

With two chunk outputs and a fixed tabular score of 0.99:

| Chunk scores | Aggregated LSTM | Fused risk | Verdict |
| --- | ---: | ---: | --- |
| 0.50, 0.99 | 0.9485 | 0.9692 | BOT |
| 0.60, 0.99 | 0.9052 | 0.9476 | SUSPECT |

Increasing a chunk's bot score increases its confidence-derived weight enough
to pull the aggregate down. This is a reproducible policy/design weakness,
not a measured false-negative rate on real traffic. It should be addressed
through a validated aggregation contract, not by declaring either verdict
ground truth for these synthetic model outputs.

Fix: compare monotonic aggregation candidates on validation data, including
fixed-weight averages and explicitly specified quantile rules. Require
property tests that raising one chunk's risk cannot lower aggregate risk.
Re-evaluate human false positives, bot misses, SUSPECT coverage and transitions
before selecting a replacement. Replacing aggregation changes the policy and
requires new release evidence; do not silently reuse the v8 manifest.

## Verification

- `python -m pytest -q`: 236 passed; one test-client dependency deprecation warning.
- `python -m ruff check .`: passed.
- `npm test` in `collector`: build and lifecycle tests passed; generated bundle unchanged.
- `python bot-lab/review_v8_probes.py`: reproduced invalid-output handling,
  spool ID reuse, metadata relabeling and non-monotonic aggregation.
- Dense frozen-bundle replay: 90 sessions, 90,000 windows; errors as reported
  above. Local report: `bot-lab/review-v8-dense-test.json`.
- Read-only live `/health`: healthy, both models loaded, bundle/policy matching
  this review, database available, queue empty at the instant of inspection.

The probes and their JSON outputs live under ignored `bot-lab/`; they do not
modify production artifacts. Passing existing tests does not cover the newly
identified scenarios.

Reproduce the dense run from the repository root (the dataset root must refer
to the existing local `web_bot_detection_dataset` checkout):

```powershell
python -m core_ml.evaluate_robustness --dataset-root $datasetRoot --weights-dir core_ml/weights --split test --checkpoints 1000 --desktop-fingerprint --full-replay --output bot-lab/review-v8-dense-test.json
```

## Release plan and acceptance criteria

1. Fix invalid-output handling and the spool identity race first. Add permanent
   regression tests for the exact probes, including process restart recovery.
2. Preserve decision provenance through retries and deployments. Assert that
   a persisted verdict always retains the bundle that actually computed it.
3. Freeze known failing cases as regression fixtures, then evaluate aggregation
   and training-window changes on validation only. The current training path
   augments a few rolling windows from retained records; distribute training
   examples over full training trajectories and include early/middle/late
   behavior without introducing validation/test examples into training. Do not
   keep tuning against a final test set. Keep a change only when error and
   SUSPECT/decision-coverage tradeoffs improve on pre-agreed criteria.
4. Strengthen the release gate beyond sparse checkpoints: replay collector-like
   intermediate exports, include event-boundary cases, and record actual
   eligible/evaluated window counts. A sparse pass must not override a known
   failure from a deeper replay of the same bundle. Bind evidence to policy,
   weights, dataset fingerprint, and replay configuration.
5. Collect an independently labeled cohort spanning supported desktop browsers,
   input devices, sites and both human/bot behavior. Keep mobile/touch and
   insufficient evidence as SUSPECT rather than treating them as confirmed bots.
   Report errors per session and by cohort; correlated windows are not
   independent users. Agree on acceptable false-positive and miss rates before
   inspecting the new holdout, and report uncertainty rather than promising zero.
   This can start with consenting human participants and controlled automation
   with known labels, kept separate from previous tuning sessions. Fingerprint
   columns currently remain constant in training (`core_ml/train.py:304-310`);
   do not claim a validated fingerprint classifier from this mouse-only corpus.
6. Repeat functional tests, offline replay, a database-outage/restart drill,
   and provenance checks. Roll out in shadow mode with an explicit rollback
   path; enable enforcement only for independently validated use cases.

The current test split informed v8 threshold tuning, as already disclosed in
`MODEL_RELEASE_V8.md`. It is useful for regression testing but cannot justify
an unbiased real-world accuracy claim. No finite audit can certify 100%
accuracy or that a model is optimized for all future traffic.
