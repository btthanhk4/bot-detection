"""Policy 46: a phone without a gyroscope counts as held in a hand from 50 motion events, with a stronger
tremor and a gravity vector that moves (mobile_held_device_v3)."""

import copy
import hashlib
import json

from core_ml.features.presence import (
    HELD_NO_GYRO_MIN_EVENTS,
    MOBILE_HELD_RULE,
    held_in_hand,
    no_gyroscope,
)
from core_ml.release_cases import (
    MOBILE_RULE_CASES,
    MOBILE_RULE_GATE,
    MOBILE_RULE_GATE_V45,
)

NO_GYRO = {"status": "ok", "events": 120, "tilt_deg": 34.0, "linear_sd": 0.08, "gravity_sd": 0.12,
           "rotation_mean": None, "rotation_sd": None}
GYRO = {"status": "ok", "events": 12, "tilt_deg": 38.0, "linear_sd": 0.09, "gravity_sd": 0.2,
        "rotation_mean": 0.9, "rotation_sd": 0.6}


def test_no_gyroscope_means_no_rotation_reading_at_all():
    assert no_gyroscope(NO_GYRO)
    assert not no_gyroscope(GYRO)
    assert not no_gyroscope({**NO_GYRO, "rotation_mean": 0.0}), "a gyroscope that reads zero is a gyroscope"
    assert not no_gyroscope({"status": "no_events"})


def test_held_without_a_gyroscope():
    assert HELD_NO_GYRO_MIN_EVENTS == 50 and MOBILE_HELD_RULE == "mobile_held_device_v3"
    assert held_in_hand(NO_GYRO)
    assert held_in_hand({**NO_GYRO, "events": 50})
    for change in ({"events": 49}, {"linear_sd": 0.029}, {"gravity_sd": 0.029}, {"gravity_sd": None},
                   {"tilt_deg": 9.9}, {"tilt_deg": 85.1}, {"status": "no_events"}):
        assert not held_in_hand({**NO_GYRO, **change}), change


def test_phones_with_a_gyroscope_keep_policy_44():
    assert held_in_hand(GYRO)
    assert held_in_hand({**GYRO, "events": 8})
    assert not held_in_hand({**GYRO, "events": 7})
    assert not held_in_hand({**GYRO, "rotation_sd": 0.1}), "a gyroscope that shows no turning"


def test_fixtures():
    from api_service.main import ensemble_detector
    ours = MOBILE_RULE_CASES[67:]
    assert [(v, s, b) for v, s, b, _ in ours] == [
        ("HUMAN", "FINAL", "mobile_held_device"), ("SUSPECT", "INSUFFICIENT_EVIDENCE", None),
        ("SUSPECT", "INSUFFICIENT_EVIDENCE", None)]
    held = ensemble_detector.predict(copy.deepcopy(ours[0][3]))
    assert held["breakdown"]["mobile_human"]["held_rule"] == "mobile_held_device_v3"
    assert held["breakdown"]["verdict_locked"] is False


def test_policy_45_gate_is_frozen_on_its_own_fixtures():
    first = MOBILE_RULE_CASES[:67]
    assert MOBILE_RULE_GATE_V45["fixture_fingerprint"] == hashlib.sha256(
        json.dumps(first, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    assert "mobile_held_device_v3" in MOBILE_RULE_GATE["rules"] and MOBILE_RULE_GATE["passed"] == 70


def test_policy_version():
    from core_ml.models.ensemble import DECISION_POLICY_VERSION
    assert DECISION_POLICY_VERSION == "46"
