"""Policy 44: a phone held in a hand counts from 8 motion events (collector 1.16-1.17 often reported
only the first second of a short visit); the frozen policy-43 mobile gate still verifies its bundles."""

import copy
import hashlib
import json

from api_service import live
from core_ml.features.presence import HELD_MIN_EVENTS, MOBILE_HELD_RULE, held_in_hand
from core_ml.release_cases import (
    MOBILE_RULE_CASES,
    MOBILE_RULE_GATE_V43,
    MOBILE_RULE_GATE_V45,
)

GLANCE = {"status": "ok", "events": 12, "tilt_deg": 38.0, "linear_sd": 0.09, "rotation_sd": 0.6}


def test_held_from_eight_events():
    assert HELD_MIN_EVENTS == 8 and MOBILE_HELD_RULE in ("mobile_held_device_v2", "mobile_held_device_v3")
    assert held_in_hand({**GLANCE, "events": 8})
    assert not held_in_hand({**GLANCE, "events": 7})
    for change in ({"rotation_sd": None}, {"rotation_sd": 0.1}, {"tilt_deg": 0.2}, {"linear_sd": 0.019}):
        assert not held_in_hand({**GLANCE, **change}), change


def test_fixtures():
    from api_service.main import ensemble_detector
    ours = MOBILE_RULE_CASES[64:67]
    assert [(v, s, b) for v, s, b, _ in ours] == [
        ("HUMAN", "FINAL", "mobile_held_device"), ("SUSPECT", "INSUFFICIENT_EVIDENCE", None),
        ("SUSPECT", "INSUFFICIENT_EVIDENCE", None)]
    held = ensemble_detector.predict(copy.deepcopy(ours[0][3]))
    assert held["breakdown"]["verdict_locked"] is False
    assert held["breakdown"]["mobile_human"]["held_rule"] in ("mobile_held_device_v2", "mobile_held_device_v3")
    assert "HELD_DEVICE" in held["breakdown"]["presence"]["research_flags"]


def test_policy_43_gate_is_frozen_on_its_own_fixtures():
    first = MOBILE_RULE_CASES[:64]
    assert MOBILE_RULE_GATE_V43["fixture_fingerprint"] == hashlib.sha256(
        json.dumps(first, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    assert (MOBILE_RULE_GATE_V43["human_cases"], MOBILE_RULE_GATE_V43["suspect_cases"],
            MOBILE_RULE_GATE_V43["bot_cases"]) == (17, 37, 10)
    assert "mobile_held_device_v1" in MOBILE_RULE_GATE_V43["rules"]
    assert "mobile_held_device_v2" in MOBILE_RULE_GATE_V45["rules"] and MOBILE_RULE_GATE_V45["passed"] == 67


def test_a_hidden_page_has_left():
    assert "hidden" in live.LEFT_ACTIONS and "pagehide" in live.LEFT_ACTIONS


def test_policy_version():
    from core_ml.models.ensemble import DECISION_POLICY_VERSION
    assert DECISION_POLICY_VERSION in ("44", "45", "46", "47", "48", "49")
