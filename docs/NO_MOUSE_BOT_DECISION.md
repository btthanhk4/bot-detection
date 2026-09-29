# No-mouse bot decisions

The current tabular model is trained on labeled mouse trajectories (25 or more
move points). Browser/environment columns are constant in its real training
examples. Its output on a zero-mouse session is therefore out of domain: a
live stealth-browser payload scored 0.0008 with 100 mouse points and 0.9989
when the exact same payload's mouse records were removed. This does not prove
the session is a bot. Zero mouse movement is also normal for a short human
visit, keyboard navigation, and unsupported touch input.

Policy v10 still abstains (`SUSPECT`, `INSUFFICIENT_EVIDENCE`) on ordinary
zero-mouse sessions and isolated BotD flags. It makes one narrow exception:
the HTTP request User-Agent and browser-reported User-Agent both explicitly
contain `HeadlessChrome/`, and BotD reports `webdriver`, `chromeDriverGlobal`,
or `distinctiveProperties`. That combination yields `BOT/FINAL` with
`decision_basis=explicit_automation`; the mouse-model risk score is marked
out of domain and is not shown as a probability. The HTTP User-Agent is also
client-controlled, so this rule detects self-identifying automation, not
disguised or stealth bots. Do not use it as a standalone blocking policy
without independent validation.

The tabular score is marked as out of domain and hidden in the dashboard when
the mouse evidence is insufficient. The collector ignores
untrusted, DOM-dispatched mouse events; this prevents one observed fake-mouse
path from creating an artificial final `HUMAN` decision. Browser automation
input via DevTools may still produce trusted events, so this is not a general
automation detector.

The initial lab harness called `/detect` for its final 100-point payload.
That endpoint does not persist results; only the collector's earlier zero-mouse
`/telemetry` snapshot appeared in the dashboard. The harness now supports an
opt-in final `/telemetry` submission. A Selenium straight-line case returned
`BOT/FINAL` from `/detect` and `persisted:true` from `/telemetry` for the same
session. This fixes the test visibility problem, not the no-mouse inference
limitation.

## Criteria for a general no-mouse classifier

1. Collect independently labeled zero-mouse human and automation sessions from
   the actual site and target browsers. Keep bot tool families and people used
   for final validation out of training. Distinguish automated test traffic,
   crawlers, and malicious traffic according to the product's enforcement goal.
2. Train and calibrate a dedicated no-mouse model on signals available in that
   state. Do not reuse the current mouse-statistics model or its 0.96 threshold.
   Consider server-observed request sequences, session age, and corroborated
   automation indicators. A shared IP, missing mouse, or client-reported flag
   alone is not sufficient; NAT and spoofed telemetry are common confounders.
3. Release as a new versioned decision policy only after a holdout and live
   shadow-mode gate establishes acceptable false-positive rates for short
   human sessions, keyboard users, and touch users. Preserve a `SUSPECT`
   outcome whenever independent evidence is insufficient.
4. Replay the local Playwright/Puppeteer/Selenium matrix as a regression suite,
   including stealth and DOM-generated mouse events, but do not mistake these
   handcrafted examples for an unbiased accuracy estimate.

Until these conditions are met, changing all zero-mouse sessions to `BOT`
would be a relabeling rule, not a detection improvement.
