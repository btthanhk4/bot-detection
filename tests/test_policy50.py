"""Policy 50: a few zero-time taps among real presses no longer withhold a phone's HUMAN verdict, and
``reconcile`` brings stored verdicts without raw snapshots in line with policies 42, 49 and 50."""

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone

import mongomock

from api_service.rejudge import RECONCILE_VERSION, reconcile, reconcile_change
from core_ml.features.mobile_human import (
    touch_flags_against,
    zero_time_taps_among_presses,
)
from core_ml.release_cases import (
    MOBILE_RULE_CASES,
    MOBILE_RULE_CASES_V50,
    MOBILE_RULE_GATE,
    MOBILE_RULE_GATE_V49,
)

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=4)
ANDROID = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 "
           "Mobile Safari/537.36")


def touch(taps, zero):
    return {"taps": taps, "zero_time_taps": zero, "research_flags": ["ZERO_TIME_TAPS"] if zero >= 2 else []}


def test_zero_time_taps_among_presses():
    assert zero_time_taps_among_presses(touch(5, 2)) and zero_time_taps_among_presses(touch(6, 3))
    assert not zero_time_taps_among_presses(touch(4, 2)), "two real presses are not enough"
    assert not zero_time_taps_among_presses(touch(7, 4)), "most taps at 0 ms"
    assert not zero_time_taps_among_presses(touch(6, 6)), "adb input tap: every tap at 0 ms"
    assert touch_flags_against(touch(10, 2)) == []
    assert touch_flags_against(touch(4, 4)) == ["ZERO_TIME_TAPS"]
    assert touch_flags_against({"taps": 8, "zero_time_taps": 2,
                                "research_flags": ["ZERO_TIME_TAPS", "RULER_SWIPES"]}) == ["RULER_SWIPES"]


def test_fixtures():
    from api_service.main import ensemble_detector

    ours = MOBILE_RULE_CASES[78:80]
    assert [(v, s, b) for v, s, b, _ in ours] == [("HUMAN", "FINAL", "mobile_clean_environment"),
                                                 ("SUSPECT", "FINAL", "mobile_risk")]
    for verdict, _, basis, payload in ours:
        result = ensemble_detector.predict(copy.deepcopy(payload))
        assert result["breakdown"]["touch"]["research_flags"] == ["ZERO_TIME_TAPS"], "the flag itself is unchanged"
        assert (result["verdict"], result["breakdown"]["decision_basis"]) == (verdict, basis)


def test_policy_49_gate_is_frozen_on_its_own_fixtures():
    assert MOBILE_RULE_GATE_V49["fixture_fingerprint"] == hashlib.sha256(
        json.dumps(MOBILE_RULE_CASES_V50[:78], sort_keys=True, default=str).encode("utf-8")).hexdigest()
    assert "zero_time_taps_among_presses_v1" in MOBILE_RULE_GATE["rules"] and MOBILE_RULE_GATE["passed"] == 81


def test_forged_browser_still_convicts_with_zero_time_taps():
    from core_ml.features.client_forgery import forged_browser_fires

    evidence = {"families": {"NATIVE_PATCH": ["signals.webdriverPatched"]}}
    assert forged_browser_fires(["WEBDRIVER_TAMPERED"], evidence, ["ZERO_TIME_TAPS"], user_agent=ANDROID)


def worker_only(sid, *, webdriver=False):
    families = {"GPU": ["worker.rendererMismatch"], "CONTEXT": ["worker.platformMismatch"]}
    if webdriver:
        families["NATIVE_PATCH"] = ["signals.webdriverPatched"]
    return {"_id": sid, "sessionId": sid, "verdict": "BOT", "decision_state": "FINAL", "policy_version": "41",
            "updated_at": OLD, "reasons": ["forged"], "fingerprint": {"userAgent": ANDROID},
            "breakdown": {"decision_basis": "forged_browser", "automation_rule": "forged_browser_v1",
                          "client_forgery": {"codes": ["PLATFORM_SPOOFED"]},
                          "automation_evidence": {"families": families}, "touch": {}}}


