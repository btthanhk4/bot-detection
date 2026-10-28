"""Previously observed classification failures kept as release regressions."""

import hashlib
import json
import os


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
                accept_language=True, renderer=None, datacenter=None, page_ms=None, active=False,
                fingerprint=None, headers=None):
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
    return {
        "_server_user_agent": http_ua or ua,
        "_server_headers": {"observed": True, "accept_language": accept_language, "sec_ch_ua": "",
                            **({"datacenter": datacenter} if datacenter else {}), **(headers or {})},
        "fingerprint": {"userAgent": browser_ua or ua, **({"webglRenderer": renderer} if renderer else {}),
                        **(fingerprint or {})},
        "botd": {
            "detectors": detectors or {},
            "automation": {"schema": "automation-v1", "signals": signals or {}, "worker": worker,
                           "notificationPermissionMismatch": permission},
        },
        "mouse": {"records": [], **({
            "pageAgeMs": page_ms,
            "counters": {"mousemove": 40 if active else 0, "mousedown": 0, "click": 0, "wheel": 0},
        } if page_ms is not None else {})},
    }


_IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 "
           "(KHTML, like Gecko) Version/26.6 Mobile/15E148 Safari/604.1")
_PIXEL = ("Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/153.0.8010.12 Mobile Safari/537.36")
_CUBOT = "Mozilla/5.0 (Linux; Android 10; Cubot X30) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36"
_GOOGLEBOT = ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Googlebot/2.1; "
              "+http://www.google.com/bot.html) Chrome/155.0.0.0 Safari/537.36")
_D3D = "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics (0x00009A49) Direct3D11 vs_5_0 ps_5_0, D3D11)"
_HEADLESS_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "HeadlessChrome/154.0.0.0 Safari/537.36")
_SWIFTSHADER = "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver)"


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
    # Policy 14/16: the zero-mouse crawler seen from Google Cloud on 2026-10-26
    # (SwiftShader WebGL, rtt 0, europe-west4 address, 14 s without input). Cloud
    # addresses alone are VPN-compatible and hypervisor GPUs are ordinary VM use,
    # so neither may decide; a cloud desktop with a person at it must not either.
    ("BOT", "idle_cloud_browser", _automation(
        renderer="ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (LLVM 10.0.0) (0x0000C0DE)), SwiftShader driver)",
        signals={"rttZero": True}, datacenter="gcp", page_ms=14000)),
    ("SUSPECT", None, _automation(
        renderer="ANGLE (Microsoft, Microsoft Basic Render Driver Direct3D11 vs_5_0 ps_5_0, D3D11)",
        signals={"rttZero": True}, datacenter="aws", page_ms=60000, active=True)),
    ("SUSPECT", None, _automation(
        renderer="ANGLE (Microsoft, Microsoft Basic Render Driver Direct3D11 vs_5_0 ps_5_0, D3D11)",
        signals={"rttZero": True}, datacenter="aws", page_ms=3000)),
    ("SUSPECT", None, _automation(renderer="SwiftShader", signals={"rttZero": True}, datacenter="gcp")),
    # Policy 17: phone emulation by Playwright/Puppeteer (measured 2026-10-26) and
    # self-declared automation. Negatives: real iPhone/Android values, DevTools
    # device mode (sets the platform), an Android Studio emulator, a phone brand
    # whose name contains "bot".
    ("BOT", "mobile_emulation", _automation(
        browser_ua=_IPHONE, http_ua=_IPHONE, renderer=_D3D,
        fingerprint={"platform": "Win32", "deviceMemory": 16, "maxTouchPoints": 1})),
    ("BOT", "mobile_emulation", _automation(
        browser_ua=_PIXEL, http_ua=_PIXEL, renderer=_D3D,
        fingerprint={"platform": "Win32", "deviceMemory": 16, "maxTouchPoints": 1})),
    ("BOT", "automation_marker", _automation(browser_ua=_GOOGLEBOT, http_ua=_GOOGLEBOT)),
    ("BOT", "automation_marker", _automation(headers={"signature_agent": True})),
    ("SUSPECT", None, _automation(browser_ua=_IPHONE, http_ua=_IPHONE, renderer="Apple GPU",
                                  fingerprint={"platform": "iPhone", "deviceMemory": 0, "maxTouchPoints": 5})),
    ("SUSPECT", None, _automation(browser_ua=_PIXEL, http_ua=_PIXEL, renderer="Mali-G710",
                                  fingerprint={"platform": "Linux aarch64", "deviceMemory": 8, "maxTouchPoints": 5})),
    ("SUSPECT", None, _automation(browser_ua=_IPHONE, http_ua=_IPHONE, renderer=_D3D,
                                  fingerprint={"platform": "iPhone", "deviceMemory": 16, "maxTouchPoints": 1})),
    ("SUSPECT", None, _automation(
        browser_ua=_PIXEL, http_ua=_PIXEL, renderer="Android Emulator OpenGL ES Translator (Google SwiftShader)",
        fingerprint={"platform": "Linux x86_64", "deviceMemory": 2, "maxTouchPoints": 10})),
    ("SUSPECT", None, _automation(browser_ua=_CUBOT, http_ua=_CUBOT)),
    # Policy 20: stealth headless Chrome seen on the live site (2026-10-27): HeadlessChrome UA,
    # SwiftShader, headless screen, webdriver hidden; and a forged HeadlessChrome header only.
    ("BOT", "automation_marker", _automation(
        browser_ua=_HEADLESS_UA, http_ua=_HEADLESS_UA, renderer=_SWIFTSHADER,
        detectors={"headlessUa": True}, signals={"headlessScreen": True, "appVersionAutomation": True})),
    ("SUSPECT", None, _automation(http_ua=_HEADLESS_UA)),
    ("SUSPECT", None, _automation(datacenter="aws")),
    ("SUSPECT", None, _automation(renderer="VirtualBox Graphics Adapter", signals={"rttZero": True},
                                  datacenter="digitalocean")),
    ("SUSPECT", None, _automation(renderer="llvmpipe (LLVM 15.0.7, 256 bits)", datacenter="aws")),
    # Policy 24, measured through the HTTPS gateway (2026-10-28): Puppeteer-stealth has no
    # permission contradiction in a secure context, so GPU and CONTEXT alone did not convict
    # it; an enabled CDP Runtime is its third family. DevTools open on its own is not enough.
    ("BOT", "environment_tampering", _automation(
        renderer="Intel Iris OpenGL Engine", signals={"gpuOsMismatch": True, "cdpRuntime": True},
        worker={"rendererMismatch": True, "cpuMismatch": True})),
    ("SUSPECT", None, _automation(signals={"cdpRuntime": True})),
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

