"""Phone verdicts: HUMAN for clean phones (policy 18), final SUSPECT for phones with
evidence against them, autoclick and stealth emulation as BOT (policy 19)."""

import copy

import pytest

from core_ml.features.automation_evidence import mobile_emulation_fires
from core_ml.features.mobile_human import MOBILE_HUMAN_MIN_GESTURES, analyze_mobile_human
from core_ml.release_cases import MOBILE_RULE_CASES, MOBILE_RULE_GATE
from core_ml.train import validate_mobile_rules


@pytest.fixture(scope="module")
def detector():
    from api_service.main import ensemble_detector

    return ensemble_detector


def _case(index):
    return copy.deepcopy(MOBILE_RULE_CASES[index][3])


def _clean_iphone():
    return _case(0)


@pytest.mark.parametrize("index", range(len(MOBILE_RULE_CASES)))
def test_release_fixtures(detector, index):
    verdict, state, basis, payload = MOBILE_RULE_CASES[index]
    result = detector.predict(copy.deepcopy(payload))
    assert (result["verdict"], result["decision_state"]) == (verdict, state)
    if basis:
        assert result["breakdown"]["decision_basis"] == basis


def test_release_gate_counts(detector):
    gate = validate_mobile_rules(detector)
    assert gate == MOBILE_RULE_GATE
    assert (gate["human_cases"], gate["suspect_cases"], gate["bot_cases"]) == (7, 10, 5)


def test_phone_human_is_not_locked_and_has_no_mouse_risk(detector):
    result = detector.predict(_clean_iphone())
    breakdown = result["breakdown"]
    assert result["verdict"] == "HUMAN" and not result["is_bot"]
    assert breakdown["verdict_locked"] is False, "later bot evidence must still be able to change it"
    assert breakdown["risk_score_in_domain"] is False
    assert breakdown["mobile_human"]["device"] == "ios"
    assert any("touch behaviour itself is not scored" in reason for reason in result["reasons"])


def test_phone_risk_is_final_but_not_locked(detector):
    result = detector.predict(_case(13))  # Android Studio emulator, enough gestures
    assert (result["verdict"], result["decision_state"]) == ("SUSPECT", "FINAL")
    assert result["breakdown"]["verdict_locked"] is False
    assert "MOBILE_RISK" in result["breakdown"]["suspect_reason_codes"]
    assert any("evidence against it: emulator" in reason for reason in result["reasons"])


def test_risk_needs_enough_gestures_to_be_judged(detector):
    payload = _case(13)
    touch = payload["mouse"]["touch"]
    touch["gestures"], touch["total"] = touch["gestures"][:2], 2
    result = detector.predict(payload)
    assert (result["verdict"], result["decision_state"]) == ("SUSPECT", "INSUFFICIENT_EVIDENCE")
    assert result["breakdown"]["mobile_human"]["risk"] == []


def test_autoclick_is_locked_bot(detector):
    result = detector.predict(_case(20))
    assert result["verdict"] == "BOT" and result["breakdown"]["verdict_locked"] is True
    assert result["breakdown"]["automation_rule"] == "autoclick_taps_v1"
    assert any("Autoclicker" in reason for reason in result["reasons"])


def test_gesture_threshold_is_inclusive(detector):
    payload = _clean_iphone()
    touch = payload["mouse"]["touch"]
    touch["gestures"] = touch["gestures"][:MOBILE_HUMAN_MIN_GESTURES]
    touch["total"] = MOBILE_HUMAN_MIN_GESTURES
    assert detector.predict(payload)["verdict"] == "HUMAN"
    touch["gestures"] = touch["gestures"][:MOBILE_HUMAN_MIN_GESTURES - 1]
    touch["total"] = MOBILE_HUMAN_MIN_GESTURES - 1
    assert detector.predict(payload)["verdict"] == "SUSPECT"


def test_page_without_touch_stays_insufficient(detector):
    payload = _clean_iphone()
    del payload["mouse"]["touch"]
    result = detector.predict(payload)
    assert result["verdict"] == "SUSPECT" and result["decision_state"] == "INSUFFICIENT_EVIDENCE"
    assert result["breakdown"]["mobile_human"]["missing"] == ["FEW_GESTURES"]


def test_unavailable_models_never_produce_phone_verdicts(detector, monkeypatch):
    monkeypatch.setattr(detector, "lstm_available", False)
    assert detector.predict(_clean_iphone())["decision_state"] == "INSUFFICIENT_EVIDENCE"
    assert detector.predict(_case(13))["decision_state"] == "INSUFFICIENT_EVIDENCE"


def test_one_tolerated_family_but_no_anchor():
    payload = _clean_iphone()
    touch = {"gestures_total": 5, "research_flags": []}
    assert analyze_mobile_human(payload, {"families": {"HTTP": ["server.missing_fetch_metadata"]}}, touch, [])["eligible"]
    for families in ({"GPU": ["x"]}, {"HEADLESS_ENV": ["x"]}, {"PERMISSION": ["x"]},
                     {"HTTP": ["x"], "CLIENT_HINTS": ["y"]}, {"NETWORK": ["server.datacenter_ip"]}):
        assert not analyze_mobile_human(payload, {"families": families}, touch, [])["eligible"], families
    assert not analyze_mobile_human(payload, {"markers": ["detectors.webdriver"]}, touch, [])["eligible"]
    assert not analyze_mobile_human(payload, {}, touch, ["Client-reported webdriver automation signal"])["eligible"]


def test_android_x86_platform_is_an_emulator():
    payload = _case(2)
    touch = {"gestures_total": 5, "research_flags": []}
    assert analyze_mobile_human(payload, {}, touch, [])["eligible"]
    payload["fingerprint"]["platform"] = "Linux i686"
    assert analyze_mobile_human(payload, {}, touch, [])["missing"] == ["EMULATOR"]


def test_mobile_emulation_needs_platform_and_hardware_evidence():
    assert mobile_emulation_fires(["platform_mismatch", "desktop_gpu"])
    assert mobile_emulation_fires(["spoofed_platform", "ios_touch_without_contact"])
    assert not mobile_emulation_fires(["platform_mismatch", "spoofed_platform"]), "one spoof, two views of it"
    assert not mobile_emulation_fires(["desktop_gpu", "server_cpu"]), "an emulator keeps the real platform"
    assert not mobile_emulation_fires(["spoofed_platform"])


def test_old_ios_without_contact_radius_is_not_judged(detector):
    result = detector.predict(_case(5))
    assert result["verdict"] == "HUMAN"
    assert "ios_touch_without_contact" not in result["breakdown"]["automation_evidence"]["mobile_emulation"]
