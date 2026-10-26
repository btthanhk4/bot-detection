"""Previously observed classification failures kept as release regressions."""

import hashlib
import json


# Relative event times from the frozen policy-v8 full-trajectory test replay.
# These are regression cases, not an independent holdout for model selection.
KNOWN_FAILURE_WINDOWS = {
    "0oa2dua3mli7mrr32c0gd4o0i2": (0, (36818,)),
    "7jbhkuigmbeo5m7ei6h4eefrmk": (0, (38589,)),
    "jfmilo33fin84baeh3k6bcnh3v": (1, (23112,)),
    "777aid4b8r0bh5do5ujttgh7me": (1, (191433, 194466, 227598)),
    "av66aadi59rs6j2njfq9ka2ab9": (
        1, (74109, 90861, 90959, 91075, 94675, 94791, 94906, 98675, 98792, 98926),
    ),
    "094i85crhkpkhqpi3rl4athrn4": (1, (606,)),
}

REGRESSION_CASE_FINGERPRINT = hashlib.sha256(
    json.dumps(KNOWN_FAILURE_WINDOWS, sort_keys=True).encode("utf-8")
).hexdigest()


def _clicks(*specs):
    return [{"ox": ox, "oy": oy, "w": w, "h": h, "hold": hold} for ox, oy, w, h, hold in specs]


# Zero-mouse fixtures for the synthetic-click rule (policy 11). Positives mirror
# Playwright/Puppeteer default clicks; negatives are the human look-alikes the
# rule must not convict: slow centred clicks, instant touchpad taps off-centre,
# too few clicks, tiny targets, one human click in the set, and malformed data.
SYNTHETIC_INPUT_CASES = (
    ("BOT", _clicks((0, 0, 83, 20, 0.3), (-0.4, 0, 29, 20, 0.1), (0.5, -0.5, 81, 36, 0.2))),
    ("BOT", _clicks((0.2, 0, 120, 40, 0.0), (0, 0.6, 60, 30, 0.2), (-0.6, 0, 90, 24, 41.0),
                    (0, 0, 200, 48, 0.1), (0.1, -0.2, 44, 44, 2.5))),
    ("SUSPECT", _clicks((0, 0, 83, 20, 96.0), (0.3, 0, 29, 20, 120.0), (0, 0.4, 81, 36, 74.0))),
    ("SUSPECT", _clicks((6.0, 2.0, 83, 20, 0.2), (-11.0, 3.0, 81, 36, 0.4), (3.0, -4.0, 120, 40, 0.1))),
    ("SUSPECT", _clicks((0, 0, 83, 20, 0.2), (0, 0, 81, 36, 0.1))),
    ("SUSPECT", _clicks((0, 0, 10, 10, 0.2), (0, 0, 12, 12, 0.1), (0, 0, 14, 14, 0.3))),
    ("SUSPECT", _clicks((0, 0, 83, 20, 0.2), (0, 0, 81, 36, 0.1), (0, 0, 120, 40, 0.2), (9.0, 4.0, 90, 30, 0.2))),
    ("SUSPECT", []),
    ("SUSPECT", [{"ox": "0", "oy": None, "w": 80, "h": 20, "hold": 0}, {"ox": True, "oy": 0, "w": 80, "h": 20},
                 {"ox": float("nan"), "oy": 0, "w": 80, "h": 20, "hold": 0}]),
)

SYNTHETIC_INPUT_RULE_GATE = {
    "rule": "synthetic_click_v1",
    "positive_cases": sum(expected == "BOT" for expected, _ in SYNTHETIC_INPUT_CASES),
    "negative_cases": sum(expected != "BOT" for expected, _ in SYNTHETIC_INPUT_CASES),
    "passed": len(SYNTHETIC_INPUT_CASES),
    "fixture_fingerprint": hashlib.sha256(
        json.dumps(SYNTHETIC_INPUT_CASES, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest(),
}


def _automation(signals=None, worker=None, permission=None, detectors=None, http_ua=None, browser_ua=None,
                accept_language=True):
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
    return {
        "_server_user_agent": http_ua or ua,
        "_server_headers": {"observed": True, "accept_language": accept_language, "sec_ch_ua": ""},
        "fingerprint": {"userAgent": browser_ua or ua},
        "botd": {
            "detectors": detectors or {},
            "automation": {"schema": "automation-v1", "signals": signals or {}, "worker": worker,
                           "notificationPermissionMismatch": permission},
        },
        "mouse": {"records": []},
    }


# Zero-mouse fixtures for policy 12. Positives: framework artefacts and the
# Puppeteer-stealth profile measured on 2026-10-26. Negatives: a clean browser,
# a UA-switcher extension (client hints + worker UA + patched getter), two
# families only, and malformed values that must not count as evidence.
AUTOMATION_EVIDENCE_CASES = (
    ("BOT", "automation_marker", _automation(detectors={"webdriver": True})),
    ("BOT", "automation_marker", _automation(signals={"playwrightGlobals": True})),
    ("BOT", "automation_marker", _automation(worker={"webdriver": True})),
    ("BOT", "environment_tampering", _automation(
        signals={"headlessScreen": True, "gpuOsMismatch": True},
        worker={"cpuMismatch": True, "rendererMismatch": True}, permission=True)),
    ("SUSPECT", None, _automation()),
    ("SUSPECT", None, _automation(
        signals={"uaHintsMismatch": True, "navigatorGetterPatched": True}, worker={"uaMismatch": True},
        http_ua="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/155.0.0.0 Safari/537.36")),
    ("SUSPECT", None, _automation(signals={"gpuOsMismatch": True}, permission=True)),
    ("SUSPECT", None, _automation(signals={"webdriverDeleted": "true", "headlessScreen": 1},
                                  detectors={"webdriver": "false"}, permission="yes")),
)

AUTOMATION_EVIDENCE_RULE_GATE = {
    "rules": ["automation_marker_v1", "environment_tampering_v1"],
    "positive_cases": sum(expected == "BOT" for expected, _, _ in AUTOMATION_EVIDENCE_CASES),
    "negative_cases": sum(expected != "BOT" for expected, _, _ in AUTOMATION_EVIDENCE_CASES),
    "passed": len(AUTOMATION_EVIDENCE_CASES),
    "fixture_fingerprint": hashlib.sha256(
        json.dumps(AUTOMATION_EVIDENCE_CASES, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest(),
}
