"""Policy 12: framework-marker and environment-tampering rules."""

import pytest

from core_ml.features.automation_evidence import (
    AUTOMATION_MARKER_RULE,
    ENVIRONMENT_TAMPERING_RULE,
    analyze_automation_evidence,
)
from core_ml.models.ensemble import DECISION_POLICY_VERSION, EnsembleBotDetector
from core_ml.release_cases import AUTOMATION_EVIDENCE_CASES, _automation

HEADLESS = "Mozilla/5.0 Chrome/154.0.0.0 HeadlessChrome/154.0.0.0"


class FixedLSTM:
    def predict_session_scores(self, chunks):
        return 0.05, 0.05


class FixedTabular:
    def predict_proba(self, vector):
        return 0.02


def predict(payload):
    return EnsembleBotDetector(lstm_model=FixedLSTM(), tabular_model=FixedTabular()).predict(payload)


@pytest.mark.parametrize("expected, basis, payload", AUTOMATION_EVIDENCE_CASES)
def test_release_fixtures(expected, basis, payload):
    result = predict(payload)
    assert result["verdict"] == expected
    assert result["policy_version"] == DECISION_POLICY_VERSION
    if basis:
        assert result["breakdown"]["decision_basis"] == basis
        assert result["breakdown"]["risk_score_in_domain"] is False


@pytest.mark.parametrize("detector", ["webdriver", "chromeDriverGlobal", "distinctiveProperties", "documentKeys"])
def test_each_legacy_framework_detector_is_a_marker(detector):
    report = analyze_automation_evidence({"botd": {"detectors": {detector: True}}})
    assert report["rule"] == AUTOMATION_MARKER_RULE
    assert report["markers"] == [f"detectors.{detector}"]


def test_markers_apply_to_collectors_without_the_new_probes():
    report = analyze_automation_evidence({"botd": {"detectors": {"webdriver": True}}})
    assert report["probes_present"] is False and report["rule"] == AUTOMATION_MARKER_RULE


def test_tampering_needs_three_families_including_an_anchor():
    two = _automation(signals={"gpuOsMismatch": True}, worker={"cpuMismatch": True})
    assert analyze_automation_evidence(two)["rule"] is None
    three = _automation(signals={"gpuOsMismatch": True}, worker={"cpuMismatch": True}, permission=True)
    assert analyze_automation_evidence(three)["rule"] == ENVIRONMENT_TAMPERING_RULE
    no_anchor = _automation(signals={"uaHintsMismatch": True, "toStringPatched": True},
                            worker={"uaMismatch": True}, accept_language=False)
    report = analyze_automation_evidence(no_anchor)
    assert report["family_count"] == 4 and report["rule"] is None


def test_two_signals_in_one_family_count_once():
    payload = _automation(signals={"gpuOsMismatch": True}, worker={"rendererMismatch": True}, permission=True)
    report = analyze_automation_evidence(payload)
    assert set(report["families"]) == {"GPU", "PERMISSION"}
    assert report["rule"] is None


def test_server_header_evidence():
    payload = _automation(accept_language=False)
    assert analyze_automation_evidence(payload)["families"] == {"HTTP": ["server.missing_accept_language"]}
    unobserved = _automation()
    unobserved["_server_headers"] = {}
    assert analyze_automation_evidence(unobserved)["families"] == {}
    mismatch = _automation(http_ua="curl/8.0")
    assert "CLIENT_HINTS" in analyze_automation_evidence(mismatch)["families"]
    trimmed = _automation(browser_ua="mobile", http_ua="Mozilla/5.0 (Linux; Android 14) Chrome/155 Mobile")
    assert analyze_automation_evidence(trimmed)["families"] == {}


def test_wrong_schema_is_ignored():
    payload = _automation(signals={"playwrightGlobals": True})
    payload["botd"]["automation"]["schema"] = "other"
    assert analyze_automation_evidence(payload)["rule"] is None


