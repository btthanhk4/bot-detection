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
                accept_language=True, renderer=None, datacenter=None):
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
    return {
        "_server_user_agent": http_ua or ua,
        "_server_headers": {"observed": True, "accept_language": accept_language, "sec_ch_ua": "",
                            **({"datacenter": datacenter} if datacenter else {})},
        "fingerprint": {"userAgent": browser_ua or ua, **({"webglRenderer": renderer} if renderer else {})},
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
    # Policy 13 additions from the first real traffic (2026-10-26): a Linux host
    # posing as Windows Chrome, and genuine Firefox on plain HTTP.
    ("BOT", "environment_tampering", _automation(
        renderer="ANGLE (Intel(R) HD Graphics Direct3D11 vs_5_0 ps_5_0)",
        worker={"cpuMismatch": True, "platformMismatch": True, "rendererMismatch": True}, permission=True)),
    ("SUSPECT", None, _automation(
        browser_ua="Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:158.0) Gecko/20100101 Firefox/158.0",
        http_ua="Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:158.0) Gecko/20100101 Firefox/158.0",
        permission=True, worker={"cpuMismatch": False})),
    ("SUSPECT", None, _automation(
        renderer="ANGLE (Intel, Intel(R) Iris(R) Xe Graphics (0x00009A49) Direct3D11 vs_5_0 ps_5_0, D3D11)")),
    # Policy 14: the zero-mouse crawler seen from Google Cloud on 2026-10-26
    # (SwiftShader WebGL, rtt 0, europe-west4 address). Cloud addresses alone are
    # VPN-compatible and hypervisor GPUs are ordinary VM use, so neither may decide.
    ("BOT", "environment_tampering", _automation(
        renderer="ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (LLVM 10.0.0) (0x0000C0DE)), SwiftShader driver)",
        signals={"rttZero": True}, datacenter="gcp")),
    ("SUSPECT", None, _automation(datacenter="aws")),
    ("SUSPECT", None, _automation(renderer="VirtualBox Graphics Adapter", signals={"rttZero": True},
                                  datacenter="digitalocean")),
    ("SUSPECT", None, _automation(renderer="llvmpipe (LLVM 15.0.7, 256 bits)", datacenter="aws")),
)

# Frozen gate of policy 12 so its bundles stay verifiable after the fixtures grew.
AUTOMATION_EVIDENCE_RULE_GATE_V12 = {
    "rules": ["automation_marker_v1", "environment_tampering_v1"],
    "positive_cases": 4, "negative_cases": 4, "passed": 8,
    "fixture_fingerprint": "56d36a577f32a6d9788c66cd1cc5d08db7a137bc5d9e0ce2b94c9b08cd504d46",
}

# Frozen gate of policy 13.
AUTOMATION_EVIDENCE_RULE_GATE_V13 = {
    "rules": ["automation_marker_v1", "environment_tampering_v1"],
    "positive_cases": 5, "negative_cases": 6, "passed": 11,
    "fixture_fingerprint": "2543f760aaf58a22773b2b5c79cae5718be6b31888256c37d399a80d386bc7ac",
}