# Frozen gate of policies 14-15.
AUTOMATION_EVIDENCE_RULE_GATE_V14 = {
    "rules": ["automation_marker_v1", "environment_tampering_v1"],
    "positive_cases": 6, "negative_cases": 9, "passed": 15,
    "fixture_fingerprint": "27b8fa2ec1a09e7037b050a1203931ea97a35ea4f55ca16eadaa91a8b19773a2",
}

# Frozen gate of policy 16.
AUTOMATION_EVIDENCE_RULE_GATE_V16 = {
    "rules": ["automation_marker_v1", "environment_tampering_v1", "idle_cloud_browser_v1"],
    "positive_cases": 6, "negative_cases": 12, "passed": 18,
    "fixture_fingerprint": "d8a9be4f1e11f12e582f799fb567fc962bb608eb56f3fa44a7b544a2ff56c225",
}

# Frozen gate of policies 17-19.
AUTOMATION_EVIDENCE_RULE_GATE_V17 = {
    "rules": ["automation_marker_v1", "environment_tampering_v1", "idle_cloud_browser_v1", "mobile_emulation_v1"],
    "positive_cases": 10, "negative_cases": 17, "passed": 27,
    "fixture_fingerprint": "738487d2e00bbe4a8df1900db1f9443910b3ecbac8bd13b6170180784f190f74",
}

# The HeadlessChrome UA checks of train.validate_explicit_automation_rule: policy 10-19
# convicted only with a framework artefact; policy 20 also when both UAs declare it.
EXPLICIT_AUTOMATION_RULE_GATE_V10 = {
    "rule": "headless_ua_and_framework_v1", "positive_cases": 2, "negative_cases": 5, "passed": 7,
}
EXPLICIT_AUTOMATION_RULE_GATE = {
    "rule": "headless_ua_and_framework_v1", "positive_cases": 3, "negative_cases": 4, "passed": 7,
}

