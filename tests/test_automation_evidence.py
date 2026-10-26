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
    assert result["policy_version"] == DECISION_POLICY_VERSION == "12"
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
