"""Fingerprint reference labels: storing event ids, fetching verdicts, the served collector, reporting."""

from datetime import datetime, timedelta, timezone

import mongomock
import pytest

from api_service import reference
from tests.test_sites import api, db, empty_registry, telemetry  # noqa: F401 (fixtures)

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(reference.settings, "FINGERPRINT_PUBLIC_KEY", "99VTEqzCIhwGMEQPP2yt")
    monkeypatch.setattr(reference.settings, "FINGERPRINT_SECRET_KEY", "secret-test")
    monkeypatch.setattr(reference.settings, "FINGERPRINT_SAMPLE_RATE", 0.25)


def store(mdb, sid, verdict="HUMAN", state="FINAL", event="1731.ev-"):
    mdb["detection_results"].insert_one({"sessionId": sid, "verdict": verdict, "decision_state": state})
    if event:
        reference.record_event(mdb, sid, event + sid, now=NOW)


def test_only_the_first_valid_event_of_a_session_is_kept():
    mdb = mongomock.MongoClient(tz_aware=True)["t"]
    mdb["detection_results"].insert_one({"sessionId": "s1"})
    assert not reference.record_event(mdb, "s1", "bad id with spaces", now=NOW)
    assert reference.record_event(mdb, "s1", "1731.first", now=NOW)
    assert not reference.record_event(mdb, "s1", "1731.second", now=NOW)
    ref = mdb["detection_results"].find_one({"sessionId": "s1"})["reference"]["fingerprint"]
    assert (ref["event_id"], ref["status"]) == ("1731.first", "pending")


def test_poll_accepts_only_events_linked_to_the_session():
    mdb = mongomock.MongoClient(tz_aware=True)["t"]
    for sid in ("ok", "other", "late"):
        store(mdb, sid)
    answers = {
        "1731.ev-ok": (200, {"bot": "bad", "linked_id": "ok", "bot_info": {"category": "automation", "confidence": "high"}}),
        "1731.ev-other": (200, {"bot": "not_detected", "linked_id": "someone-else"}),
        "1731.ev-late": (404, {"error": {"code": "event_not_found"}}),
    }
    later = NOW + timedelta(minutes=1)
    outcome = reference.poll_pending(mdb, fetch=lambda eid: answers[eid], now=later, pause=0)
    assert outcome == {"done": 1, "mismatch": 1, "retry": 1, "failed": 0}
    refs = {d["sessionId"]: d["reference"]["fingerprint"] for d in mdb["detection_results"].find()}
    assert (refs["ok"]["status"], refs["ok"]["bot"], refs["ok"]["bot_category"]) == ("done", "bad", "automation")
    assert refs["other"]["status"] == "mismatch" and "bot" not in refs["other"]
    assert refs["late"]["status"] == "pending" and refs["late"]["next_at"] > later


def test_an_event_that_never_appears_is_given_up():
    mdb = mongomock.MongoClient(tz_aware=True)["t"]
    store(mdb, "gone")
    now = NOW
    for _ in range(reference.MAX_ATTEMPTS):
        now += timedelta(days=1)
        reference.poll_pending(mdb, fetch=lambda eid: (404, None), now=now, pause=0)
    ref = mdb["detection_results"].find_one({"sessionId": "gone"})["reference"]["fingerprint"]
    assert (ref["status"], ref["attempts"]) == ("not_found", reference.MAX_ATTEMPTS)


def test_v3_event_shape_is_understood():
    fields = reference._bot_fields({"products": {"botd": {"data": {"bot": {"result": "notDetected"}}},
                                                 "identification": {"data": {"linkedId": "s"}}}})
    assert (fields["bot"], fields["linked_id"]) == ("not_detected", "s")


