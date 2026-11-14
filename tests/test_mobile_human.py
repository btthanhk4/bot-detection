"""Phone verdicts: HUMAN for clean phones (policy 18), final SUSPECT for phones with
evidence against them, autoclick and stealth emulation as BOT (policy 19)."""

import copy

import pytest

from core_ml.features.automation_evidence import mobile_emulation_fires
from core_ml.features.mobile_human import (
    MOBILE_HUMAN_MIN_GESTURES,
    analyze_mobile_human,
)
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
    assert (gate["human_cases"], gate["suspect_cases"], gate["bot_cases"]) == (12, 24, 5)


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


def test_risk_no_longer_waits_for_three_gestures(detector):
    # Policy 33: an emulator is evidence against a phone however few its gestures.
    payload = _case(13)
    touch = payload["mouse"]["touch"]
    touch["gestures"], touch["total"] = touch["gestures"][:2], 2
    result = detector.predict(payload)
    assert (result["verdict"], result["decision_state"]) == ("SUSPECT", "FINAL")
    assert "EMULATOR" in result["breakdown"]["mobile_human"]["risk"]
    assert result["breakdown"]["decision_basis"] == "mobile_risk"


def test_unverified_page_alone_still_waits_with_few_gestures(detector):
    payload = _clean_iphone()
    payload["_server_headers"]["page_view"] = "missing"
    touch = payload["mouse"]["touch"]
    touch["gestures"], touch["total"] = [], 0
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
    assert detector.predict(payload)["breakdown"]["decision_basis"] == "mobile_clean_environment"
    touch["gestures"] = touch["gestures"][:MOBILE_HUMAN_MIN_GESTURES - 1]
    touch["total"] = MOBILE_HUMAN_MIN_GESTURES - 1
    # Policy 33: fewer than three real touches are a HUMAN of lower confidence.
    result = detector.predict(payload)
    assert result["verdict"] == "HUMAN" and result["breakdown"]["decision_basis"] == "mobile_light_touch"
    assert any("lower confidence" in reason for reason in result["reasons"])
    touch["gestures"], touch["total"] = [], 0
    assert detector.predict(payload)["decision_state"] == "INSUFFICIENT_EVIDENCE"


def test_light_touch_needs_real_contact_and_a_seen_page(detector):
    payload = _clean_iphone()
    touch = payload["mouse"]["touch"]
    touch["gestures"], touch["total"] = touch["gestures"][4:5], 1
    assert detector.predict(copy.deepcopy(payload))["breakdown"]["decision_basis"] == "mobile_light_touch"
    cdp = copy.deepcopy(payload)
    for point in cdp["mouse"]["touch"]["gestures"][0]["points"]:
        point[3:6] = [1, 1, 1]
    assert detector.predict(cdp)["verdict"] != "HUMAN", "CDP contact is not a finger"
    instant = copy.deepcopy(payload)
    gesture = instant["mouse"]["touch"]["gestures"][0]["points"]
    for point in gesture:
        point[0] = 0.0
    instant["mouse"]["touch"]["gestures"][0]["points"] = gesture[:1] + gesture[:1]
    assert detector.predict(instant)["verdict"] != "HUMAN", "a 0 ms tap is not a finger"
    unseen = copy.deepcopy(payload)
    unseen["mouse"]["presence"] = {"prerendered": True, "initialVisibility": "prerender", "firstVisibleMs": None,
                                   "visibleMs": 0, "firstTouchMs": None, "motion": {"status": "unsupported"}}
    result = detector.predict(unseen)
    assert result["decision_state"] == "INSUFFICIENT_EVIDENCE"
    assert "NOT_VIEWED" in result["breakdown"]["suspect_reason_codes"]


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
