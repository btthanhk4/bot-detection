"""Policy 49 (autoclick_taps_v2): a metronomic group of taps at one point convicts only when it is pressed
like a machine: the same contact geometry on every tap, pressed for a fixed time or for under 20 ms."""

import copy
import hashlib
import json

from core_ml.features.touch import (
    AUTOCLICK_MAX_PRESS_CV,
    AUTOCLICK_RULE,
    AUTOCLICK_SHORT_PRESS_MS,
    TOUCH_ANALYSIS_VERSION,
    analyze_touch,
)
from core_ml.release_cases import (
    MOBILE_RULE_CASES,
    MOBILE_RULE_CASES_V50,
    MOBILE_RULE_GATE,
    MOBILE_RULE_GATE_V48,
)


def taps(presses, contacts=None, x=105.5, y=408.0, gap=210.0, jitter=(0, 24, -12, 8, -6, 10)):
    """Six taps at one point at a steady rhythm; ``presses`` in ms, ``contacts`` (radius, force) per tap."""
    contacts = contacts or [(0.3, 1.0)] * len(presses)
    gestures, t0 = [], 1000.0
    for i, (ms, (radius, force)) in enumerate(zip(presses, contacts)):
        gestures.append({"t0": t0, "points": [[0.0, x, y, radius, radius, force],
                                              [ms, x + 0.3, y, radius, radius, force]]})
        t0 += gap + jitter[i % len(jitter)]
    return {"gestures": gestures, "total": len(gestures)}


def test_people_drumming_on_a_button_are_not_autoclickers():
    # The finger's contact changes from tap to tap (a phone reporting contact size).
    drumming = analyze_touch(taps((97, 97, 95, 87, 93, 150), [(2.0, 1), (1.3, 1), (1.5, 1), (2.0, 1), (2.3, 1), (1.8, 1)]))
    assert drumming["metronomic_taps"] == 6 and drumming["autoclick_taps"] == 0
    assert "AUTOCLICK_TAPS" not in drumming["research_flags"]
    # The same contact (no size or pressure sensor) but presses spread like a person's.
    no_sensor = analyze_touch(taps((94.5, 61.2, 93.2, 124.4, 117.9, 107.6)))
    assert no_sensor["metronomic_taps"] == 6 and no_sensor["autoclick_taps"] == 0
    # Pressure that varies (a phone with a pressure sensor and no size sensor).
    pressure = analyze_touch(taps((117, 127, 94, 116, 130, 101), [(0, 1.91), (0, 1.89), (0, 1.9), (0, 1.89), (0, 1.88), (0, 1.96)]))
    assert pressure["autoclick_taps"] == 0


def test_machines_still_convict():
    fixed = analyze_touch(taps((40, 40, 40, 40, 40, 40)))
    assert fixed["autoclick_taps"] == 6 and "AUTOCLICK_TAPS" in fixed["research_flags"]
    near_fixed = analyze_touch(taps((50.0, 50.8, 49.6, 50.3, 49.9, 50.5)))
    assert near_fixed["autoclick_taps"] == 6, "a jitter of 1-2% is still a fixed press time"
    short = analyze_touch(taps((8, 4, 5, 9, 7, 13), [(26.7, 0.0)] * 6))
    assert short["autoclick_taps"] == 6
    # Irregular rhythm: not metronomic, whatever the presses.
    irregular = analyze_touch(taps((40,) * 6, jitter=(0, 300, -150, 420, -90, 260)))
    assert irregular["metronomic_taps"] == 0 and irregular["autoclick_taps"] == 0
    assert AUTOCLICK_RULE == "autoclick_taps_v2" and TOUCH_ANALYSIS_VERSION == "touch_v3"
    assert (AUTOCLICK_MAX_PRESS_CV, AUTOCLICK_SHORT_PRESS_MS) == (0.05, 20.0)


def test_fixtures():
    from api_service.main import ensemble_detector

    ours = MOBILE_RULE_CASES[75:78]
    assert [(v, s, b) for v, s, b, _ in ours] == [
        ("HUMAN", "FINAL", "mobile_clean_environment"), ("HUMAN", "FINAL", "mobile_clean_environment"),
        ("BOT", "FINAL", "touch_automation")]
    bot = ensemble_detector.predict(copy.deepcopy(ours[2][3]))
    assert bot["breakdown"]["automation_rule"] == "autoclick_taps_v2"
    drumming = ensemble_detector.predict(copy.deepcopy(ours[0][3]))
    assert drumming["breakdown"]["touch"]["metronomic_taps"] == 6


def test_policy_48_gate_is_frozen_on_its_own_fixtures():
    first = MOBILE_RULE_CASES_V50[:75]
    assert MOBILE_RULE_GATE_V48["fixture_fingerprint"] == hashlib.sha256(
        json.dumps(first, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    assert "autoclick_taps_v2" in MOBILE_RULE_GATE["rules"] and MOBILE_RULE_GATE["passed"] == 81


def test_policy_version():
    from core_ml.models.ensemble import DECISION_POLICY_VERSION

    assert DECISION_POLICY_VERSION in ("49", "50", "51", "52")