def test_headless_rule_keeps_precedence_and_marker_beats_synthetic_clicks():
    headless = {"_server_user_agent": HEADLESS, "fingerprint": {"userAgent": HEADLESS},
                "botd": {"detectors": {"webdriver": True}}, "mouse": {"records": []}}
    assert predict(headless)["breakdown"]["decision_basis"] == "explicit_automation"
    clicks = [{"ox": 0, "oy": 0, "w": 80, "h": 24, "hold": 0.1}] * 3
    marker = _automation(detectors={"webdriver": True})
    marker["mouse"]["clickEvents"] = clicks
    assert predict(marker)["breakdown"]["decision_basis"] == "automation_marker"
    clean = _automation()
    clean["mouse"]["clickEvents"] = clicks
    assert predict(clean)["breakdown"]["decision_basis"] == "synthetic_input"


def test_reason_names_the_evidence():
    stealth = AUTOMATION_EVIDENCE_CASES[3][2]
    reasons = predict(stealth)["reasons"]
    assert any("GPU" in r and "PERMISSION" in r for r in reasons)
    marker = predict(_automation(signals={"seleniumGlobals": True}))["reasons"]
    assert any("signals.seleniumGlobals" in r for r in marker)


def test_https_fetch_metadata_and_client_hint_headers():
    https = _automation()
    https["_server_headers"].update({"forwarded_proto": "https", "sec_fetch_site": "same-origin"})
    assert analyze_automation_evidence(https)["families"] == {}
    https["_server_headers"]["sec_fetch_site"] = ""
    assert analyze_automation_evidence(https)["families"] == {"HTTP": ["server.missing_fetch_metadata"]}
    plain_http = _automation()
    plain_http["_server_headers"].update({"forwarded_proto": "http", "sec_fetch_site": ""})
    assert analyze_automation_evidence(plain_http)["families"] == {}
    hinted = _automation()
    hinted["_server_headers"]["sec_ch_ua"] = '"HeadlessChrome";v="155", "Chromium";v="155"'
    assert analyze_automation_evidence(hinted)["families"] == {"HEADLESS_ENV": ["server.headless_client_hints_header"]}


def test_permission_family_only_applies_to_chromium():
    firefox = "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:158.0) Gecko/20100101 Firefox/158.0"
    payload = _automation(browser_ua=firefox, http_ua=firefox, permission=True)
    assert analyze_automation_evidence(payload)["families"] == {}
    assert "PERMISSION" in analyze_automation_evidence(_automation(permission=True))["families"]


@pytest.mark.parametrize("renderer, flagged", [
    ("ANGLE (Intel(R) HD Graphics Direct3D11 vs_5_0 ps_5_0)", True),
    ("ANGLE (Intel, Intel(R) Iris(R) Xe Graphics (0x00009A49) Direct3D11 vs_5_0 ps_5_0, D3D11)", False),
    ("ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)", False),
    ("Mesa Intel(R) UHD Graphics 620 (KBL GT2)", False),
])
def test_legacy_angle_renderer_is_gpu_evidence(renderer, flagged):
    families = analyze_automation_evidence(_automation(renderer=renderer))["families"]
    assert (families == {"GPU": ["server.legacy_angle_renderer"]}) == flagged


def test_legacy_angle_needs_a_modern_chrome_claim():
    old = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/90.0.0.0"
    payload = _automation(browser_ua=old, http_ua=old, renderer="ANGLE (Intel(R) HD Graphics Direct3D11 vs_5_0 ps_5_0)")
    assert analyze_automation_evidence(payload)["families"] == {}


def test_evidence_families_survive_bson_sanitising():
    from api_service.database import _sanitize_bson_value

    result = predict(AUTOMATION_EVIDENCE_CASES[3][2])
    stored = _sanitize_bson_value({"result": result})
    families = stored["result"]["breakdown"]["automation_evidence"]["families"]
    assert families and all(isinstance(v, str) for values in families.values() for v in values)