def test_report_counts_agreement_and_kappa():
    mdb = mongomock.MongoClient(tz_aware=True)["t"]
    rows = [("b1", "BOT", "bad"), ("b2", "BOT", "bad"), ("b3", "BOT", "not_detected"),
            ("h1", "HUMAN", "not_detected"), ("h2", "HUMAN", "not_detected"), ("h3", "HUMAN", "bad"),
            ("s1", "SUSPECT", "bad")]
    for sid, verdict, bot in rows:
        store(mdb, sid, verdict=verdict)
        mdb["detection_results"].update_one({"sessionId": sid}, {"$set": {
            "reference.fingerprint.status": "done", "reference.fingerprint.bot": bot}})
    result = reference.report(mdb)
    assert result["decided_pairs"] == 6
    assert (result["both_bot"], result["datacat_bot_only"], result["fingerprint_bot_only"], result["neither"]) == (2, 1, 1, 2)
    assert result["agreement"] == round(4 / 6, 4)
    assert result["kappa"] == round((4 / 6 - 0.5) / 0.5, 4)
    assert result["crosstab"]["SUSPECT"] == {"bad": 1}


def test_served_collector_carries_the_key_only_when_enabled(api, enabled, monkeypatch):  # noqa: F811
    on = api.get("/bot-collector.js")
    assert "99VTEqzCIhwGMEQPP2yt" in on.text and "__DATACAT_FP_KEY__" not in on.text
    assert "Number('0.25')" in on.text
    monkeypatch.setattr(reference.settings, "FINGERPRINT_SAMPLE_RATE", 0.0)
    off = api.get("/bot-collector.js")
    assert "99VTEqzCIhwGMEQPP2yt" not in off.text and "Number('0.0')" in off.text
    assert on.headers["etag"] != off.headers["etag"]


def test_telemetry_records_the_reference_event_when_enabled(api, db, enabled):  # noqa: F811
    payload = telemetry("r1")
    payload["collector"]["referenceEventId"] = "1731400000000.Xy"
    assert api.post("/api/v1/telemetry", json=payload,
                    headers={"Origin": "https://silkmoon.datacat.io.vn"}).status_code == 200
    ref = db["detection_results"].find_one({"sessionId": "r1"})["reference"]["fingerprint"]
    assert (ref["event_id"], ref["status"]) == ("1731400000000.Xy", "pending")
    bad = telemetry("r2")
    bad["collector"]["referenceEventId"] = "not valid!"
    assert api.post("/api/v1/telemetry", json=bad, headers={"Origin": "https://silkmoon.datacat.io.vn"}).status_code == 422


def test_telemetry_ignores_reference_events_when_disabled(api, db):  # noqa: F811
    payload = telemetry("r3")
    payload["collector"]["referenceEventId"] = "1731400000000.Xy"
    assert api.post("/api/v1/telemetry", json=payload,
                    headers={"Origin": "https://silkmoon.datacat.io.vn"}).status_code == 200
    assert "reference" not in db["detection_results"].find_one({"sessionId": "r3"})


def test_review_lists_and_endpoint(api, db, enabled):  # noqa: F811
    READ = {"X-Read-Token": "read-secret"}
    now = datetime.now(timezone.utc)
    rows = [("x1", "HUMAN", "bad"), ("x2", "BOT", "not_detected"), ("x3", "BOT", "good"), ("x4", "BOT", "bad")]
    for sid, verdict, bot in rows:
        db["detection_results"].insert_one({
            "sessionId": sid, "verdict": verdict, "decision_state": "FINAL", "site_id": "shop", "created_at": now,
            "reference": {"fingerprint": {"status": "done", "bot": bot, "event_id": "e." + sid}}})
    kinds = {kind: [r["sessionId"] for r in reference.disagreements(db, kind)] for kind in reference.DISAGREEMENTS}
    assert kinds == {"fingerprint_only": ["x1"], "datacat_only": ["x2"], "good_bot": ["x3"]}
    res = api.get("/api/v1/reference/fingerprint?days=7", headers=READ)
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] and body["statuses"] == {"done": 4}
    assert body["crosstab"]["BOT"] == {"not_detected": 1, "good": 1, "bad": 1}
    assert [r["sessionId"] for r in body["review"]["fingerprint_only"]] == ["x1"]
    assert api.get("/api/v1/reference/fingerprint?days=14", headers=READ).status_code == 422