# Frozen gate of policies 20-23.
AUTOMATION_EVIDENCE_RULE_GATE_V20 = {
    "rules": ["automation_marker_v1", "environment_tampering_v1", "idle_cloud_browser_v1", "mobile_emulation_v1"],
    "positive_cases": 11, "negative_cases": 18, "passed": 29,
    "fixture_fingerprint": "148fa79976767a10794a32ba8a1ec267c9bf4eec0d683d72f58b63880a6622ee",
}

AUTOMATION_EVIDENCE_RULE_GATE = {
    "rules": ["automation_marker_v1", "environment_tampering_v1", "idle_cloud_browser_v1", "mobile_emulation_v1"],
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
    # Policy 16: Vietnamese Telex through Unikey/EVKey ("Hương" + f -> "Hường"):
    # the input method injects Backspace and letters with ~0 ms holds. A script
    # typing accented text sends them as plain keys, with no Backspace.
    ("SUSPECT", None, _device(
        _strokes([92, 71, 104, 66], [212, 148, 305, 176])
        + [dict(s, t=s["t"] + 900) for s in _strokes([0.5, 0.5, 0.5], [1.2, 1.2, 1.2], kind="b")]
        + [dict(s, t=s["t"] + 904) for s in _strokes([0.5], [1.2], kind="n")]
        + [dict(s, t=s["t"] + 905) for s in _strokes([0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5], [1.2] * 8)])),
    ("BOT", "synthetic_typing_v1", _device(
        [dict(s, k="n" if i % 3 == 0 else "c") for i, s in enumerate(_strokes([1.5] * 12, [1.2] * 12))])),
    # Policy 22, from the Aalto 136M keystrokes (168,593 people): a skilled typist with
    # an even rhythm but human holds, and a keyboard that reports key-up with key-down,
    # were both convicted by policy 15-21. Selenium typing one key per fixed sleep
    # (measured 2026-10-28: holds 0.3 ms, interval CV 0.017) is the script they resemble.
    ("SUSPECT", None, _device(_strokes(_HUMAN_HOLDS[:12],
                                       [150, 160, 145, 155, 165, 150, 140, 158, 152, 147, 162, 149]))),
    ("SUSPECT", None, _device(_strokes([0.0, 1.0, 0.0, 2.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 2.0, 0.0],
                                       _HUMAN_GAPS[:12]))),
    ("BOT", "synthetic_typing_v1", _device(_strokes(
        [0.3, 0.4, 0.3, 0.35, 0.3, 0.4, 0.3, 0.3, 0.35, 0.4, 0.3, 0.3],
        [110.4, 111.2, 109.8, 110.6, 110.9, 110.1, 111.4, 110.2, 110.7, 110.3, 111.0, 110.5]))),
)

# Frozen gate of policy 15.
SYNTHETIC_DEVICE_RULE_GATE_V15 = {
    "rules": ["synthetic_typing_v1", "synthetic_pointer_v1"],
    "positive_cases": 3, "negative_cases": 8, "passed": 11,
    "fixture_fingerprint": "5727b7e21ed1e868cd94b1566219b6632023c45463e021c07bda389e9e867de1",
}

# Frozen gate of policies 16-21 (typing on interval CV < 0.10 or hold < 12 ms alone).
SYNTHETIC_DEVICE_RULE_GATE_V16 = {
    "rules": ["synthetic_typing_v1", "synthetic_pointer_v1"],
    "positive_cases": 4, "negative_cases": 9, "passed": 13,
    "fixture_fingerprint": "47c4086dc5817b2bf0f60d7c5e2bafe77cbc2254ff875f4291272fd3604a1442",
}

