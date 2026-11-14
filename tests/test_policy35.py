"""Policy 35: emulated motion sensors, a flagship reporting too little memory, and one sensor
calibration behind several claimed phone models."""

import copy
from datetime import datetime, timedelta, timezone

import mongomock
import pytest

from api_service import sensor_fleet
from core_ml.features.client_forgery import (
    contradictions,
    forgery_codes,
    model_memory_mismatch,
)
from core_ml.features.presence import (
    analyze_presence,
    sensor_signature,
    still_signature,
    synthetic_motion,
)
from core_ml.features.server_context import server_context_codes
from core_ml.release_cases import (
    _EMULATED_MOTION,
    _HAND_MOTION,
    _S23,
    _TABLE_MOTION,
    MOBILE_RULE_CASES,
)

ANDROID = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) "
           "Chrome/156.0.0.0 Mobile Safari/537.36")
IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_7_8 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
          "Version/26.6 Mobile/15E148 Safari/604.1")


def _summary(raw):
    """The sanitized motion summary, as the server stores it."""
    return analyze_presence({"mouse": {"presence": {"firstVisibleMs": 0, "motion": raw}}}, android=True)["motion"]


def _payload(motion=None, model="SM-S918B", memory=8, ua=ANDROID, session="s"):
    payload = {"sessionId": session, "fingerprint": {"userAgent": ua, "deviceMemory": memory},
               "mouse": {"presence": {"firstVisibleMs": 0, "visibleMs": 9000, "motion": motion or _TABLE_MOTION}},
               "botd": {"profile": {"main": {"clientHints": {"model": model, "mobile": True}}}}}
    if model is None:
        payload["botd"] = {}
    return payload


# ---- SYNTHETIC_MOTION ----

def test_emulated_motion_is_flagged_and_real_phones_are_not():
    assert synthetic_motion(_summary(_EMULATED_MOTION))
    assert not synthetic_motion(_summary(_TABLE_MOTION)), "a phone on a table is tilted by its camera bump"
    assert not synthetic_motion(_summary(_HAND_MOTION))


@pytest.mark.parametrize("change, fires", [
    ({"tiltDeg": 0.2}, True), ({"tiltDeg": 0.3}, False), ({"tiltDeg": 0.6}, False),
    ({"linearSd": 0.03}, True), ({"linearSd": 0.029}, False), ({"linearSd": 0.0}, False),
    ({"events": 100}, True), ({"events": 99}, False), ({"status": "no_events"}, False),
    ({"tiltDeg": None}, False), ({"tiltDeg": True}, False), ({"linearSd": float("nan")}, False),
])
def test_synthetic_motion_boundaries(change, fires):
    assert synthetic_motion(_summary({**_EMULATED_MOTION, **change})) is fires


def test_synthetic_motion_is_a_presence_code():
    report = analyze_presence(_payload(_EMULATED_MOTION), android=True)
    assert "SYNTHETIC_MOTION" in report["codes"] and report["analysis_version"] == "presence_v2"
    assert "SYNTHETIC_MOTION" not in analyze_presence(_payload(_TABLE_MOTION), android=True)["codes"]


# ---- MODEL_MEMORY_MISMATCH ----

@pytest.mark.parametrize("model, memory, fires", [
    ("SM-S918B", 4, True), ("SM-S921U1", 2, True), ("SM-F731B", 4, True), ("SM-F946B", 4, True),
    ("Pixel 9 Pro XL", 4, True), ("Pixel 6", 4, True), ("Pixel 7a", 4, True),
    ("SM-S918B", 8, False), ("Pixel 9 Pro", 8, False),
    ("Pixel 6a", 4, False), ("Pixel 10a", 4, False), ("Pixel 5", 4, False), ("SM-S711B", 4, False),
    ("SM-A546B", 4, False), ("SM-G990B", 4, False), ("CPH2727", 4, False), ("", 4, False), (None, 4, False),
    ("SM-S918B", None, False), ("SM-S918B", True, False), ("SM-S918B", float("nan"), False), ("SM-S918B", 0, False),
])
def test_model_memory_mismatch(model, memory, fires):
    assert model_memory_mismatch(_payload(model=model, memory=memory)) is fires


