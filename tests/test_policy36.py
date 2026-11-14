"""Policy 36: a BOT verdict for emulated phones (emulated motion + an independent channel), and an
Android Chrome audio fingerprint nobody else reported."""

import copy
from datetime import datetime, timedelta, timezone

import mongomock
import pytest

from api_service import sensor_fleet
from core_ml.features.presence import emulated_phone_fires
from core_ml.features.server_context import server_context_codes
from core_ml.release_cases import (
    _EMULATED_MOTION,
    _HAND_MOTION,
    _TABLE_MOTION,
    MOBILE_RULE_CASES,
)

ANDROID = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) "
           "Chrome/156.0.0.0 Mobile Safari/537.36")
WEBVIEW = ("Mozilla/5.0 (Linux; Android 13; SM-A546B Build/TP1A; wv) AppleWebKit/537.36 (KHTML, like Gecko) "
           "Version/4.0 Chrome/156.0.0.0 Mobile Safari/537.36")
FACEBOOK = ANDROID + " [FBAN/EMA;FBLC/vi_VN;FBAV/480.0.0.0;]"
SAMSUNG = ("Mozilla/5.0 (Linux; Android 14; SM-A546B) AppleWebKit/537.36 (KHTML, like Gecko) "
           "SamsungBrowser/27.0 Chrome/125.0.0.0 Mobile Safari/537.36")
IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_7_8 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
          "Version/26.6 Mobile/15E148 Safari/604.1")
WINDOWS = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"


# ---- the rule ----

@pytest.mark.parametrize("presence, server, contradictions, fires", [
    (["SYNTHETIC_MOTION"], ["AUDIO_NOVEL"], [], True),
    (["SYNTHETIC_MOTION"], ["TIMEZONE_MISMATCH"], [], True),
    (["SYNTHETIC_MOTION"], [], ["MODEL_MEMORY_MISMATCH"], True),
    (["SYNTHETIC_MOTION"], [], [], False),
    (["SYNTHETIC_MOTION"], ["SHARED_SENSOR_SIGNATURE", "UNVERIFIED_PAGE_LOAD", "DEVICE_VELOCITY"], [], False),
    ([], ["AUDIO_NOVEL", "TIMEZONE_MISMATCH"], ["MODEL_MEMORY_MISMATCH"], False),
    (["NOT_VIEWED", "INSTANT_TOUCH"], ["AUDIO_NOVEL"], [], False),
])
def test_emulated_phone_needs_emulated_motion_and_an_independent_channel(presence, server, contradictions, fires):
    assert emulated_phone_fires(presence, server, contradictions) is fires


def test_audio_novel_code_only_for_zero():
    def codes(value):
        return server_context_codes({"_server_headers": {"audio_hash_sessions": value}})
    assert "AUDIO_NOVEL" in codes(0)
    for value in (1, 5, None, False, "0", 0.0):
        assert "AUDIO_NOVEL" not in codes(value), value


# ---- the audio count ----

@pytest.fixture
def db():
    database = mongomock.MongoClient(tz_aware=True)["bot_detection"]
    assert sensor_fleet.ensure_indexes(database)
    sensor_fleet._memo.values.clear()
    sensor_fleet._warm.update(until=0.0, value=False)
    return database


def _payload(audio="a1", ua=ANDROID):
    return {"fingerprint": {"userAgent": ua, "audioHash": audio}}


def _fill(db, n=sensor_fleet.AUDIO_WARM_SESSIONS, audio="common", age_hours=1.0):
    now = datetime.now(timezone.utc)
    db["detection_results"].insert_many([
        {"sessionId": f"s{i}", "created_at": now - timedelta(hours=age_hours), "fingerprint": {"audioHash": audio}}
        for i in range(n)])


def test_audio_count_needs_a_warm_store(db):
    _fill(db, n=sensor_fleet.AUDIO_WARM_SESSIONS - 1)
    assert sensor_fleet.audio_hash_sessions(db, _payload("fresh"), "x") is None
    db["detection_results"].insert_one({"sessionId": "w", "created_at": datetime.now(timezone.utc),
                                        "fingerprint": {"audioHash": "common"}})
    sensor_fleet._warm.update(until=0.0)
    assert sensor_fleet.audio_hash_sessions(db, _payload("fresh"), "x") == 0


def test_audio_count_counts_others_in_the_last_day(db):
    _fill(db)
    assert sensor_fleet.audio_hash_sessions(db, _payload("common"), "x") == 5, "capped at 5"
    db["detection_results"].insert_many([
        {"sessionId": "own", "created_at": datetime.now(timezone.utc), "fingerprint": {"audioHash": "mine"}},
        {"sessionId": "old", "created_at": datetime.now(timezone.utc) - timedelta(hours=25),
         "fingerprint": {"audioHash": "mine"}}])
    assert sensor_fleet.audio_hash_sessions(db, _payload("mine"), "own") == 0
    db["detection_results"].insert_one({"sessionId": "other", "created_at": datetime.now(timezone.utc),
                                        "fingerprint": {"audioHash": "mine"}})
    sensor_fleet._memo.values.clear()
    assert sensor_fleet.audio_hash_sessions(db, _payload("mine"), "own") == 1