SYNTHETIC_DEVICE_RULE_GATE = {
    "rules": ["synthetic_typing_v1", "synthetic_pointer_v1"],
    "positive_cases": sum(expected == "BOT" for expected, _, _ in SYNTHETIC_DEVICE_CASES),
    "negative_cases": sum(expected != "BOT" for expected, _, _ in SYNTHETIC_DEVICE_CASES),
    "passed": len(SYNTHETIC_DEVICE_CASES),
    "fixture_fingerprint": hashlib.sha256(
        json.dumps(SYNTHETIC_DEVICE_CASES, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest(),
}


def _finger(x, y, radius=(36.4, 36.4), force=0.0, spread=0.0, steps=(6, 14, 26, 38, 40, 30, 18, 8, 3)):
    """A thumb flick: accelerates, slows, drifts sideways; contact as the device reports it."""
    points, t = [[0.0, x, y, radius[0], radius[1], force]], 0.0
    for i, step in enumerate(steps):
        t += 16.7
        x += 0.4 * i - 0.6
        y -= step
        points.append([round(t, 1), round(x, 1), round(y, 1), round(radius[0] + spread * i, 1),
                       round(radius[1] + spread * i, 1), round(max(0.0, force - spread * i / 100), 2)])
    return points


def _tap(x, y, ms=84.0, radius=(36.4, 36.4), force=0.0):
    return [[0.0, x, y, radius[0], radius[1], force], [ms, x + 0.5, y, radius[0], radius[1], force]]


def _phone(ua, platform, renderer, gestures, touch_points=5, memory=None, cores=None, times=None, **kwargs):
    fingerprint = {"platform": platform, "maxTouchPoints": touch_points,
                   **({"deviceMemory": memory} if memory is not None else {}),
                   **({"hardwareConcurrency": cores} if cores is not None else {})}
    payload = _automation(browser_ua=ua, http_ua=ua, renderer=renderer, fingerprint=fingerprint, **kwargs)
    times = times or [1000 * i for i in range(len(gestures))]
    payload["mouse"]["touch"] = {"gestures": [{"t0": t, "points": g} for t, g in zip(times, gestures)],
                                 "total": len(gestures), "viewport": [390, 763], "dpr": 3}
    return payload


_IPAD_DESKTOP = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
                 "Version/26.6 Safari/605.1.15")
_MAC_CHROME = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/155.0.0.0 Safari/537.36")
_EMULATOR_GPU = "Android Emulator OpenGL ES Translator (Google SwiftShader)"
_IOS_HAND = [_finger(150 + 9 * i, 620) for i in range(4)] + [_tap(180, 324), _tap(210, 500, 97)]
_ANDROID_HAND = [_finger(140 + 7 * i, 640, radius=(11.5, 10.0), force=0.42, spread=0.3) for i in range(4)] + [
    _tap(180, 324, radius=(10.9, 9.8), force=0.38)]
_CDP_SWIPE = [[i * 2.0, 200.0 + i, 700.0 - i * 50.0, 1, 1, 1] for i in range(11)]
_RULER_SWIPE = [[i * 16.0, 200.0, 700.0 - i * 40.0, 11.5, 10.0, 0.4] for i in range(9)]

# Frozen gate of policy 18 (its fixtures expected every non-HUMAN, non-BOT phone
# to stay insufficient; policy 19 makes phones with evidence against them final).
MOBILE_HUMAN_RULE_GATE_V18 = {
    "rules": ["mobile_clean_environment_v1"],
    "positive_cases": 3, "negative_cases": 9, "passed": 12,
    "fixture_fingerprint": "d08211f325c91c775f97278a7135a6d2c4d5c8ad0399efeb7cde6a843ae22c17",
}

_IOS18 = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_7_8 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
          "GSA/443.5.99 Mobile/15E148 Safari/604.1")
_IOS16 = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_7_10 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
          "Version/16.6 Mobile/15E148 Safari/604.1")
