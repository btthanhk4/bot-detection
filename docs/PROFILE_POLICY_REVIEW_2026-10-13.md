# Integrated Profile Policy Experiment

## Implementation

The product ensemble now accepts an explicit keyword-only
`predict(payload, profile_candidate=True)` for offline A/B replay. Both arms
use the same loaded model objects and prediction path. The evaluator does not
rewrite returned verdicts. Default calls remain policy 10. API call sites,
model artifacts, thresholds and collector behavior are unchanged.

The experiment is identified as `10+profile_corroborated_v1`, including
predictions where it does not trigger. It reports `release_approved: false`
and the observed evidence codes. A client payload cannot enable the mode.
This code integration is not approval to replace the deployed decision policy.

The candidate recognizes HeadlessChrome when:

- Page and successful worker observations both expose a HeadlessChrome UA or
  Client Hints brand; or
- At least one such observation is corroborated by strict boolean webdriver
  or an existing collector framework marker.

Multiple brand lists or UA/brand matches in one realm are not counted as
multiple contexts. Only known profile schema is accepted. Unsuccessful
worker observations are ignored. OS mismatch, missing browser APIs, high
heuristic score alone, regular movement, and absent mouse data are not triggers.
The previously released explicit-automation rule retains precedence.

Like the existing explicit-automation path, a match is independent of mouse
model availability. Its numeric mouse/fusion outputs are marked out of domain;
this rule does not manufacture a calibrated probability. All observations
are client-controlled and can be concealed or forged. Page and worker are
separate contexts, not statistically independent proof. Detecting automation
also does not establish malicious intent or click fraud.

## Primary Code References

Independently implemented Python logic, no upstream package installation or
copied source. Reviewed code at pinned revisions:

- [BotD webdriver detector](https://github.com/fingerprintjs/BotD/blob/66da86e9d9e7206e817a0f7fdbdfa8fe37f3cd47/src/detectors/webdriver.ts)
  and [distinctive properties detector](https://github.com/fingerprintjs/BotD/blob/66da86e9d9e7206e817a0f7fdbdfa8fe37f3cd47/src/detectors/distinctive_properties.ts):
  explicit automation observations rather than inferring bots from absent mouse input.
- [fpscanner context mismatch](https://github.com/antoinevastel/fpscanner/blob/4255cfd8a23fef5ea714147518d8c6ae1e5426d3/src/detections/hasContextMismatch.ts),
  [worker webdriver](https://github.com/antoinevastel/fpscanner/blob/4255cfd8a23fef5ea714147518d8c6ae1e5426d3/src/detections/hasWebdriverWorker.ts)
  and [bot user agent](https://github.com/antoinevastel/fpscanner/blob/4255cfd8a23fef5ea714147518d8c6ae1e5426d3/src/detections/hasBotUserAgent.ts):
  inspect multiple browser contexts. Our candidate does not adopt its broad
  bot/headless substring rule or treat generic context mismatch as BOT.

## Observed Results

Frozen bundle: `e3dd550e4d40453db0e17a743da7e992`. Inputs are the existing
2026-10-02 profile and interaction capture directories. The 42 runs all have
BOT labels from the runner, not from the model. Compare all 186 sent snapshots;
exclude each run's final unsent test probe. Reject duplicate capture/session IDs
across directories. Do not count correlated snapshots as independent runs.

| Final verdict on browser bots | Baseline | Candidate |
| --- | ---: | ---: |
| BOT | 6 | 15 |
| HUMAN | 20 | 14 |
| SUSPECT | 16 | 13 |

Nine runs changed: three circular (SUSPECT to BOT), three heavy-wander
(HUMAN to BOT), three scrub-hover (HUMAN to BOT). All were secure-localhost
stealth runs exposing HeadlessChrome Client Hints in page and worker.
Across intermediate snapshots, 12 HUMAN and 24 SUSPECT outcomes became BOT.
Existing BOT outcomes were preserved. Insecure-HTTP captures did not improve.
The same captures informed rule development: this is a diagnostic replay,
not an independent generalization estimate. Secure context alone is not a
detector and does not guarantee that Client Hints will expose other tools.

Compatibility controls use one final collector-sized window per deduplicated
mouse-dataset session, not a full-session release replay:

| Mouse-only labels | Runs | Before and after |
| --- | ---: | --- |
| HUMAN | 109 | 107 HUMAN, 2 SUSPECT, 0 BOT |
| BOT | 340 | 291 BOT, 49 SUSPECT, 0 HUMAN |

These controls have no browser profiles. Unchanged results are expected and
cannot establish the false-positive rate of the new profile policy. There
are zero independently labeled human browser captures in this experiment.
No model fitting or threshold tuning was performed.

## Verification and Reproduction

- 28 new cases; full suite: 417 passed, one existing Starlette/httpx warning.
- Ruff, collector build/lifecycle/profile tests and Compose config passed.
- Positive and negative rule cases include missing mouse, unavailable worker,
  duplicate observations, malformed booleans, unknown schema, generic profile
  mismatch, broken models and preservation of the baseline decision path.
- Evaluator tests cover probe exclusion, independent counting, conflicting
  input identities and explicitly reporting candidate human false positives.

From the repository root, using the private local capture folders:

```powershell
python -m core_ml.evaluate_profile_candidate `
  --capture-dir C:/Users/Admin/bot-detection-test/captures-profile-shadow-2026-10-02 `
  --capture-dir C:/Users/Admin/bot-detection-test/captures-interactions-2026-10-02 `
  --dataset-root '../Tuần 3/repos/web_bot_detection_dataset' `
  --output docs/PROFILE_CANDIDATE_RESULTS_2026-10-13.json
```

Use repeated `--human-capture-dir` for independently attested human controls.
Output is aggregate only: [saved results](PROFILE_CANDIDATE_RESULTS_2026-10-13.json).

## What To Integrate Next

| Reference | Suitable next step | Missing evidence or infrastructure |
| --- | --- | --- |
| BotD / fpscanner | Test the integrated candidate on regular browsers and known automation | Human browser profiles; held-out bot families |
| CreepJS / FingerprintJS | Study availability and consistency across contexts | Browser/privacy compatibility tests; do not equate fingerprints with identity |
| bot-signal / DELBOT-Mouse / BeCAPTCHA-Mouse | Ablate local motion features, retrain with session/family splits | Same-site human controls; independent evaluation |
| CrowdSec / Baskerville | Aggregate actual business requests over bounded time windows | Backend/CDN request logs and trusted timing; collector uploads are not business requests |

Do not bulk-import all heuristics, turn DevTools/CDP presence into a hard ban,
or label people from CPU count, timezone, plugin count or shared IP alone.
Keep GNN out of scope. Before default activation: collect human profiles with
consent, hold out users/tool families, measure false positives and coverage,
review automation exceptions, then update the release gate and policy evidence.
This iteration did not push GitHub, deploy or enable automatic blocking.
