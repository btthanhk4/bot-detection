"""Policy 51 (sparse_pointer_v1): ten moves of any shape no longer turn an idle desktop page into a HUMAN. A
pointer that travelled over 10-24 moves at 45 ms or more between moves is an anomaly (SUSPECT)."""

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone

import mongomock

from api_service.rejudge import reconcile, reconcile_change
from core_ml.release_cases import (
    THREE_VERDICT_CASES,
    THREE_VERDICT_GATE,
    THREE_VERDICT_GATE_V50,
)
from core_ml.three_verdicts import (
    SPARSE_POINTER_MIN_POSITIONS,
    SPARSE_POINTER_MS,
    input_anomalies,
    sparse_pointer,
)

NOW = datetime(2026, 11, 19, 23, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=3)
WINDOWS = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"


def breakdown(moves=15, interval=60.0, positions=15):
    return {"mouse_points": moves, "distinct_positions": positions, "presence": {"visible_ms": 8000},
            "interaction_shadow": {"features": {"move_interval_median_ms": interval}}}


def test_sparse_pointer_conditions():
    assert (SPARSE_POINTER_MS, SPARSE_POINTER_MIN_POSITIONS) == (45.0, 3)
    assert sparse_pointer(breakdown())
    assert not sparse_pointer(breakdown(interval=17.0)), "a mouse at 60 Hz"
    assert not sparse_pointer(breakdown(interval=33.0)), "Chrome's energy saver halves the frame rate"
    assert not sparse_pointer(breakdown(positions=1)), "moves fired by scrolling under a still pointer"
    assert not sparse_pointer(breakdown(moves=9)), "fewer than 10 moves is DESKTOP_IDLE's business"
    assert not sparse_pointer({"mouse_points": 15}), "no interval measured"
    assert input_anomalies(breakdown()) == ["SPARSE_POINTER"]
    phone = {**breakdown(), "mobile_human": {"device": "android"}}
    assert "SPARSE_POINTER" not in input_anomalies(phone), "desktops only"


def test_fixtures_and_frozen_gate():
    from api_service.main import ensemble_detector
    from core_ml.three_verdicts import apply_three_verdicts

    ours = THREE_VERDICT_CASES[10:]
    assert [(v, b, a) for v, _, b, a, _ in ours] == [
        ("SUSPECT", "input_anomaly", ["SPARSE_POINTER"]), ("HUMAN", "no_bot_evidence", []),
        ("HUMAN", "no_bot_evidence", [])]
    for verdict, _, basis, anomalies, payload in ours:
        result = apply_three_verdicts(ensemble_detector.predict(copy.deepcopy(payload)), payload)
        assert (result["verdict"], result["breakdown"]["decision_basis"]) == (verdict, basis)
        assert result["breakdown"]["three_verdicts"]["anomalies"] == anomalies
    assert THREE_VERDICT_GATE_V50["fixture_fingerprint"] == hashlib.sha256(
        json.dumps(THREE_VERDICT_CASES[:10], sort_keys=True, default=str).encode("utf-8")).hexdigest()
    assert "sparse_pointer_v1" in THREE_VERDICT_GATE["rules"] and THREE_VERDICT_GATE["passed"] == 13


def stored(sid, interval, positions=15, verdict="HUMAN", basis="no_bot_evidence", ua=WINDOWS, updated=OLD):
    return {"_id": sid, "sessionId": sid, "verdict": verdict, "decision_state": "FINAL", "policy_version": "50",
            "updated_at": updated, "reasons": ["three verdicts"], "fingerprint": {"userAgent": ua},
            "breakdown": {**breakdown(interval=interval, positions=positions), "decision_basis": basis,
                          "suspect_reason_codes": [], "automation_evidence": {"families": {}}, "touch": {},
                          "three_verdicts": {"version": "three_verdicts_v1", "anomalies": []}}}