_ANDROID10 = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/156.0.0.0 Mobile Safari/537.36")
_ADRENO = "ANGLE (Qualcomm, Adreno (TM) 610, OpenGL ES 3.2)"
_HOST_GPU = "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)"
# A low-end Android phone on the live site (2026-10-27): no pressure or size sensor.
_LOW_END_HAND = [
    [[0.0, 114.5, 413.0, 0.3, 0.3, 1.0], [47.0, 113.5, 422.0, 0.3, 0.3, 1.0], [60.0, 115.5, 446.5, 0.3, 0.3, 1.0],
     [165.0, 111.5, 575.0, 0.3, 0.3, 1.0], [165.3, 111.5, 575.0, 0.3, 0.3, 0.0]],
    [[0.0, 110.5, 372.5, 0.3, 0.3, 1.0], [40.7, 111.5, 381.0, 0.3, 0.3, 1.0], [58.3, 113.5, 397.0, 0.3, 0.3, 1.0],
     [163.8, 121.0, 497.0, 0.3, 0.3, 1.0], [164.0, 121.0, 497.0, 0.3, 0.3, 0.0]],
    [[0.0, 96.5, 297.5, 0.3, 0.3, 1.0], [27.1, 99.5, 308.5, 0.3, 0.3, 1.0], [43.0, 106.0, 328.0, 0.3, 0.3, 1.0],
     [147.0, 130.0, 469.5, 0.3, 0.3, 1.0], [147.4, 130.0, 469.5, 0.3, 0.3, 0.0]],
]
_NO_CONTACT_HAND = [[[p[0], p[1], p[2], None, None, None] for p in g] for g in _IOS_HAND]
_SAME_BUTTON = [_tap(180 + dx, 324 + dy, ms) for dx, dy, ms in
                ((0, 0, 84), (2, -1, 61), (-1, 2, 95), (1, 1, 72), (-2, 0, 88), (0, -2, 66))]
_SAME_BUTTON_TIMES = [1000, 1650, 2480, 3010, 3920, 4410]
_AUTOCLICK = [_tap(180, 324, 40, radius=(0.3, 0.3), force=1.0) for _ in range(6)] + _ANDROID_HAND[:3]
_REPLAY = [_finger(150, 640, radius=(11.5, 10.0), force=0.42, spread=0.3)] * 3 + _ANDROID_HAND[4:]
_SPOOFED = {"platformMismatch": True}
_PATCHED = {"navigatorGetterPatched": True}