def test_model_memory_mismatch_needs_an_android_user_agent_and_is_a_contradiction():
    assert not model_memory_mismatch(_payload(model="SM-S918B", memory=4, ua=IPHONE))
    codes = forgery_codes(_payload(model="SM-S918B", memory=4), {}, desktop=False)
    assert codes == ["MODEL_MEMORY_MISMATCH"]
    assert contradictions(codes) == ["MODEL_MEMORY_MISMATCH"]


# ---- Sensor signature ----

def test_still_signature_only_for_a_phone_lying_still():
    assert still_signature(_summary(_TABLE_MOTION)) == (9.71, 2.3)
    assert still_signature(_summary(_HAND_MOTION)) is None
    assert still_signature(_summary(_EMULATED_MOTION)) is None, "jitter above 0.06"
    assert still_signature(_summary({**_TABLE_MOTION, "rotationSd": 0.1})) is None
    assert still_signature(_summary({**_TABLE_MOTION, "rotationSd": None})) == (9.71, 2.3)
    assert still_signature(_summary({**_TABLE_MOTION, "events": 49})) is None
    assert still_signature(_summary({**_TABLE_MOTION, "gravity": None})) is None


def test_sensor_signature_needs_a_claimed_model():
    assert sensor_signature(_payload()) == (9.71, 2.3, "SM-S918B")
    assert sensor_signature(_payload(model="")) is None
    assert sensor_signature(_payload(model=None)) is None
    assert sensor_signature(_payload(_HAND_MOTION)) is None


def test_server_code_from_three_models():
    def codes(value):
        return server_context_codes({"_server_headers": {"sensor_signature_models": value}})
    assert "SHARED_SENSOR_SIGNATURE" in codes(3) and "SHARED_SENSOR_SIGNATURE" in codes(12)
    for value in (2, 1, None, True, "3", 3.0):
        assert "SHARED_SENSOR_SIGNATURE" not in codes(value), value


@pytest.fixture
def db():
    database = mongomock.MongoClient(tz_aware=True)["bot_detection"]
    assert sensor_fleet.ensure_indexes(database)
    sensor_fleet._memo.values.clear()
    return database


def _stored(db, session, model, motion=None, age_hours=0.0):
    report = analyze_presence(_payload(motion or _TABLE_MOTION, model=model), android=True)
    db["detection_results"].insert_one({
        "sessionId": session, "created_at": datetime.now(timezone.utc) - timedelta(hours=age_hours),
        "breakdown": {"presence": report}})


def test_shared_signature_counts_distinct_claimed_models(db):
    _stored(db, "a", "Pixel 9 Pro")
    _stored(db, "b", "SM-A346B")
    _stored(db, "c", "SM-A346B")  # the same model again counts once
    _stored(db, "d", "", )  # no model: not counted
    assert sensor_fleet.shared_signature_models(db, _payload(model="CPH2449"), "new") == 3
    sensor_fleet._memo.values.clear()
    assert sensor_fleet.shared_signature_models(db, _payload(model="Pixel 9 Pro"), "new") == 2


def test_shared_signature_ignores_its_own_session_old_moving_and_distant_rows(db):
    _stored(db, "self", "Pixel 9 Pro")
    _stored(db, "old", "SM-A346B", age_hours=25)
    _stored(db, "moving", "Pixel 7", motion={**_TABLE_MOTION, "gravitySd": 0.3})
    _stored(db, "far-gravity", "Pixel 8", motion={**_TABLE_MOTION, "gravity": 9.73})
    _stored(db, "far-tilt", "Pixel 6", motion={**_TABLE_MOTION, "tiltDeg": 2.5})
    _stored(db, "near", "SM-S921B", motion={**_TABLE_MOTION, "gravity": 9.72, "tiltDeg": 2.4})
    assert sensor_fleet.shared_signature_models(db, _payload(model="Pixel 9 Pro", session="self"), "self") == 2


def test_shared_signature_is_none_without_a_signature_or_database(db):
    assert sensor_fleet.shared_signature_models(db, _payload(_HAND_MOTION), "x") is None
    assert sensor_fleet.shared_signature_models(db, _payload(model=""), "x") is None
    assert sensor_fleet.shared_signature_models(None, _payload(), "x") is None

    class Broken:
        def __getitem__(self, name):
            raise RuntimeError("down")
    assert sensor_fleet.shared_signature_models(Broken(), _payload(), "x") is None


