"""Policy 47: an Android phone whose Chrome asks for desktop sites (X11 Linux x86_64 user agent, ARM
navigator.platform, touch screen, phone GPU) is judged as a phone (android_desktop_site), and its x86 Client
Hint, Chrome's own desktop override, is not an emulator."""

import copy
import hashlib
import json

from core_ml.features.mobile_human import android_desktop_site
from core_ml.features.presence import PRESENCE_VERSION, analyze_presence
from core_ml.release_cases import (
    MOBILE_RULE_CASES,
    MOBILE_RULE_CASES_V50,
    MOBILE_RULE_GATE,
    MOBILE_RULE_GATE_V46,
)

# The controlled test of 18 Nov 2026 (a Samsung with a Mali-G57): only the user agent changed.
DESKTOP_SITE = {
    "userAgent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/157.0.0.0 Safari/537.36"),
    "platform": "Linux armv81", "maxTouchPoints": 5, "webglRenderer": "ANGLE (ARM, Mali-G57, OpenGL ES 3.2)",
}


def test_recognises_a_phone_asking_for_desktop_sites():
    assert android_desktop_site(DESKTOP_SITE)
    for gpu in ("ANGLE (Qualcomm, Adreno (TM) 610, OpenGL ES 3.2)", "Xclipse 920", "PowerVR Rogue GE8320",
                "Immortalis-G715", "Mali-G52 MC2"):
        assert android_desktop_site({**DESKTOP_SITE, "webglRenderer": gpu}), gpu
    for platform in ("Linux armv8l", "Linux aarch64", "Linux armv7l"):
        assert android_desktop_site({**DESKTOP_SITE, "platform": platform}), platform
    samsung = DESKTOP_SITE["userAgent"].replace("Chrome/157.0.0.0", "SamsungBrowser/28.0 Chrome/130.0.0.0")
    assert android_desktop_site({**DESKTOP_SITE, "userAgent": samsung})


def test_a_desktop_is_not_one():
    for change in ({"platform": "Linux x86_64"}, {"maxTouchPoints": 0}, {"maxTouchPoints": 1},
                   {"maxTouchPoints": True}, {"webglRenderer": ""},
                   {"webglRenderer": "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)), SwiftShader driver)"},
                   {"webglRenderer": "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
                   {"userAgent": DESKTOP_SITE["userAgent"].replace("Safari/537.36", "Mobile Safari/537.36")},
                   {"userAgent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"},
                   {"userAgent": DESKTOP_SITE["userAgent"].replace("X11; Linux x86_64", "Windows NT 10.0; Win64; x64")},
                   {"userAgent": DESKTOP_SITE["userAgent"].replace("Chrome/157.0.0.0", "HeadlessChrome/157.0.0.0")}):
        assert not android_desktop_site({**DESKTOP_SITE, **change}), change
    assert not android_desktop_site({**DESKTOP_SITE, "platform": "Linux x86_64",
                                     "webglRenderer": "ANGLE (Intel, Mesa Intel(R) UHD Graphics 620 (KBL GT2), OpenGL 4.6)"})
    assert not android_desktop_site(None)


def test_chrome_desktop_hints_are_not_an_emulator():
    payload = {"botd": {"profile": {"main": {"clientHints": {"architecture": "x86", "bitness": "64", "mobile": False,
                                                              "model": "", "platform": "Linux"}}}},
               "mouse": {"presence": {}}}
    assert "CH_EMULATOR" in analyze_presence(copy.deepcopy(payload), android=True)["codes"]
    report = analyze_presence(copy.deepcopy(payload), android=True, desktop_site=True)
    assert "CH_EMULATOR" not in report["codes"] and "CH_DESKTOP_HINTS" not in report["research_flags"]
    payload["botd"]["profile"]["main"]["clientHints"]["model"] = "sdk_gphone64_arm64"
    assert "CH_EMULATOR" in analyze_presence(payload, android=True, desktop_site=True)["codes"]
    assert PRESENCE_VERSION == "presence_v6"


def test_fixtures():
    from api_service.main import ensemble_detector
    ours = MOBILE_RULE_CASES[70:75]
    assert [(v, s, b) for v, s, b, _ in ours] == [
        ("HUMAN", "FINAL", "mobile_clean_environment"), ("HUMAN", "FINAL", "mobile_held_device"),
        ("SUSPECT", "FINAL", "mobile_risk"), ("SUSPECT", "FINAL", "client_forgery"),
        ("SUSPECT", "INSUFFICIENT_EVIDENCE", None)]
    touched = ensemble_detector.predict(copy.deepcopy(ours[0][3]))
    assert touched["breakdown"]["mobile_human"]["device"] == "android_desktop_site"
    assert touched["breakdown"]["unsupported_mobile"] is True
    held = ensemble_detector.predict(copy.deepcopy(ours[1][3]))
    assert "CH_EMULATOR" not in held["breakdown"]["presence"]["codes"]
    assert "HELD_DEVICE" in held["breakdown"]["presence"]["research_flags"]
    laptop = ensemble_detector.predict(copy.deepcopy(ours[4][3]))
    assert laptop["breakdown"]["mobile_human"]["device"] is None


def test_policy_46_gate_is_frozen_on_its_own_fixtures():
    first = MOBILE_RULE_CASES_V50[:70]
    assert MOBILE_RULE_GATE_V46["fixture_fingerprint"] == hashlib.sha256(
        json.dumps(first, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    assert "android_desktop_site_v1" in MOBILE_RULE_GATE["rules"] and MOBILE_RULE_GATE["passed"] == 81


def test_policy_version():
    from core_ml.models.ensemble import DECISION_POLICY_VERSION
    assert DECISION_POLICY_VERSION in ("47", "48", "49", "50", "51", "52")