# Policy 19 fixtures: (verdict, decision state, decision basis, payload).
# Contact values of real phones measured on the live site (2026-10-27): iPhone
# force 0 with radius 24.3/36.4/48.6; a low-end Android radius 0.3, force 1,
# release 0. Stealth bots measured the same day: Playwright WebKit (iPhone, iPad)
# and Chromium (Pixel 7) with navigator.platform/webdriver/maxTouchPoints patched
# and CDP touches with finger-like contact.
MOBILE_RULE_CASES = (
    # People: iPhone (old and current UA), Android flagship and low-end, iPad in
    # desktop mode, iOS 16 without contact radius (not judged), and someone tapping
    # one button six times (the finger never lands twice on the same point).
    ("HUMAN", "FINAL", "mobile_clean_environment", _phone(_IPHONE, "iPhone", "Apple GPU", _IOS_HAND)),
    ("HUMAN", "FINAL", "mobile_clean_environment", _phone(_IOS18, "iPhone", "Apple GPU", _IOS_HAND)),
    ("HUMAN", "FINAL", "mobile_clean_environment", _phone(_PIXEL, "Linux aarch64", "Mali-G710", _ANDROID_HAND, memory=8)),
    ("HUMAN", "FINAL", "mobile_clean_environment", _phone(_ANDROID10, "Linux armv81", _ADRENO, _LOW_END_HAND,
                                                          memory=4, cores=8)),
    ("HUMAN", "FINAL", "mobile_clean_environment", _phone(_IPAD_DESKTOP, "MacIntel", "Apple GPU", _IOS_HAND)),
    ("HUMAN", "FINAL", "mobile_clean_environment", _phone(_IOS16, "iPhone", "Apple GPU", _NO_CONTACT_HAND)),
    ("HUMAN", "FINAL", "mobile_clean_environment", _phone(_IOS18, "iPhone", "Apple GPU", _SAME_BUTTON,
                                                          times=_SAME_BUTTON_TIMES)),
    # Not enough to judge.
    ("SUSPECT", "INSUFFICIENT_EVIDENCE", None, _phone(_IPHONE, "iPhone", "Apple GPU", _IOS_HAND[:2])),
    ("SUSPECT", "INSUFFICIENT_EVIDENCE", None, _phone(None, "Win32", _D3D, _ANDROID_HAND, touch_points=10)),
    ("SUSPECT", "INSUFFICIENT_EVIDENCE", None, _phone(_MAC_CHROME, "MacIntel", "Apple GPU", _IOS_HAND)),
    # Judged, with evidence against: CDP contact, ruler swipes, replayed swipes,
    # emulators (Android Studio, a host GPU as in LDPlayer/BlueStacks), a cloud
    # address, a server CPU.
    ("SUSPECT", "FINAL", "mobile_risk", _phone(_PIXEL, "Linux aarch64", "Mali-G710", [_CDP_SWIPE] * 4, memory=8)),
    ("SUSPECT", "FINAL", "mobile_risk", _phone(_PIXEL, "Linux aarch64", "Mali-G710",
                                               [_RULER_SWIPE] * 3 + _ANDROID_HAND, memory=8)),
    ("SUSPECT", "FINAL", "mobile_risk", _phone(_PIXEL, "Linux aarch64", "Mali-G710", _REPLAY, memory=8)),
    ("SUSPECT", "FINAL", "mobile_risk", _phone(_PIXEL, "Linux x86_64", _EMULATOR_GPU, _ANDROID_HAND,
                                               touch_points=10, memory=2)),
    ("SUSPECT", "FINAL", "mobile_risk", _phone(_ANDROID10, "Linux armv81", _HOST_GPU, _ANDROID_HAND, memory=8)),
    ("SUSPECT", "FINAL", "mobile_risk", _phone(_IPHONE, "iPhone", "Apple GPU", _IOS_HAND, datacenter="gcp")),
    ("SUSPECT", "FINAL", "mobile_risk", _phone(_ANDROID10, "Linux armv81", _ADRENO, _ANDROID_HAND, cores=49)),
    # Bots: desktop emulation, stealth WebKit iPhone and Chromium Pixel (platform
    # patched; the worker keeps the real one), an autoclicker, a webdriver flag.
    ("BOT", "FINAL", "mobile_emulation", _phone(_IPHONE, "Win32", _D3D, _IOS_HAND, touch_points=1, memory=16)),
    ("BOT", "FINAL", "mobile_emulation", _phone(_IOS18, "iPhone", "Apple GPU", _NO_CONTACT_HAND, cores=8,
                                                worker=_SPOOFED, signals=_PATCHED)),
    ("BOT", "FINAL", "mobile_emulation", _phone(_PIXEL, "Linux armv81", _D3D, _ANDROID_HAND, memory=8,
                                                worker=_SPOOFED, signals=_PATCHED)),
    ("BOT", "FINAL", "touch_automation", _phone(_ANDROID10, "Linux armv81", _ADRENO, _AUTOCLICK, memory=4,
                                                times=[1000 + 500 * i for i in range(9)])),
    ("BOT", "FINAL", "automation_marker", _phone(_PIXEL, "Linux aarch64", "Mali-G710", _ANDROID_HAND, memory=8,
                                                 detectors={"webdriver": True})),
    # Policy 24: a phone page the gateway served stays human; telemetry without one, or a
    # device starting sessions non-stop, is judged with evidence against it.
    ("HUMAN", "FINAL", "mobile_clean_environment", _phone(_IOS18, "iPhone", "Apple GPU", _IOS_HAND,
                                                          headers={"page_view": "verified", "device_sessions": 2})),
    ("SUSPECT", "FINAL", "mobile_risk", _phone(_IOS18, "iPhone", "Apple GPU", _IOS_HAND,
                                               headers={"page_view": "missing"})),
    ("SUSPECT", "FINAL", "mobile_risk", _phone(_ANDROID10, "Linux armv81", _ADRENO, _LOW_END_HAND, memory=4, cores=8,
                                               headers={"page_view": "verified", "device_sessions": 40})),
)

# Frozen gate of policies 19-23.
MOBILE_RULE_GATE_V19 = {
    "rules": ["mobile_clean_environment_v1", "mobile_risk_v1", "autoclick_taps_v1", "mobile_emulation_v1"],
    "human_cases": 7, "suspect_cases": 10, "bot_cases": 5, "passed": 22,
    "fixture_fingerprint": "ab08fe3f334ac3dfa9b1f68431917fee4347a810d1932f4dd7fc1353ff4a8027",
}

