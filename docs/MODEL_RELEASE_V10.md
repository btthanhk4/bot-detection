# Model release v10

Bundle: `e3dd550e4d40453db0e17a743da7e992`. Policy: `10`.
BOT cutoff: `0.96`; SUSPECT cutoff: `0.45`. Both model artifact hashes are
identical to v9; the change is the versioned decision policy and its evidence.

## What changed

- A no-mouse session stays `SUSPECT` unless both the HTTP request UA and the
  browser-reported UA contain `HeadlessChrome/` **and** BotD reports webdriver,
  ChromeDriver globals, or distinctive automation properties. This narrow
  self-identifying case is `BOT/FINAL` with `decision_basis=explicit_automation`.
- The risk score from the mouse-model fusion is explicitly out of domain for
  that rule decision. The dashboard hides it and displays the rule basis.
- The release gate requires seven zero-mouse positive/near-miss checks in
  addition to the existing dense mouse-trajectory replay and regression cases.

## Same-source evaluation

The training corpus has 449 real labeled mouse sessions and 300 synthetic
training samples. The full-trajectory replay checks 1,000 windows per session.

| Replay | Validation | Test |
| --- | ---: | ---: |
| Human BOT windows | 0 / 14,000 | 0 / 24,000 |
| Bot HUMAN windows | 0 / 46,000 | 0 / 66,000 |
| Human SUSPECT windows | 413 / 14,000 | 1,255 / 24,000 |
| Maximum SUSPECT fraction in one human session | 11.9% | 14.7% |

At the final snapshot, BOT recall is 80.43% on validation and 90.91% on test;
BOT precision is 100% on those splits. These are the same-source v9 results,
not evidence that no-mouse classification accuracy improved in general. The
new rule was also exercised against a captured zero-mouse Playwright payload:
matching HeadlessChrome HTTP UA gave `BOT/FINAL`, while an ordinary HTTP UA
gave `SUSPECT/INSUFFICIENT_EVIDENCE`.

HTTP User-Agent and browser telemetry are both client-controlled. Stealth
automation can evade this rule, and a real user operating a headless browser
may be classified BOT. The seven rule fixtures are regression checks, **not**
an independent labeled holdout. Keep enforcement in monitor-only mode until a
separate cohort of humans, accessibility users, touch users, and bot families
is labeled and evaluated. Scores remain uncalibrated and should not be read as
probabilities of bot ownership.

## Reproduce

```powershell
python -m core_ml.train --dataset-root "../Tuần 3/repos/web_bot_detection_dataset" --weights-dir bot-lab/reproduce-v10/weights --device cpu
python -m pytest -q
python -m ruff check .
```