@pytest.mark.parametrize("ua", [WEBVIEW, FACEBOOK, SAMSUNG, IPHONE, WINDOWS])
def test_audio_is_judged_only_for_android_chrome(db, ua):
    _fill(db)
    assert not sensor_fleet.audio_judged(_payload("fresh", ua))
    assert sensor_fleet.audio_hash_sessions(db, _payload("fresh", ua), "x") is None


@pytest.mark.parametrize("audio", [None, "", True])
def test_audio_missing_is_not_judged(db, audio):
    _fill(db)
    assert sensor_fleet.audio_hash_sessions(db, _payload(audio), "x") is None


def test_audio_count_survives_a_database_failure():
    class Broken:
        def __getitem__(self, name):
            raise RuntimeError("down")
    sensor_fleet._memo.values.clear()
    sensor_fleet._warm.update(until=0.0, value=False)
    assert sensor_fleet.audio_hash_sessions(Broken(), _payload("x"), "s") is None
    assert sensor_fleet.audio_hash_sessions(None, _payload("x"), "s") is None


def test_api_sets_the_audio_count_for_phones(db, monkeypatch):
    from starlette.requests import Request

    from api_service import database, main

    monkeypatch.setattr(database, "get_db", lambda: db)
    _fill(db)

    def request(ua):
        return Request({"type": "http", "method": "POST", "path": "/api/v1/telemetry", "query_string": b"",
                        "headers": [(b"host", b"partner.example"), (b"user-agent", ua.encode())],
                        "client": ("203.0.113.7", 1234)})

    phone = {**_payload("fresh"), "sessionId": "p", "client_ip": "203.0.113.7"}
    main._attach_server_context(request(ANDROID), phone, link=True)
    assert phone["_server_headers"]["audio_hash_sessions"] == 0
    desktop = {**_payload("fresh", WINDOWS), "sessionId": "d", "client_ip": "203.0.113.7"}
    main._attach_server_context(request(WINDOWS), desktop, link=True)
    assert desktop["_server_headers"]["audio_hash_sessions"] is None


# ---- decisions ----

def test_fixtures_cover_both_directions():
    ours = MOBILE_RULE_CASES[41:47]
    assert [(v, s, b) for v, s, b, _ in ours] == [
        ("BOT", "FINAL", "emulated_phone"), ("BOT", "FINAL", "emulated_phone"), ("BOT", "FINAL", "emulated_phone"),
        ("SUSPECT", "FINAL", "mobile_risk"), ("SUSPECT", "FINAL", "mobile_risk"), ("HUMAN", "FINAL", "mobile_light_touch")]


def test_bot_verdict_explains_both_channels_and_locks():
    from api_service.main import ensemble_detector
    result = ensemble_detector.predict(copy.deepcopy(MOBILE_RULE_CASES[41][3]))
    assert (result["verdict"], result["breakdown"]["automation_rule"]) == ("BOT", "emulated_phone_v1")
    assert result["breakdown"]["verdict_locked"] is True
    reason = " ".join(result["reasons"]).lower()
    assert "perfectly level" in reason and "audio novel" in reason


def test_a_real_motion_summary_never_convicts_whatever_else_is_wrong():
    from api_service.main import ensemble_detector
    for motion in (_TABLE_MOTION, _HAND_MOTION):
        payload = copy.deepcopy(MOBILE_RULE_CASES[41][3])
        payload["mouse"]["presence"]["motion"] = dict(motion)
        payload["fingerprint"]["timezone"] = "America/New_York"
        payload["_server_headers"]["ip_country"] = "VN"
        result = ensemble_detector.predict(payload)
        assert result["verdict"] == "SUSPECT", motion
        assert result["breakdown"]["automation_rule"] is None


def test_emulated_motion_alone_is_never_bot():
    from api_service.main import ensemble_detector
    payload = copy.deepcopy(MOBILE_RULE_CASES[41][3])
    payload["_server_headers"]["audio_hash_sessions"] = 2
    result = ensemble_detector.predict(payload)
    assert (result["verdict"], result["decision_state"]) == ("SUSPECT", "FINAL")
    assert dict(_EMULATED_MOTION)["tiltDeg"] == 0.0


def test_policy_version():
    from core_ml.models.ensemble import DECISION_POLICY_VERSION
    assert DECISION_POLICY_VERSION in ("36", "37")
