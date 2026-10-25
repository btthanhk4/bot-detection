# Local Motion Feature Review (2026-10-13)

## Scope

This change adds measurements, not a detector or a release-approved model.
BiLSTM, XGBoost, heuristic policy, thresholds and model artifacts are unchanged.
The new measurements appear only in the existing `interaction_shadow` output.
No production deployment, new browser traffic or model training was performed.

## Source Review

Shallow research clones live outside the product repository at
`C:/Users/Admin/bot-detection-research`. That directory contains the complete
revision manifest and private benchmarking scripts. No upstream dependency
installation or lifecycle script was executed. No upstream code was copied
verbatim into the product. License suitability must be checked separately
before adopting code, packages or datasets.

| Repository | Pinned revision | Intended use |
| --- | --- | --- |
| [BotD](https://github.com/fingerprintjs/BotD) | `66da86e9d9e7206e817a0f7fdbdfa8fe37f3cd47` | Source/detector separation |
| [FingerprintJS](https://github.com/fingerprintjs/fingerprintjs) | `dac5ae59409669f09aa09c0b2f44b7615b0520da` | Attribute availability and collection |
| [fpscanner](https://github.com/antoinevastel/fpscanner) | `4255cfd8a23fef5ea714147518d8c6ae1e5426d3` | Browser consistency checks |
| [CreepJS](https://github.com/abrahamjuliot/creepjs) | `10aa6724cd33a1015db1574211890518cd04f0cc` | Spoofing/consistency research |
| [bot-signal](https://github.com/okasi/bot-signal) | `de9b554ecb5fd6f6af49cec5c5027abd24f41d1f` | Short sliding motion windows |
| [DELBOT-Mouse](https://github.com/chrisgdt/DELBOT-Mouse) | `712a00ea994738b680b0b11bb4b518979385d07b` | Mouse sequence research |
| [BeCAPTCHA-Mouse](https://github.com/BiDAlab/BeCAPTCHA-Mouse) | `daaad5adc9235fdc3cf17ebf50c709eea790d10d` | Human/synthetic trajectory evaluation |
| [CrowdSec](https://github.com/crowdsecurity/crowdsec) | `c86bf40b34fc86abec46ff547916759d994a163e` | Server-side temporal behavior |
| [Baskerville](https://github.com/deflect-ca/baskerville) | `9659f4b39ab66fcf5329a4eccff15e97245b04f0` | Traffic aggregation and anomaly pipelines |

The first implementation studies the sliding-window idea from bot-signal,
but implements independent continuous descriptors in Python. It does not
adopt an upstream classification threshold. The other clones are references,
not integrated dependencies. BeCAPTCHA dataset access was not obtained by cloning.

## Feature Contract

`interaction_window_v2` retains the original 11 features and adds:

| Feature | Measurement |
| --- | --- |
| `move_window_speed_cv_min` | Minimum population speed CV across valid windows |
| `move_window_speed_cv_median` | Median population speed CV |
| `move_window_straightness_max` | Maximum endpoint distance / path length |
| `move_window_regular_line_score_max` | Maximum straightness / (1 + speed CV), computed within each window |
| `move_window_turn_cv_min` | Minimum CV of absolute turn angles where direction is defined |

Each window contains 14 move points, advances by one point and remains inside
the sanitized retained collector window (at most 100 events, 87 local windows).
A touch event, duplicate move timestamp or inter-move gap above 250 ms resets
the window. Click/down/up are not movement points. Stationary or non-finite
speed windows are excluded. Direction is unavailable for stationary steps;
near-zero mean turn angle is excluded rather than reported as regular turning.
Missing evidence remains null. Counts expose examined, valid-motion and
valid-turn windows. The 14-point and 250-ms settings are experimental feature
definitions, not validated human/bot thresholds.

CV uses max-scaled, two-pass variance on finite nonnegative samples with a
positive peak. This avoids overflow/underflow and the Fraction-heavy standard
library reference path on the local Python runtime. Existing timing CV code
for the original 11 features was not changed.

## Replay Evidence

Input: private collector captures from 2026-10-02, 18 runner-labeled BOT runs,
6 families, 90 sent snapshots, no human participants. Bundle:
`e3dd550e4d40453db0e17a743da7e992`.

| Family | Final HUMAN | Final SUSPECT | Final BOT |
| --- | ---: | ---: | ---: |
| Circular fixed | 0 | 3 | 0 |
| Circular jitter | 0 | 3 | 0 |
| Heavy wander fixed | 3 | 0 | 0 |
| Heavy wander jitter | 3 | 0 | 0 |
| Scrub hover fixed | 0 | 3 | 0 |
| Scrub hover jitter | 2 | 1 | 0 |
| Total | 8 | 10 | 0 |

Final/ever verdict summaries and summaries of all 11 old features matched
the v1 baseline. The full aggregate report matched between reference and
optimized v2 implementations. Feature summaries describe final retained
windows per run; this is not a new independent test dataset or an estimate of
production accuracy. The 8 HUMAN outcomes remain known bot false negatives.

See [aggregate results](INTERACTION_RESULTS_2026-10-13.json). Private raw
captures were not copied into the product repository.

## Verification

- 23 new regression cases: off-grid windows, missing/stationary data, circles,
  pauses, mixed touch, duplicate timestamps, numerical extremes, bounded work,
  legacy input, coordinate scaling and unchanged production predictions.
- Full Python suite: 389 passed, one existing Starlette/httpx deprecation warning.
- Ruff, collector build/lifecycle/profile tests, Compose configuration: passed.
- Model weights and generated collector content: unchanged.
- No real MongoDB integration test or production load test in this step.

Local paired timing experiment: synthetic 100-point circle, 87 windows,
10 warm-ups, 200 measured calls per implementation, alternating call order,
equal output assertions. Private script: `benchmark_local_motion.py`.

| CV implementation | Median ms | p95 ms |
| --- | ---: | ---: |
| Normalized reference using `statistics.pstdev` | 17.760 | 31.504 |
| Max-scaled two-pass implementation | 4.132 | 8.154 |

This measures feature extraction only, not HTTP latency or model inference.
It is not a speedup over v1 production: v1 computes fewer features, and the
new shadow measurements add CPU work. Results are machine/run dependent.

## Next Release Gate

1. Collect consenting real-traffic controls and known-runner bot captures on
   the same website. Preserve raw snapshots, source labels and model versions.
2. Export a versioned dataset, keeping vendor judgments as weak labels, not
   automatic ground truth. Resolve conflicting or unjoinable labels explicitly.
3. Split by participant/session and hold out generator families before window
   extraction. Compare baseline versus added features on validation only.
4. Measure bot-to-HUMAN, human-to-BOT, SUSPECT, coverage and decision delay by
   input type. Include touch, sparse mouse, accessibility and collector failure.
5. Promote features only after independent held-out evaluation and replay
   regression checks. Keep monitoring mode until false-positive risk is known.

There is no evidence yet that these descriptors improve classification.
Do not turn regular paths, missing mouse data or unusual profiles into BOT
solely to make the existing scripts pass.