MOBILE_RULE_GATE = {
    "rules": ["mobile_clean_environment_v1", "mobile_risk_v1", "autoclick_taps_v1", "mobile_emulation_v1"],
    "human_cases": sum(verdict == "HUMAN" for verdict, _, _, _ in MOBILE_RULE_CASES),
    "suspect_cases": sum(verdict == "SUSPECT" for verdict, _, _, _ in MOBILE_RULE_CASES),
    "bot_cases": sum(verdict == "BOT" for verdict, _, _, _ in MOBILE_RULE_CASES),
    "passed": len(MOBILE_RULE_CASES),
    "fixture_fingerprint": hashlib.sha256(
        json.dumps(MOBILE_RULE_CASES, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest(),
}


with open(os.path.join(os.path.dirname(__file__), "fixtures", "m4d_human_60hz.json"), encoding="utf-8") as _fixture:
    _M4D_60HZ = json.load(_fixture)["points_t_x_y"]


def _path(scale=1.0, burst=0):
    """A human path (M4D, 60 Hz frames); ``scale`` stretches time, ``burst`` adds moves within 1 ms."""
    records = []
    for t, x, y in _M4D_60HZ:
        records.append({"time": round(t * scale), "x": x, "y": y, "type": "move", "source": "mouse"})
        records += [{"time": round(t * scale) + k % 2, "x": round(x + 0.4 * (k + 1), 1), "y": y, "type": "move",
                     "source": "mouse"} for k in range(burst)]
    return records[-100:]


def _desktop(coalesced=1.9, multi=0.8, secure=True, frame_ms=16.7, path=None, ua=None, renderer=_D3D,
             stats=None, **kwargs):
    payload = _automation(browser_ua=ua, http_ua=ua, renderer=renderer, **kwargs)
    payload["mouse"]["records"] = path or _path()
    payload["mouse"]["pointerStats"] = {
        "pointermove": 600, "coalescedTotal": round(600 * coalesced), "coalescedMax": 4,
        "coalescedMulti": round(600 * multi), "rawUpdates": round(600 * coalesced), "secureContext": secure,
        "frameMs": frame_ms, "frames": 60, **(stats or {})}
    return payload


_LINUX_CHROME = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                 "Chrome/155.0.0.0 Safari/537.36")
_WINDOWS_FIREFOX = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:158.0) Gecko/20100101 Firefox/158.0"
_APPLE_M2 = "ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)"
_MESA = "ANGLE (Intel, Mesa Intel(R) Iris(R) Xe Graphics (ADL GT2), OpenGL 4.6)"
_APPLE_M4 = "ANGLE (Apple, ANGLE Metal Renderer: Apple M4, Unspecified Version)"
_COCCOC = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
           "coc_coc_browser/150.0.0 Chrome/144.0.0.0 Safari/537.36")

