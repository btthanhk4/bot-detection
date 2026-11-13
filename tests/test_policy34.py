"""Policy 34: desktop fonts on a phone, empty plugin lists, an environment family alone, the
'seen but never touched' reason code, and the strong Fingerprint flags kept with each label."""

import copy

from api_service.reference import _bot_fields
from core_ml.features.client_forgery import (
    contradictions,
    evidence_codes,
    forgery_codes,
)
from core_ml.release_cases import CLIENT_FORGERY_CASES, MOBILE_RULE_CASES

ANDROID = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) "
           "Chrome/156.0.0.0 Mobile Safari/537.36")
IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_7_8 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
          "Version/26.6 Mobile/15E148 Safari/604.1")
WINDOWS = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
           "Chrome/157.0.0.0 Safari/537.36")


def _fp(ua, **extra):
    return {"fingerprint": {"userAgent": ua, **extra}}


def test_desktop_fonts_only_on_phones_above_eight():
    assert "DESKTOP_FONTS" in forgery_codes(_fp(ANDROID, fontsCount=9), {}, desktop=False)
    assert "DESKTOP_FONTS" in forgery_codes(_fp(IPHONE, fontsCount=12), {}, desktop=False)
    for fonts in (5, 6, 8, None, True, float("nan")):
        assert "DESKTOP_FONTS" not in forgery_codes(_fp(ANDROID, fontsCount=fonts), {}, desktop=False), fonts
    assert "DESKTOP_FONTS" not in forgery_codes(_fp(WINDOWS, fontsCount=40), {}, desktop=True)


def test_desktop_fonts_is_a_contradiction():
    forgery = forgery_codes(_fp(ANDROID, fontsCount=11), {}, desktop=False)
    assert contradictions(forgery) == ["DESKTOP_FONTS"]


def test_evidence_codes_are_desktop_only_and_not_contradictions():
    assert evidence_codes(_fp(WINDOWS, pluginsLength=0), {}) == ["PLUGINS_EMPTY"]
    assert evidence_codes(_fp(WINDOWS, pluginsLength=5), {}) == []
    assert evidence_codes(_fp(WINDOWS), {}) == [], "no plugin count reported is not an empty list"
    assert evidence_codes(_fp(ANDROID, pluginsLength=0), {}) == [], "phones list no plugins"
    assert evidence_codes(_fp(WINDOWS), {"families": {"GPU": ["x"]}}) == ["ENVIRONMENT_EVIDENCE"]
    assert evidence_codes(_fp(WINDOWS), {"families": {"CDP": ["x"]}}) == ["ENVIRONMENT_EVIDENCE"]
    assert evidence_codes(_fp(WINDOWS), {"families": {"NETWORK": ["x"]}}) == []
    # Never counted towards the two contradictions that convict.
    assert contradictions(forgery_codes(_fp(WINDOWS, pluginsLength=0), {}, desktop=True)) == []


def test_empty_plugins_withholds_human_from_a_judged_desktop():
    from api_service.main import ensemble_detector
    from core_ml.release_cases import DESKTOP_RISK_CASES
    verdict, codes, payload = next(case for case in DESKTOP_RISK_CASES if case[0] == "HUMAN")
    payload = copy.deepcopy(payload)
    payload["fingerprint"]["pluginsLength"] = 0
    result = ensemble_detector.predict(payload)
    assert "PLUGINS_EMPTY" in result["breakdown"]["desktop_risk"]["codes"]
    assert result["verdict"] != "HUMAN"


def test_seen_untouched_clean_phone_gets_its_own_reason_code():
    from api_service.main import ensemble_detector
    payload = copy.deepcopy(next(p for v, s, b, p in MOBILE_RULE_CASES if b == "mobile_light_touch"
                                 and "presence" in p["mouse"]))
    payload["mouse"]["touch"]["gestures"], payload["mouse"]["touch"]["total"] = [], 0
    payload["mouse"]["presence"]["firstTouchMs"] = None
    result = ensemble_detector.predict(payload)
    assert result["decision_state"] == "INSUFFICIENT_EVIDENCE"
    assert "NO_INTERACTION_CLEAN" in result["breakdown"]["suspect_reason_codes"]
    payload["mouse"]["presence"]["firstVisibleMs"] = None  # never shown: the other code
    result = ensemble_detector.predict(payload)
    assert "NOT_VIEWED" in result["breakdown"]["suspect_reason_codes"]
    assert "NO_INTERACTION_CLEAN" not in result["breakdown"]["suspect_reason_codes"]


def test_fixtures_cover_both_directions():
    ours = [case for case in CLIENT_FORGERY_CASES
            if "fontsCount" in case[3]["fingerprint"] or "pluginsLength" in case[3]["fingerprint"]]
    bases = [(v, s, b) for v, s, b, p in ours]
    assert bases == [("SUSPECT", "FINAL", "client_forgery"), ("BOT", "FINAL", "forged_browser"),
                     ("SUSPECT", "INSUFFICIENT_EVIDENCE", None), ("SUSPECT", "FINAL", "client_forgery"),
                     ("SUSPECT", "INSUFFICIENT_EVIDENCE", None)]


def test_strong_reference_flags_are_kept():
    fields = _bot_fields({"bot": "not_detected", "tampering": True, "tampering_details": {"anti_detect_browser": False},
                          "suspect_score": 3, "vpn": True, "ip_info": {"v4": {"datacenter_result": False}},
                          "linked_id": "s"})
    assert fields["strong"] is True and fields["tampering"] is True and fields["vpn"] is True
    assert _bot_fields({"bot": "not_detected", "suspect_score": 20})["strong"] is True
    clean = _bot_fields({"bot": "not_detected", "suspect_score": 19})
    assert clean["strong"] is False and clean["suspect_score"] == 19
    assert _bot_fields({"bot": "not_detected", "suspect_score": True})["suspect_score"] is None
