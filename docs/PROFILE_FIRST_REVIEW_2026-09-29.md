# Profile-first decision review, 2026-09-29

The current XGBoost model is trained on mouse features. Browser/environment
columns are constant in labeled training examples, so its score is **not** a
profile anomaly score. BotD flags and fingerprint values are browser-supplied
and can be spoofed or absent. Missing mouse activity alone is not BOT evidence.

## Measured coverage

In the 15 browser runs captured for heavy-mouse, circular-spiral, and
scrub-hover, every final sent collector snapshot reported BotD score `0`,
zero flagged detectors, and no webdriver, driver-global, distinctive-property,
or headless-UA flag. Their profiles look normal to the current collector.
Promoting anomalous profiles to BOT cannot catch these 15 runs because there
is no reported profile anomaly to promote. Four additional one-run scenarios
(ultra-human-like, stealth-evasive, fast-zigzag, drag-select) likewise reported
zero BotD flags. The one basic HeadlessChrome run had four flags and is already
BOT under the explicit automation rule when the observed HTTP User-Agent is
available. These are counts from this limited harness, not production rates.

## Decision order

1. A matching HeadlessChrome User-Agent in both the HTTP request and browser
   telemetry, corroborated by webdriver or an automation-framework marker,
   yields `BOT/FINAL` without invoking the mouse models. The response marks
   their scores unavailable and does not present a calibrated risk score.
2. Isolated client-reported flags, virtual GPU, missing plugins, or high BotD
   heuristic score are investigative signals, not sufficient proof for a
   profile-only BOT decision. With insufficient mouse data they remain
   `SUSPECT`; with usable mouse data the existing fusion policy applies.
3. A profile with no reported anomaly proceeds to mouse analysis. If mouse
   evidence is missing, touch-only, degenerate, or outside the trained domain,
   the decision remains `SUSPECT`, not HUMAN or BOT.

The first rule was made independent of BiLSTM/XGBoost runtime errors. This
change does not relabel any of the 15 profile-clean bot runs. Lowering the BOT
threshold or treating every BotD flag as conclusive would change labels
without evidence about false positives in real users.

## Why SUSPECT is common

`SUSPECT` covers different conditions that should not be conflated: too few
usable mouse points (including short, touch, and keyboard-only visits), an
out-of-domain/degenerate trajectory, a risk score between the SUSPECT and BOT
thresholds, disagreement between the mouse models, or browser-only anomaly
flags without corroboration. A normal-looking profile is not proof of HUMAN,
and a missing mouse trajectory is not proof of BOT. The three profile-clean
bot families above can only be distinguished through reliable behavioral or
server-side evidence; profile escalation alone cannot reduce their SUSPECT
count safely.

To widen profile-only BOT coverage, first collect independently labeled
human and automation sessions from the same site, including short visits,
privacy browsers, VMs, accessibility tools, touch/keyboard use, and multiple
bot tool families. Evaluate candidate rules in shadow mode by **person and
tool family**, measure false BOT decisions, then version and replay the exact
policy before release. Until then, keep `SUSPECT` as the abstention state.