@pytest.mark.parametrize("renderer, software", [
    ("ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (LLVM 10.0.0) (0x0000C0DE)), SwiftShader driver)", True),
    ("llvmpipe (LLVM 15.0.7, 256 bits)", True),
    ("Microsoft Basic Render Driver", True),
    ("VirtualBox Graphics Adapter", False),
    ("ANGLE (VMware, Inc., SVGA3D, D3D11)", False),
    ("ANGLE (Intel, Intel(R) Iris(R) Xe Graphics (0x00009A49) Direct3D11 vs_5_0 ps_5_0, D3D11)", False),
])
def test_software_renderer_is_gpu_evidence_but_hypervisors_are_not(renderer, software):
    families = analyze_automation_evidence(_automation(renderer=renderer))["families"]
    assert ("server.software_renderer" in families.get("GPU", [])) == software


def test_datacenter_address_corroborates_but_never_anchors():
    alone = analyze_automation_evidence(_automation(datacenter="aws"))
    assert alone["families"] == {"NETWORK": ["server.datacenter_ip"]} and alone["rule"] is None
    no_anchor = _automation(signals={"uaHintsMismatch": True, "toStringPatched": True}, datacenter="gcp")
    assert analyze_automation_evidence(no_anchor)["rule"] is None
    # On a cloud address the CPU rasteriser and zero RTT are what the VM explains.
    vm = analyze_automation_evidence(_automation(renderer="SwiftShader", signals={"rttZero": True}, datacenter="gcp"))
    assert vm["families"] == {"NETWORK": ["server.datacenter_ip", "server.software_renderer", "signals.rttZero"]}
    assert vm["cloud_vm"] is True and vm["rule"] is None
    idle = _automation(renderer="SwiftShader", signals={"rttZero": True}, datacenter="gcp", page_ms=14000)
    assert analyze_automation_evidence(idle)["rule"] == "idle_cloud_browser_v1"
    used = _automation(renderer="SwiftShader", signals={"rttZero": True}, datacenter="gcp", page_ms=14000, active=True)
    assert analyze_automation_evidence(used)["rule"] is None
    # Away from the cloud the same signals keep counting on their own.
    home = analyze_automation_evidence(_automation(renderer="SwiftShader", signals={"rttZero": True}))
    assert set(home["families"]) == {"GPU", "HEADLESS_ENV"}


@pytest.mark.parametrize("ua, declared", [
    ("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", True),
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)", True),
    ("Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/155.0 Safari/537.36 Chrome-Lighthouse", True),
    ("Mozilla/5.0 (Linux; Android 10; Cubot X30) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36", False),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0 Safari/537.36", False),
])
def test_declared_bot_user_agents(ua, declared):
    report = analyze_automation_evidence(_automation(browser_ua=ua, http_ua=ua))
    assert ("server.declared_bot_ua" in report["markers"]) == declared


def test_web_bot_auth_signature_is_a_marker():
    assert analyze_automation_evidence(_automation(headers={"signature_agent": True}))["markers"] == ["server.signature_agent"]
    assert analyze_automation_evidence(_automation(headers={"signature_agent": False}))["markers"] == []


def test_phone_emulation_needs_a_platform_contradiction():
    iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"
    d3d = "ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)"
    devtools = _automation(browser_ua=iphone, http_ua=iphone, renderer=d3d,
                           fingerprint={"platform": "iPhone", "deviceMemory": 8, "maxTouchPoints": 1})
    report = analyze_automation_evidence(devtools)
    assert report["mobile_emulation"] == ["desktop_gpu", "chromium_api_on_ios"] and report["rule"] is None
    only_platform = _automation(browser_ua=iphone, http_ua=iphone, renderer="Apple GPU",
                                fingerprint={"platform": "Win32", "maxTouchPoints": 5})
    assert analyze_automation_evidence(only_platform)["rule"] is None
