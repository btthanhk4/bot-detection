"""Policy 39: a real low-end phone lying level is not emulated motion."""

import copy

from core_ml.features.presence import (
    analyze_presence,
    emulated_phone_fires,
    synthetic_motion,
)
from core_ml.release_cases import (
    _EMULATED_MOTION,
    _LEVEL_LOW_END_MOTION,
    MOBILE_RULE_CASES,
)


def _summary(raw):
    return analyze_presence({"mouse": {"presence": {"firstVisibleMs": 0, "motion": raw}}}, android=True)["motion"]


def test_the_redmi_on_a_desk_is_not_emulated_motion_whatever_its_event_count():
    for events in (84, 100, 400):
        assert not synthetic_motion(_summary({**_LEVEL_LOW_END_MOTION, "events": events})), events
    assert synthetic_motion(_summary(_EMULATED_MOTION))


def test_it_can_never_convict_even_with_every_second_channel():
    codes = analyze_presence({"mouse": {"presence": {"firstVisibleMs": 0, "motion": _LEVEL_LOW_END_MOTION}}},
                             android=True)["codes"]
    assert "SYNTHETIC_MOTION" not in codes
    assert not emulated_phone_fires(codes, ["AUDIO_NOVEL", "TIMEZONE_MISMATCH"], ["MODEL_MEMORY_MISMATCH"])


def test_fixtures():
    ours = MOBILE_RULE_CASES[52:]
    assert [(v, s, b) for v, s, b, _ in ours] == [
        ("HUMAN", "FINAL", "mobile_light_touch"), ("SUSPECT", "INSUFFICIENT_EVIDENCE", None),
        ("SUSPECT", "FINAL", "mobile_risk")]


def test_with_audio_novel_and_another_country_it_stays_suspect_not_bot():
    from api_service.main import ensemble_detector
    payload = copy.deepcopy(MOBILE_RULE_CASES[54][3])
    payload["_server_headers"]["audio_hash_sessions"] = 0
    result = ensemble_detector.predict(payload)
    assert result["verdict"] == "SUSPECT" and result["breakdown"]["automation_rule"] is None


def test_policy_version():
    from core_ml.models.ensemble import DECISION_POLICY_VERSION
    assert DECISION_POLICY_VERSION == "39"
