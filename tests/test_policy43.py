"""Policy 43: an untouched phone held in a hand is HUMAN; sensors that do not stream plus a novel audio
stack convict a phone."""

import copy

from core_ml.features.presence import (
    analyze_presence,
    held_in_hand,
    sensorless_phone_fires,
    sensors_unavailable,
)
from core_ml.release_cases import MOBILE_RULE_CASES

HAND = {"status": "ok", "events": 400, "tilt_deg": 41.0, "linear_sd": 0.21, "rotation_sd": 4.3}


def presence(visible_ms, events, gravity, status="ok"):
    return {"visible_ms": visible_ms, "motion": {"status": status, "events": events, "gravity": gravity}}


def test_sensors_unavailable():
    assert sensors_unavailable(presence(40000, 1, 0.0))
    assert sensors_unavailable(presence(10000, 5, None))
    assert not sensors_unavailable(presence(9999, 1, 0.0)), "a page seen only briefly"
    assert not sensors_unavailable(presence(40000, 6, 0.0))
    assert not sensors_unavailable(presence(40000, 1, 9.8)), "a real reading"
    assert not sensors_unavailable(presence(40000, 0, None, status="no_events"))


def test_held_in_hand_needs_tilt_tremor_rotation_and_events():
    assert held_in_hand(HAND)
    for change in ({"rotation_sd": 0.05}, {"rotation_sd": None}, {"tilt_deg": 2.3}, {"tilt_deg": 88},
                   {"linear_sd": 0.01}, {"events": 7}, {"status": "no_events"}):
        assert not held_in_hand({**HAND, **change}), change


def test_rule_needs_both_channels():
    assert sensorless_phone_fires(["SENSORS_UNAVAILABLE"], ["AUDIO_NOVEL"])
    assert not sensorless_phone_fires(["SENSORS_UNAVAILABLE"], ["TIMEZONE_MISMATCH"])
    assert not sensorless_phone_fires([], ["AUDIO_NOVEL"])


def test_sensorless_flag_is_android_only():
    payload = {"mouse": {"presence": {"firstVisibleMs": 0, "visibleMs": 40000,
                                      "motion": {"status": "ok", "events": 1, "gravity": 0.0}}}}
    assert "SENSORS_UNAVAILABLE" in analyze_presence(copy.deepcopy(payload), android=True)["research_flags"]
    assert "SENSORS_UNAVAILABLE" not in analyze_presence(copy.deepcopy(payload), android=False)["research_flags"]


def test_fixtures():
    from api_service.main import ensemble_detector
    ours = MOBILE_RULE_CASES[55:64]
    assert [(v, s, b) for v, s, b, _ in ours] == [
        ("HUMAN", "FINAL", "mobile_held_device"), ("SUSPECT", "INSUFFICIENT_EVIDENCE", None),
        ("SUSPECT", "FINAL", "mobile_risk"), ("SUSPECT", "INSUFFICIENT_EVIDENCE", None),
        ("BOT", "FINAL", "sensorless_phone"), ("BOT", "FINAL", "sensorless_phone"),
        ("SUSPECT", "FINAL", "mobile_risk"), ("HUMAN", "FINAL", "mobile_light_touch"),
        ("SUSPECT", "FINAL", "mobile_risk")]
    held = ensemble_detector.predict(copy.deepcopy(ours[0][3]))
    assert held["breakdown"]["verdict_locked"] is False, "later evidence can still change it"
    assert any("lowest confidence" in reason for reason in held["reasons"])
    bot = ensemble_detector.predict(copy.deepcopy(ours[4][3]))
    assert bot["breakdown"]["automation_rule"] == "sensorless_phone_v1" and bot["breakdown"]["verdict_locked"] is True


def test_policy_version():
    from core_ml.models.ensemble import DECISION_POLICY_VERSION
    assert DECISION_POLICY_VERSION in ("43", "44", "45")
