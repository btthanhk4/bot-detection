"""Policy 37: a device configuration seen 30+ times in a day without a single interaction."""

import copy
from datetime import datetime, timedelta, timezone

import mongomock
import pytest

from api_service import sensor_fleet
from core_ml.features.server_context import server_context_codes
from core_ml.release_cases import MOBILE_RULE_CASES

ANDROID = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) "
           "Chrome/156.0.0.0 Mobile Safari/537.36")
WINDOWS = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"


@pytest.mark.parametrize("sessions, interactive, fires", [
    (30, 0, True), (200, 0, True), (29, 0, False), (30, 1, False), (80, 5, False),
    (None, 0, False), (30, None, False), (True, 0, False), (30, False, False), (30.0, 0, False),
])
def test_inert_cohort_code(sessions, interactive, fires):
    codes = server_context_codes({"_server_headers": {"cohort_sessions": sessions, "cohort_interactive": interactive}})
    assert ("INERT_COHORT" in codes) is fires


@pytest.fixture
def db():
    database = mongomock.MongoClient(tz_aware=True)["bot_detection"]
    sensor_fleet._memo.values.clear()
    return database


def _add(db, n, visitor="cfg-1", touches=0, moves=0, age_hours=1.0, start=0):
    now = datetime.now(timezone.utc)
    db["detection_results"].insert_many([
        {"sessionId": f"{visitor}-{start + i}", "visitorId": visitor, "created_at": now - timedelta(hours=age_hours),
         "breakdown": {"touch": {"gestures_total": touches}}, "mouse_stats": {"move_point_count": moves}}
        for i in range(n)])


def test_cohort_activity_counts_sessions_and_interactions(db):
    _add(db, 40)
    assert sensor_fleet.cohort_activity(db, {"visitorId": "cfg-1"}, "new") == (40, 0)
    _add(db, 1, touches=2, start=100)
    sensor_fleet._memo.values.clear()
    assert sensor_fleet.cohort_activity(db, {"visitorId": "cfg-1"}, "new") == (41, 1)
    _add(db, 1, visitor="cfg-2", moves=30)
    assert sensor_fleet.cohort_activity(db, {"visitorId": "cfg-2"}, "new") == (1, 1), "25+ pointer moves interact"


def test_cohort_activity_excludes_itself_old_sessions_and_other_configs(db):
    _add(db, 10)
    _add(db, 50, age_hours=25, start=100)
    _add(db, 50, visitor="cfg-other")
    assert sensor_fleet.cohort_activity(db, {"visitorId": "cfg-1"}, "cfg-1-0") == (9, 0)


def test_cohort_activity_without_a_visitor_or_database(db):
    assert sensor_fleet.cohort_activity(db, {}, "x") is None
    assert sensor_fleet.cohort_activity(db, {"visitorId": ""}, "x") is None
    assert sensor_fleet.cohort_activity(None, {"visitorId": "cfg-1"}, "x") is None

    class Broken:
        def __getitem__(self, name):
            raise RuntimeError("down")
    assert sensor_fleet.cohort_activity(Broken(), {"visitorId": "cfg-1"}, "x") is None


def test_api_counts_cohorts_for_phones_only(db, monkeypatch):
    from starlette.requests import Request

    from api_service import database, main

    monkeypatch.setattr(database, "get_db", lambda: db)
    _add(db, 35)

    def request(ua):
        return Request({"type": "http", "method": "POST", "path": "/api/v1/telemetry", "query_string": b"",
                        "headers": [(b"host", b"partner.example"), (b"user-agent", ua.encode())],
                        "client": ("203.0.113.7", 1234)})

    phone = {"sessionId": "p", "visitorId": "cfg-1", "client_ip": "203.0.113.7", "fingerprint": {"userAgent": ANDROID}}
    main._attach_server_context(request(ANDROID), phone, link=True)
    assert (phone["_server_headers"]["cohort_sessions"], phone["_server_headers"]["cohort_interactive"]) == (35, 0)
    desktop = {"sessionId": "d", "visitorId": "cfg-1", "client_ip": "203.0.113.7", "fingerprint": {"userAgent": WINDOWS}}
    main._attach_server_context(request(WINDOWS), desktop, link=True)
    assert desktop["_server_headers"]["cohort_sessions"] is None


def test_fixtures_cover_both_directions():
    ours = MOBILE_RULE_CASES[-4:]
    assert [(v, s, b) for v, s, b, _ in ours] == [
        ("SUSPECT", "FINAL", "mobile_risk"), ("SUSPECT", "INSUFFICIENT_EVIDENCE", None),
        ("SUSPECT", "INSUFFICIENT_EVIDENCE", None), ("HUMAN", "FINAL", "mobile_light_touch")]


def test_inert_cohort_never_touches_a_phone_that_interacted():
    from api_service.main import ensemble_detector
    payload = copy.deepcopy(MOBILE_RULE_CASES[-1][3])
    result = ensemble_detector.predict(payload)
    assert result["verdict"] == "HUMAN"
    assert "INERT_COHORT" not in result["breakdown"]["mobile_human"]["missing"]


def test_inert_cohort_makes_an_untouched_phone_suspect_not_bot():
    from api_service.main import ensemble_detector
    payload = copy.deepcopy(MOBILE_RULE_CASES[-4][3])
    payload["_server_headers"]["cohort_sessions"] = 150
    result = ensemble_detector.predict(payload)
    assert (result["verdict"], result["decision_state"]) == ("SUSPECT", "FINAL")
    assert result["breakdown"]["mobile_human"]["risk"] == ["INERT_COHORT"]
    assert "NO_INTERACTION_CLEAN" not in result["breakdown"]["suspect_reason_codes"]


def test_policy_version():
    from core_ml.models.ensemble import DECISION_POLICY_VERSION
    assert DECISION_POLICY_VERSION == "37"