AUTOMATION_EVIDENCE_RULE_GATE = {
    "rules": ["automation_marker_v1", "environment_tampering_v1"],
    "positive_cases": sum(expected == "BOT" for expected, _, _ in AUTOMATION_EVIDENCE_CASES),
    "negative_cases": sum(expected != "BOT" for expected, _, _ in AUTOMATION_EVIDENCE_CASES),
    "passed": len(AUTOMATION_EVIDENCE_CASES),
    "fixture_fingerprint": hashlib.sha256(
        json.dumps(AUTOMATION_EVIDENCE_CASES, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest(),
}


def _device(keystrokes=None, zero_pressure=0, ua=None, coarse=False, bulk=0):
    ua = ua or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
    return {
        "_server_user_agent": ua,
        "fingerprint": {"userAgent": ua},
        "botd": {"detectors": {}},
        "mouse": {
            "records": [],
            "pointerStats": {"mouseDowns": max(zero_pressure, 3), "zeroPressureDowns": zero_pressure},
            "keyboard": {"keystrokes": keystrokes or [], "bulkInserts": bulk, "bulkMaxLength": 17 if bulk else 0,
                         "coarsePointer": coarse},
        },
    }


def _strokes(holds, intervals, kind="c"):
    t, out = 1000.0, []
    for hold, gap in zip(holds, intervals):
        out.append({"t": round(t, 1), "h": hold, "k": kind})
        t += gap
    return out


# Policy 15 fixtures, measured 2026-10-26 on Playwright/Patchright/Puppeteer:
# default keyboard.type (holds 1-7 ms), keyboard.type with delay (holds and
# spacing ~105 ms), and Puppeteer presses with pressure 0. Negatives: CMU-like
# human typing, an Android virtual keyboard (Unidentified keys), a phone with a
# coarse pointer, too few keys, one zero-pressure press, Firefox, bulk insert only.
_HUMAN_HOLDS = [92, 71, 104, 66, 118, 83, 97, 59, 88, 131, 74, 95, 102, 68]
_HUMAN_GAPS = [212, 148, 305, 176, 260, 131, 228, 190, 342, 158, 207, 263, 185, 240]
SYNTHETIC_DEVICE_CASES = (
    ("BOT", "synthetic_typing_v1", _device(_strokes([2.1, 2.5, 1.5, 2.0, 2.2, 2.5, 2.8, 2.4, 2.4, 2.2, 4.2, 5.9],
                                                     [1.2, 0.9, 1.4, 1.1, 0.8, 1.3, 1.0, 0.9, 1.2, 1.1, 1.0, 1.0]))),
    ("BOT", "synthetic_typing_v1", _device(_strokes([105.6, 106.1, 106.0, 105.8, 104.9, 106.3, 105.2, 105.9, 106.0, 105.4, 105.7, 105.5],
                                                     [106.0, 106.4, 106.1, 105.9, 106.6, 106.2, 105.8, 106.3, 106.0, 106.1, 106.2, 106.0]))),
    ("BOT", "synthetic_pointer_v1", _device(zero_pressure=3)),
    ("SUSPECT", None, _device(_strokes(_HUMAN_HOLDS, _HUMAN_GAPS))),
    ("SUSPECT", None, _device(_strokes([0.0] * 12, [140, 210, 180, 250, 160, 300, 190, 220, 170, 260, 200, 230], kind="u"))),
    ("SUSPECT", None, _device(_strokes([1.0] * 12, [140, 210, 180, 250, 160, 300, 190, 220, 170, 260, 200, 230]), coarse=True)),
    ("SUSPECT", None, _device(_strokes([2.0] * 7, [1.0] * 7))),
    ("SUSPECT", None, _device(zero_pressure=1)),
    ("SUSPECT", None, _device(zero_pressure=3, ua="Mozilla/5.0 (X11; Linux x86_64; rv:158.0) Gecko/20100101 Firefox/158.0")),
    ("SUSPECT", None, _device(bulk=2)),
    ("SUSPECT", None, _device([{"t": "x", "h": 1, "k": "c"}, {"t": 5, "h": -3, "k": "c"}, None, {"t": 9, "k": "zz"}])),
)

SYNTHETIC_DEVICE_RULE_GATE = {
    "rules": ["synthetic_typing_v1", "synthetic_pointer_v1"],
    "positive_cases": sum(expected == "BOT" for expected, _, _ in SYNTHETIC_DEVICE_CASES),
    "negative_cases": sum(expected != "BOT" for expected, _, _ in SYNTHETIC_DEVICE_CASES),
    "passed": len(SYNTHETIC_DEVICE_CASES),
    "fixture_fingerprint": hashlib.sha256(
        json.dumps(SYNTHETIC_DEVICE_CASES, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest(),
}
