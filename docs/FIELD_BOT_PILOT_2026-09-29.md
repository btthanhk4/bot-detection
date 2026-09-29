# Browser bot pilot, 2026-09-29

This is a diagnostic experiment, not production release evidence. The private
capture files remain outside this repository in `bot-detection-test`.

## Baseline

Bundle `e3dd550e4d40453db0e17a743da7e992`, policy 10, was replayed against
15 labeled Playwright bot runs on the instrumented Silkmoon site. The evaluator
used collector telemetry requests actually sent by the browser. It counted
each browser run once; repeated heartbeat snapshots were not treated as
independent sessions.

| Generator family | Runs | Last sent BOT | Last sent HUMAN | Ever BOT | Ever HUMAN |
| --- | ---: | ---: | ---: | ---: | ---: |
| Heavy mouse | 5 | 0 | 4 | 0 | 5 |
| Circular spiral | 5 | 0 | 5 | 0 | 5 |
| Scrub hover | 5 | 0 | 3 | 0 | 5 |

The remaining last sent decisions were SUSPECT. The optional final `/detect`
probe was evaluated separately because the runner used `PERSIST_FINAL=0`;
that probe was not an observed dashboard decision. The baseline is a measured
failure on these generators, not an estimate of general production accuracy.
For a run with BiLSTM score near 0.13, even a perfect tabular score of 1.0
and the maximum BotD lift would produce risk around 0.65 under the current
fusion formula, below the BOT threshold of 0.96. The tabular-only experiment
can still reduce HUMAN mistakes to SUSPECT, but cannot by itself make those
low-BiLSTM windows BOT.

## Candidate protocol

- Keep the existing BiLSTM weights frozen and fit XGBoost on the original
  training data plus heavy mouse and circular browser runs.
- Hold out all scrub hover runs by generator family. No snapshot from a held
  out browser run enters training.
- Apply a diagnostic weight of four to each browser run's tabular windows.
- Re-run the existing same-source human/bot release replay and report the
  captured family holdout separately.
- Mark every artifact from this experiment `diagnostic_only`; the API release
  check must reject it.

Five runs per family on a single site and browser configuration are far below
what is needed to estimate a false-positive rate or generalization to unseen
automation. No independently labeled human sessions from this site were
available in this pilot.

## Frozen-BiLSTM candidate

Diagnostic bundle `4da81d5914fc47c3b2c2621b790b2f44` was trained with the
original BiLSTM artifact unchanged (identical SHA-256) and the updated XGBoost.
Its manifest is `diagnostic_only`, and the serving release check rejects it.

| Generator family | Baseline last HUMAN | Candidate last HUMAN | Candidate last BOT | Candidate ever HUMAN |
| --- | ---: | ---: | ---: | ---: |
| Heavy mouse, used in train | 4/5 | 0/5 | 0/5 | 3/5 |
| Circular spiral, used in train | 5/5 | 0/5 | 0/5 | 0/5 |
| Scrub hover, family holdout | 3/5 | 0/5 | 0/5 | 1/5 |

The candidate shifted final decisions to SUSPECT, not BOT. On the original
same-source replay it had zero human BOT and zero bot HUMAN windows, while
human SUSPECT windows increased from 1,255 to 1,279 on test. Final-snapshot
BOT recall on the original test declined from 90.91% to 87.88%.

In one-run checks on the five other bot families, ultra-human-like remained
HUMAN and drag-select became BOT. The latter needs same-site human drag
controls before it can be counted as a safe improvement. A new capture with
the observed HTTP User-Agent confirmed that the explicit no-mouse HeadlessChrome
rule remains BOT in both the API and offline replay. Older captures without
the transport header cannot validate that rule.

## Session-balanced BiLSTM candidate

Diagnostic bundle `d27030f77dab4dddb365624938b3be2e` retrained both
XGBoost and BiLSTM. Each session contributed equal total BiLSTM weight before
the fourfold captured-bot multiplier. Heavy mouse and circular runs were used
in training; all scrub-hover runs were held out by generator family.

| Generator family | Last sent BOT | Last sent HUMAN | Ever HUMAN |
| --- | ---: | ---: | ---: |
| Heavy mouse, used in train | 0/5 | 0/5 | 0/5 |
| Circular spiral, used in train | 5/5 | 0/5 | 0/5 |
| Scrub hover, family holdout | 0/5 | 0/5 | 0/5 |

The remaining last sent decisions were SUSPECT. One scrub-hover *probe* was
HUMAN; it was not sent as a persisted dashboard observation. Among the five
other one-run bot checks, drag-select became BOT and ultra-human-like became
SUSPECT. Neither result establishes a family-level detection rate, and
drag-select needs a human control group on this site. A separate capture with
observed HTTP User-Agent confirmed that the explicit no-mouse HeadlessChrome
rule still returned BOT. The older one-run no-mouse capture lacks the
transport header and cannot test that rule faithfully.

The original held-out test replay found zero human-ever-BOT and zero
bot-ever-HUMAN across 90,000 windows, but **3,446 of 24,000 human windows**
were SUSPECT (up from 1,255 for the deployed bundle), with one human session
SUSPECT at 32.8% of its checkpoints. The release gate rejected the candidate
for excessive human SUSPECT windows. Final-snapshot BOT recall on the
original test was 59/66, compared with 60/66 for the deployed bundle.
Its manifest records `diagnostic_only=true` and the gate failure; the serving
release check rejects it. It was not deployed.

## Decision and next evidence

Neither diagnostic candidate is suitable for production promotion. The
frozen-BiLSTM candidate did not call any of the 15 target runs BOT at the
last sent snapshot. Retraining BiLSTM caught the circular training family,
but not the held-out scrub family, and it increased human SUSPECT exposure.
Do not lower the BOT threshold just to force these runs into BOT: that would
make the human false-positive risk unknown.

Collect independently labeled humans using this same site and collector,
including normal mouse, touchpad, hover, scrolling, and drag selection. Then
collect more bot runs with varied timing/viewport/seed and reserve entire
generator families for evaluation. Compare family-level BOT/HUMAN/SUSPECT
outcomes, interim verdicts, and human false positives before any new bundle
is proposed for release. Five runs per family and no same-site human controls
cannot certify production accuracy.