def autoclick(sid, rule):
    return {"_id": sid, "sessionId": sid, "verdict": "BOT", "decision_state": "FINAL", "policy_version": "37",
            "updated_at": OLD, "reasons": ["autoclick"], "fingerprint": {"userAgent": ANDROID},
            "breakdown": {"decision_basis": "touch_automation", "automation_rule": rule,
                          "touch": {"research_flags": ["AUTOCLICK_TAPS"]}}}


def zero_quirk(sid, taps, zero, missing=("TOUCH_FLAGS",), updated=OLD):
    return {"_id": sid, "sessionId": sid, "verdict": "SUSPECT", "decision_state": "FINAL", "policy_version": "32",
            "updated_at": updated, "reasons": ["touch flags"], "fingerprint": {"userAgent": ANDROID},
            "breakdown": {"decision_basis": "mobile_risk", "suspect_reason_codes": ["MOBILE_RISK"],
                          "mobile_human": {"device": "android", "gestures": taps, "missing": list(missing),
                                           "risk": ["TOUCH_FLAGS"]},
                          "touch": touch(taps, zero), "automation_evidence": {"families": {}},
                          # As stored: the zero-time taps are listed as the session's one contradiction.
                          "client_forgery": {"codes": [], "contradictions": ["ZERO_TIME_TAPS"]}}}


def test_reconcile_change():
    assert reconcile_change(worker_only("a"))[3] == "forged_browser -> SUSPECT"
    assert reconcile_change(worker_only("b", webdriver=True)) is None, "two contradictions still convict"
    assert reconcile_change(autoclick("c", "autoclick_taps_v1"))[:2] == ("SUSPECT", "mobile_risk")
    assert reconcile_change(autoclick("d", "autoclick_taps_v2")) is None
    assert reconcile_change(zero_quirk("e", 8, 2))[:2] == ("HUMAN", "mobile_clean_environment")
    assert reconcile_change(zero_quirk("f", 6, 4)) is None
    assert reconcile_change(zero_quirk("g", 8, 2, missing=("TOUCH_FLAGS", "UNVERIFIED_PAGE_LOAD"))) is None
    two = zero_quirk("h", 8, 2)
    two["breakdown"]["client_forgery"]["contradictions"] = ["WEBDRIVER_TAMPERED", "ZERO_TIME_TAPS"]
    assert reconcile_change(two) is None, "another contradiction keeps it SUSPECT"


def test_reconcile_counts_then_writes_and_keeps_the_previous_verdict():
    db = mongomock.MongoClient()["reconcile"]
    db["detection_results"].insert_many([
        worker_only("a"), worker_only("b", webdriver=True), autoclick("c", "autoclick_taps_v1"),
        autoclick("d", "autoclick_taps_v2"), zero_quirk("e", 8, 2), zero_quirk("f", 6, 4),
        zero_quirk("live", 8, 2, updated=NOW - timedelta(minutes=5))])
    counted = reconcile(db, now=NOW)
    assert counted["changes"] == {"forged_browser -> SUSPECT": 1, "autoclick_v1 -> SUSPECT": 1,
                                  "zero-time quirk -> HUMAN": 1}
    assert counted["left_to_live_traffic"] == 1 and counted["written"] == 0
    assert db["detection_results"].find_one({"_id": "a"})["verdict"] == "BOT"

    applied = reconcile(db, apply=True, now=NOW)
    assert applied["written"] == 3
    a = db["detection_results"].find_one({"_id": "a"})
    assert (a["verdict"], a["is_bot"], a["verdict_locked"], a["breakdown"]["decision_basis"]) == (
        "SUSPECT", False, False, "client_forgery")
    assert a["rejudged"]["rule"] == RECONCILE_VERSION and a["rejudged"]["from_verdict"] == "BOT"
    e = db["detection_results"].find_one({"_id": "e"})
    assert e["verdict"] == "HUMAN" and e["breakdown"]["mobile_human"]["missing"] == []
    assert e["breakdown"]["suspect_reason_codes"] == []
    for unchanged in ("b", "d", "f", "live"):
        assert "rejudged" not in db["detection_results"].find_one({"_id": unchanged})
    assert reconcile(db, now=NOW)["changed"] == 0, "a second run finds nothing"


def test_policy_version():
    from core_ml.models.ensemble import DECISION_POLICY_VERSION

    assert DECISION_POLICY_VERSION in ("50", "51", "52")