# Policy 21 fixtures: (verdict, risk codes, payload). One human path throughout, so the
# mouse models call every case human and only the input or environment differs.
# Measured 2026-10-27: Windows people on the live site 1.88-2.29 coalesced samples per
# move; a Linux person 1.02; patchright/Puppeteer CDP moves 1.000-1.002; CDP moves fired
# without waiting 4 ms apart (1.07); fired in parallel, 0.3 ms apart.
DESKTOP_RISK_CASES = (
    ("HUMAN", [], _desktop()),
    ("HUMAN", [], _desktop(coalesced=1.02, multi=0.007, ua=_LINUX_CHROME, renderer=_MESA)),
    ("HUMAN", [], _desktop(coalesced=1.0, multi=0.0, ua=_MAC_CHROME, renderer=_APPLE_M2)),
    ("HUMAN", [], _desktop(coalesced=1.0, multi=0.0, frame_ms=6.9)),
    ("HUMAN", [], _desktop(coalesced=0.0, multi=0.0, secure=False)),
    ("HUMAN", [], _desktop(coalesced=1.0, multi=0.0, ua=_WINDOWS_FIREFOX)),
    ("HUMAN", [], _desktop(datacenter="aws")),
    ("HUMAN", [], _desktop(signals={"uaHintsMismatch": True})),
    ("SUSPECT", ["FRAME_LOCKED_POINTER"], _desktop(coalesced=1.0, multi=0.002)),
    ("SUSPECT", ["FRAME_LOCKED_POINTER"], _desktop(coalesced=1.0, multi=0.0, ua=_MAC_CHROME)),
    ("SUSPECT", ["UNALIGNED_POINTER"], _desktop(coalesced=1.07, multi=0.07, path=_path(scale=0.24))),
    ("SUSPECT", ["SUBFRAME_POINTER_BURST"], _desktop(coalesced=3.4, multi=0.8, path=_path(burst=3))),
    ("SUSPECT", ["CLOUD_SOFTWARE_GPU"], _desktop(renderer=_SWIFTSHADER, datacenter="gcp")),
    ("SUSPECT", ["ENVIRONMENT_EVIDENCE"], _desktop(signals={"headlessScreen": True})),
    # Policy 23 (2026-10-28): a MacBook M4 on the live site (3.56 samples, Chrome energy
    # saver at 30 frames per second), Cốc Cốc moved by OS input (2.52); a script that
    # made getCoalescedEvents return the event itself, one that deleted it, a page that
    # reports a rewritten timing API, and a script stepping every 130 ms.
    ("HUMAN", [], _desktop(coalesced=3.56, multi=0.91, frame_ms=33.3, ua=_MAC_CHROME, renderer=_APPLE_M4)),
    ("HUMAN", [], _desktop(coalesced=2.52, multi=0.75, ua=_COCCOC)),
    ("SUSPECT", ["POINTER_API_TAMPERED"], _desktop(coalesced=0.002, multi=0.0, stats={"coalescedSelf": 968})),
    ("SUSPECT", ["POINTER_API_TAMPERED"], _desktop(coalesced=0.0, multi=0.0)),
    ("SUSPECT", ["POINTER_API_TAMPERED"], _desktop(signals={"inputApiPatched": True})),
    ("SUSPECT", ["FRAME_LOCKED_POINTER"], _desktop(coalesced=1.004, multi=0.004, path=_path(scale=7.8))),
    # A human-looking payload posted by a script (no Accept-Language), and one posted
    # over HTTPS without the Sec-Fetch headers every Chromium request carries.
    ("SUSPECT", ["NON_BROWSER_REQUEST"], _desktop(accept_language=False)),
    ("SUSPECT", ["NON_BROWSER_REQUEST"], _desktop(headers={"forwarded_proto": "https"})),
    ("HUMAN", [], _desktop(headers={"forwarded_proto": "https", "sec_fetch_site": "same-origin"})),
    # Policy 24: telemetry from the shop host without the cookie of a page the gateway served,
    # or with one cookie presented by many sessions; one device starting 45 sessions an hour
    # on one address. A served page and a person's few tabs stay human.
    ("SUSPECT", ["UNVERIFIED_PAGE_LOAD"], _desktop(headers={"page_view": "missing"})),
    ("SUSPECT", ["UNVERIFIED_PAGE_LOAD"], _desktop(headers={"page_view": "reused"})),
    ("SUSPECT", ["DEVICE_VELOCITY"], _desktop(headers={"page_view": "verified", "device_sessions": 45})),
    ("HUMAN", [], _desktop(headers={"page_view": "verified", "device_sessions": 4})),
    ("HUMAN", [], _desktop(headers={"page_view": "untracked"})),
    # A page with the CDP Runtime enabled and nothing else: a CDP client, or DevTools open.
    ("SUSPECT", ["CDP_ATTACHED"], _desktop(signals={"cdpRuntime": True})),
)

# Frozen gate of policy 23.
DESKTOP_RISK_RULE_GATE_V23 = {
    "rules": ["desktop_risk_v1"], "human_cases": 11, "suspect_cases": 12, "passed": 23,
    "fixture_fingerprint": "3c825a230812817f4db3557f5f35b04058f3ebc7529589b4ae516594436ede6c",
}

# Frozen gate of policies 21-22.
DESKTOP_RISK_RULE_GATE_V21 = {
    "rules": ["desktop_risk_v1"], "human_cases": 8, "suspect_cases": 6, "passed": 14,
    "fixture_fingerprint": "b58fc60f607a53115701225fd70f8b607b11e5722d69081d7f72bef530782a9a",
}

DESKTOP_RISK_RULE_GATE = {
    "rules": ["desktop_risk_v1"],
    "human_cases": sum(verdict == "HUMAN" for verdict, _, _ in DESKTOP_RISK_CASES),
    "suspect_cases": sum(verdict == "SUSPECT" for verdict, _, _ in DESKTOP_RISK_CASES),
    "passed": len(DESKTOP_RISK_CASES),
    "fixture_fingerprint": hashlib.sha256(
        json.dumps(DESKTOP_RISK_CASES, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest(),
}