def test_shared_signature_is_memoised_per_session(db):
    _stored(db, "a", "Pixel 9 Pro")
    _stored(db, "b", "SM-A346B")
    assert sensor_fleet.shared_signature_models(db, _payload(model="CPH2449"), "new") == 3
    db["detection_results"].delete_many({})
    assert sensor_fleet.shared_signature_models(db, _payload(model="CPH2449"), "new") == 3


def test_api_counts_models_for_phones_only(db, monkeypatch):
    from starlette.requests import Request

    from api_service import database, main

    monkeypatch.setattr(database, "get_db", lambda: db)
    monkeypatch.setattr(main, "_sensor_indexes_ready", False)

    def request():
        return Request({"type": "http", "method": "POST", "path": "/api/v1/telemetry", "query_string": b"",
                        "headers": [(b"host", b"partner.example"), (b"user-agent", ANDROID.encode())],
                        "client": ("203.0.113.7", 1234)})

    _stored(db, "a", "Pixel 9 Pro")
    _stored(db, "b", "SM-A346B")
    phone = {**_payload(model="CPH2449"), "client_ip": "203.0.113.7"}
    main._attach_server_context(request(), phone, link=True)
    assert phone["_server_headers"]["sensor_signature_models"] == 3
    desktop = {**_payload(model="CPH2449", ua="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/157.0.0.0"),
               "client_ip": "203.0.113.7", "sessionId": "d"}
    main._attach_server_context(request(), desktop, link=True)
    assert desktop["_server_headers"]["sensor_signature_models"] is None


# ---- Decisions ----

def _case(index):
    return copy.deepcopy(MOBILE_RULE_CASES[index][3])


def test_fixtures_cover_both_directions():
    ours = MOBILE_RULE_CASES[-7:]
    assert [(v, s, b) for v, s, b, _ in ours] == [
        ("HUMAN", "FINAL", "mobile_light_touch"), ("HUMAN", "FINAL", "mobile_clean_environment"),
        ("SUSPECT", "FINAL", "mobile_risk"), ("SUSPECT", "FINAL", "mobile_risk"),
        ("SUSPECT", "FINAL", "client_forgery"), ("SUSPECT", "FINAL", "mobile_risk"),
        ("SUSPECT", "INSUFFICIENT_EVIDENCE", None)]
    assert ours[1][3]["botd"]["profile"]["main"]["clientHints"] == _S23


def test_emulated_motion_withholds_human_from_a_tapping_phone():
    from api_service.main import ensemble_detector
    payload = _case(-7)
    assert ensemble_detector.predict(payload)["verdict"] == "HUMAN"
    payload["mouse"]["presence"]["motion"] = dict(_EMULATED_MOTION)
    result = ensemble_detector.predict(payload)
    assert (result["verdict"], result["decision_state"]) == ("SUSPECT", "FINAL")
    assert "SYNTHETIC_MOTION" in result["breakdown"]["mobile_human"]["risk"]
    assert "SYNTHETIC_MOTION" in result["breakdown"]["presence"]["codes"]


def test_untouched_clean_phone_keeps_its_reason_code_until_evidence_arrives():
    from api_service.main import ensemble_detector
    payload = _case(-1)  # two models only
    result = ensemble_detector.predict(payload)
    assert result["decision_state"] == "INSUFFICIENT_EVIDENCE"
    assert "NO_INTERACTION_CLEAN" in result["breakdown"]["suspect_reason_codes"]
    payload["_server_headers"]["sensor_signature_models"] = 3
    result = ensemble_detector.predict(payload)
    assert (result["verdict"], result["decision_state"]) == ("SUSPECT", "FINAL")
    assert result["breakdown"]["mobile_human"]["risk"] == ["SHARED_SENSOR_SIGNATURE"]
    assert "NO_INTERACTION_CLEAN" not in result["breakdown"]["suspect_reason_codes"]


def test_flagship_with_four_gigabytes_never_becomes_bot_alone():
    from api_service.main import ensemble_detector
    payload = _case(-6)  # an S23 tapping with a hand: HUMAN at 8 GB
    payload["fingerprint"]["deviceMemory"] = 4
    result = ensemble_detector.predict(payload)
    assert (result["verdict"], result["decision_state"]) == ("SUSPECT", "FINAL")
    assert result["breakdown"]["client_forgery"]["contradictions"] == ["MODEL_MEMORY_MISMATCH"]


def test_policy_version():
    from core_ml.models.ensemble import DECISION_POLICY_VERSION
    assert DECISION_POLICY_VERSION == "35"