def test_reconcile_sparse_pointer():
    assert reconcile_change(stored("a", 60.0))[:2] == ("SUSPECT", "input_anomaly")
    assert reconcile_change(stored("b", 17.0)) is None
    assert reconcile_change(stored("c", 60.0, positions=1)) is None
    assert reconcile_change(stored("d", 60.0, basis="ensemble")) is None, "judged by the mouse models"
    db = mongomock.MongoClient()["p51"]
    db["detection_results"].insert_many([stored("a", 60.0), stored("b", 17.0), stored("c", 60.0, positions=1),
                                         stored("live", 60.0, updated=NOW - timedelta(minutes=3))])
    assert reconcile(db, now=NOW)["changes"] == {"sparse pointer -> SUSPECT": 1}
    assert reconcile(db, apply=True, now=NOW)["written"] == 1
    a = db["detection_results"].find_one({"_id": "a"})
    assert (a["verdict"], a["breakdown"]["decision_basis"], a["breakdown"]["suspect_reason_codes"]) == (
        "SUSPECT", "input_anomaly", ["SPARSE_POINTER"])
    assert a["breakdown"]["three_verdicts"]["anomalies"] == ["SPARSE_POINTER"]
    assert a["rejudged"]["from_verdict"] == "HUMAN"
    assert reconcile(db, now=NOW)["changed"] == 0


def test_policy_version():
    from core_ml.models.ensemble import DECISION_POLICY_VERSION

    assert DECISION_POLICY_VERSION == "51"


ANDROID = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 "
           "Mobile Safari/537.36")


def test_silent_sensor_with_touches_is_not_human():
    from api_service.main import ensemble_detector
    from core_ml.release_cases import (
        MOBILE_RULE_CASES,
    MOBILE_RULE_CASES_V50,
        MOBILE_RULE_GATE,
        MOBILE_RULE_GATE_V50,
    )

    ours = MOBILE_RULE_CASES[80:]
    assert [(v, s, b) for v, s, b, _ in ours] == [("SUSPECT", "FINAL", "mobile_risk")]
    assert MOBILE_RULE_CASES[62][:3] == ("SUSPECT", "FINAL", "mobile_risk")
    assert MOBILE_RULE_CASES_V50[62][:3] == ("HUMAN", "FINAL", "mobile_light_touch")
    ours = ours + (MOBILE_RULE_CASES[62],)
    for _, _, _, payload in ours:
        result = ensemble_detector.predict(copy.deepcopy(payload))
        assert "SENSORS_UNAVAILABLE" in result["breakdown"]["mobile_human"]["risk"]
        assert result["verdict"] == "SUSPECT"
    assert MOBILE_RULE_GATE_V50["fixture_fingerprint"] == hashlib.sha256(
        json.dumps(MOBILE_RULE_CASES_V50[:80], sort_keys=True, default=str).encode("utf-8")).hexdigest()
    assert "sensors_unavailable_touch_v1" in MOBILE_RULE_GATE["rules"] and MOBILE_RULE_GATE["passed"] == 81


def phone_doc(sid, basis="mobile_light_touch", flags=("SENSORS_UNAVAILABLE",), verdict="HUMAN"):
    return {"_id": sid, "sessionId": sid, "verdict": verdict, "decision_state": "FINAL", "policy_version": "49",
            "updated_at": OLD, "reasons": ["touch"], "fingerprint": {"userAgent": ANDROID},
            "breakdown": {"decision_basis": basis, "presence": {"research_flags": list(flags), "visible_ms": 40000},
                          "mobile_human": {"device": "android", "gestures": 1, "missing": ["FEW_GESTURES"],
                                           "risk": []}, "touch": {}, "automation_evidence": {"families": {}}}}


def test_reconcile_silent_sensor():
    assert reconcile_change(phone_doc("a"))[:2] == ("SUSPECT", "mobile_risk")
    assert reconcile_change(phone_doc("b", basis="mobile_clean_environment"))[:2] == ("SUSPECT", "mobile_risk")
    assert reconcile_change(phone_doc("c", flags=("HELD_DEVICE",))) is None
    assert reconcile_change(phone_doc("d", basis="no_bot_evidence")) is None, "no touch: the anomaly layer's"
    db = mongomock.MongoClient()["p51b"]
    db["detection_results"].insert_many([phone_doc("a"), phone_doc("c", flags=("HELD_DEVICE",))])
    assert reconcile(db, apply=True, now=NOW)["changes"] == {"silent sensor with touches -> SUSPECT": 1}
    a = db["detection_results"].find_one({"_id": "a"})
    assert a["verdict"] == "SUSPECT" and a["breakdown"]["mobile_human"]["risk"] == ["SENSORS_UNAVAILABLE"]
    assert reconcile(db, now=NOW)["changed"] == 0
