# Profile Shadow Review: 2026-10-02

## Scope and decision

The existing BiLSTM/XGBoost/BotD bundle remains frozen at
`e3dd550e4d40453db0e17a743da7e992`, decision policy 10. This implementation adds
bounded browser-profile observations and a separately versioned, diagnostic-only
analysis (`profile_consistency_v1`). No production threshold or model weights
changed. `release_approved` is false for every shadow analysis and report.

The collector caches the observations under `botd.profile`. The API returns and
persists `breakdown.profile_shadow`. The CLI's overlay is an experimental
comparison: automation evidence suggests BOT, OS inconsistency can raise HUMAN
to SUSPECT, and an existing BOT is never downgraded. No signal means no profile
suggestion, not a HUMAN confirmation. Profile fields are client-controlled.

## Method

The private runner `C:/Users/Admin/bot-detection-test/benchmark-profile-shadow.js`
serves the rebuilt UMD collector and a small fixture page from a local HTTP
server. It runs Chromium 153.0.8010.12 via Playwright and playwright-extra with
puppeteer-extra-plugin-stealth. The stealth profile sets a normal Chrome UA,
locale and timezone and uses `--disable-blink-features=AutomationControlled`.

Two origins use the same server: localhost (secure context) and an HTTP test
hostname mapped locally (insecure context). The runner executes three seeds
per family/origin. Families are a plain automation control, heavy random
wandering, circular movement and scrub-hover movement. It uses the real mouse
event API, pauses between moves, and sends four collector snapshots per run.
The local HTTP server records the transport UA. A final unsent probe is saved
separately and excluded from per-run decisions. Labels come from the runner.

This fixture and its movement scripts differ from the September 29 website
pilot. The two benchmarks must not be presented as matched before/after runs.
The 24 runs are a feature feasibility test, not an independent population
accuracy estimate. There are no independently labeled human controls.

## Results

| Runs | Baseline BOT | Baseline SUSPECT | Baseline HUMAN | Shadow BOT | Shadow SUSPECT | Shadow HUMAN |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Plain, localhost (3) | 3 | 0 | 0 | 3 | 0 | 0 |
| Plain, HTTP (3) | 3 | 0 | 0 | 3 | 0 | 0 |
| Stealth heavy, localhost (3) | 0 | 0 | 3 | 3 | 0 | 0 |
| Stealth circular, localhost (3) | 0 | 3 | 0 | 3 | 0 | 0 |
| Stealth scrub, localhost (3) | 0 | 0 | 3 | 3 | 0 | 0 |
| Stealth heavy, HTTP (3) | 0 | 0 | 3 | 0 | 0 | 3 |
| Stealth circular, HTTP (3) | 0 | 3 | 0 | 0 | 3 | 0 |
| Stealth scrub, HTTP (3) | 0 | 0 | 3 | 0 | 0 | 3 |

All 24 workers completed, and no page errors occurred. Client Hints were
available in the 12 localhost runs and unsupported in the 12 insecure runs.
In the 9 secure stealth runs, full Client Hints in the page and worker still
named HeadlessChrome. These two observations can have the same underlying
cause; they are not independent corroboration. Insecure stealth runs had no
headless marker and did not improve. CPU mismatch is deliberately ignored.

The old 15-run website pilot has no `botd.profile`, so replay correctly reports
zero runs with profile coverage and exactly preserves its 0 BOT / 3 SUSPECT /
12 HUMAN baseline. No new fingerprints are fabricated for historical captures.

The aggregate machine-readable report is
[`PROFILE_SHADOW_RESULTS_2026-10-02.json`](PROFILE_SHADOW_RESULTS_2026-10-02.json).
Raw profiles, captures and bot tooling remain outside Git.

Verification: 301 Python tests passed, collector lifecycle and passive-profile
tests passed, Ruff passed, and `git diff --check` found no whitespace errors.
The Python run emitted one existing Starlette/httpx deprecation warning.
The 90,000-window historical replay was not rerun for this diagnostic-only
change; production score/verdict preservation is covered by regression tests
and the old capture replay. This is not a new model release certification.

## Reproduction

From the repository root:

```powershell
python -m pytest -q
python -m ruff check .
npm --prefix collector test
python -m core_ml.evaluate_profile_shadow --capture-dir 'C:/Users/Admin/bot-detection-test/captures-profile-shadow-2026-10-02' --output docs/PROFILE_SHADOW_RESULTS_2026-10-02.json
```

To generate fresh captures with the private runner:

```powershell
node 'C:/Users/Admin/bot-detection-test/benchmark-profile-shadow.js'
```

The runner is private and is not distributed in this repository. Captures store
the runner SHA-256, collector SHA-256, browser version, origin, seed and source
label. Rerunning can change mouse timing and therefore mouse model outcomes.

## Next acceptance criteria

1. Collect human controls with ordinary, non-automated browsers, including
   privacy settings and supported browser families. Automation-launched human
   mouse sessions are not profile controls.
2. Freeze candidate rules before evaluating held-out people and bot families.
   Compare false HUMAN, false BOT, SUSPECT duration and API availability.
3. Add whole-interaction features for HTTP blind spots, test XGBoost ablations,
   and retrain only with observed timestamps and independent labels.
4. Promote any changed decision policy only after its own regression, replay
   and independent control evaluation; the current model manifest cannot
   certify a new policy or these shadow rules.
