"""Policy 18: phones with real finger input and a clean environment are HUMAN."""

import copy

import pytest

from core_ml.features.mobile_human import MOBILE_HUMAN_MIN_GESTURES, analyze_mobile_human
from core_ml.release_cases import MOBILE_HUMAN_CASES, MOBILE_HUMAN_RULE_GATE
from core_ml.train import validate_mobile_human_rules


@pytest.fixture(scope="module")
def detector():
    from api_service.main import ensemble_detector

    return ensemble_detector


def _clean_iphone():
    return copy.deepcopy(MOBILE_HUMAN_CASES[0][2])


@pytest.mark.parametrize("index", range(len(MOBILE_HUMAN_CASES)))
def test_release_fixtures(detector, index):
    expected, basis, payload = MOBILE_HUMAN_CASES[index]
    result = detector.predict(copy.deepcopy(payload))
    assert result["verdict"] == expected
    if basis:
        assert result["breakdown"]["decision_basis"] == basis
    assert result["decision_state"] == ("INSUFFICIENT_EVIDENCE" if expected == "SUSPECT" else "FINAL")


def test_release_gate_counts(detector):
    gate = validate_mobile_human_rules(detector)
    assert gate == MOBILE_HUMAN_RULE_GATE
    assert (gate["positive_cases"], gate["negative_cases"]) == (3, 9)


def test_phone_human_is_not_locked_and_has_no_mouse_risk(detector):
    result = detector.predict(_clean_iphone())
    breakdown = result["breakdown"]
    assert result["verdict"] == "HUMAN" and not result["is_bot"]
    assert breakdown["verdict_locked"] is False, "later bot evidence must still be able to change it"
    assert breakdown["risk_score_in_domain"] is False
    assert breakdown["mobile_human"]["device"] == "ios"
    assert any("touch behaviour itself is not scored" in reason for reason in result["reasons"])


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


def test_unavailable_models_never_produce_phone_human(detector, monkeypatch):
    monkeypatch.setattr(detector, "lstm_available", False)
    assert detector.predict(_clean_iphone())["verdict"] == "SUSPECT"


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
    payload = copy.deepcopy(MOBILE_HUMAN_CASES[1][2])
    touch = {"gestures_total": 5, "research_flags": []}
    assert analyze_mobile_human(payload, {}, touch, [])["eligible"]
    payload["fingerprint"]["platform"] = "Linux i686"
    assert analyze_mobile_human(payload, {}, touch, [])["missing"] == ["EMULATOR"]
