"""Ad-click attribution: clickid and t1 of the landing URL, kept per session and reported."""

from datetime import datetime, timedelta, timezone

import mongomock
import pytest
from fastapi.testclient import TestClient

from api_service import clicks, main, reports
from api_service.database import save_detection_result

LANDER = "https://toprewards4u7.online/Download/Downloader/index.html"
NOW = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)
ANALYSIS = {"verdict": "HUMAN", "bot_probability": 0.1, "decision_state": "FINAL", "policy_version": "29"}


@pytest.fixture
def db(monkeypatch):
    database = mongomock.MongoClient(tz_aware=True)["bot_detection"]
    monkeypatch.setattr("api_service.database.get_db", lambda: database)
    return database


@pytest.mark.parametrize("url, expected", [
    (LANDER + "?clickid=dbpj8r797ugs73fe0jng&t1=28628-5fe41363",
     {"click_id": "dbpj8r797ugs73fe0jng", "click_source": "28628-5fe41363"}),
    (LANDER + "?t1=19333-3bf5fe05&utm_source=x&CLICKID=abc_1#top", {"click_id": "abc_1", "click_source": "19333-3bf5fe05"}),
    (LANDER + "?clickid=abc", {"click_id": "abc"}),
    (LANDER + "?t1=zone7", {"click_source": "zone7"}),
    # The network did not fill in its macros, or the value is not a token.
    (LANDER + "?clickid={clickid}&t1={t1}", {}),
    (LANDER + "?clickid=%7Bclickid%7D&t1=%7Bt1%7D", {}),
    (LANDER + "?clickid=a%20b&t1=<script>", {}),
    (LANDER + "?clickid=" + "x" * 129, {}),
    (LANDER + "?clickid=&t1=", {}),
    (LANDER, {}),
    (None, {}),
    (12, {}),
])
def test_click_params(url, expected):
    assert clicks.click_params(url) == expected


def save(sid, url, sequence=1, verdict="HUMAN"):
    return save_detection_result({"sessionId": sid, "visitorId": "v1", "sequence": sequence, "pageUrl": url},
                                 {**ANALYSIS, "verdict": verdict})


def test_a_session_keeps_the_click_of_its_landing_page(db):
    assert save("s1", LANDER + "?clickid=c1&t1=z1")
    # The next page of the visit does not carry the parameters, or carries other ones.
    assert save("s1", "https://toprewards4u7.online/Download/next.html", sequence=2)
    assert save("s1", LANDER + "?clickid=c2&t1=z2", sequence=3)
    doc = db["detection_results"].find_one({"sessionId": "s1"})
    assert (doc["click_id"], doc["click_source"]) == ("c1", "z1")


def test_a_later_page_names_the_click_when_the_first_did_not(db):
    assert save("s2", LANDER)
    assert "click_id" not in db["detection_results"].find_one({"sessionId": "s2"})
    assert save("s2", LANDER + "?clickid=c3&t1=z3", sequence=2)
    doc = db["detection_results"].find_one({"sessionId": "s2"})
    assert (doc["click_id"], doc["click_source"]) == ("c3", "z3")


def test_backfill_attributes_older_sessions_once(db):
    rows = db["detection_results"]
    rows.insert_many([
        {"sessionId": "old1", "landing_url": LANDER + "?clickid=o1&t1=z9"},
        {"sessionId": "old2", "landing_url": LANDER + "?clickid={clickid}"},
        {"sessionId": "old3", "landing_url": LANDER},
        {"sessionId": "new", "landing_url": LANDER + "?clickid=n1", "click_id": "kept"},
    ])
    assert clicks.backfill(db) == 1
    assert rows.find_one({"sessionId": "old1"})["click_source"] == "z9"
    assert "click_id" not in rows.find_one({"sessionId": "old2"})
    assert rows.find_one({"sessionId": "new"})["click_id"] == "kept"
    rows.insert_one({"sessionId": "later", "landing_url": LANDER + "?clickid=l1"})
    assert clicks.backfill(db) == 0  # once: the marker stops a second scan


def add(db, sid, verdict, *, click=None, source=None, state="FINAL", age_minutes=10, **breakdown):
    created = NOW - timedelta(minutes=age_minutes)
    doc = {"sessionId": sid, "site_id": "downloader", "verdict": verdict, "decision_state": state,
           "created_at": created, "updated_at": created, "breakdown": breakdown, "client_ip": "203.0.113.9"}
    if click:
        doc["click_id"] = click
    if source:
        doc["click_source"] = source
    db["detection_results"].insert_one(doc)


def test_report_counts_clicks_by_source(db, monkeypatch):
    monkeypatch.setattr(reports.geoip, "lookup", lambda ip: {})
    add(db, "a", "BOT", click="c1", source="z1", decision_basis="forged_browser", automation_rule="forged_browser_v1")
    add(db, "b", "BOT", click="c2", source="z1", age_minutes=5)
    add(db, "c", "HUMAN", click="c3", source="z1", age_minutes=4)
    add(db, "d", "SUSPECT", click="c4", source="z2", age_minutes=3, decision_basis="client_forgery",
        client_forgery={"codes": ["WEBDRIVER_TAMPERED"], "evidence": ["WEBDRIVER_TAMPERED"]})
    add(db, "e", "SUSPECT", click="c5", source="z2", state="INSUFFICIENT_EVIDENCE", age_minutes=2, decision_deferred=True)
    add(db, "f", "HUMAN")  # no click: not in the click report
    add(db, "g", "BOT", click="c7", age_minutes=60 * 24 * 3)  # outside the day

    day = reports.summary(db, site_filter={"site_id": "downloader"}, days=1, now=NOW)
    assert day["clicks"] == {"sessions": 5, "human": 1, "bot": 2, "suspect": 1, "insufficient": 1}
    assert day["click_sources"] == [
        {"source": "z1", "sessions": 3, "human": 1, "bot": 2, "suspect": 0, "insufficient": 0},
        {"source": "z2", "sessions": 2, "human": 0, "bot": 0, "suspect": 1, "insufficient": 1},
    ]
    recent = day["recent_clicks"]
    assert [row["click_id"] for row in recent] == ["c5", "c4", "c3", "c2", "c1"]
    assert recent[-1]["category"] == "bot" and recent[-1]["automation_rule"] == "forged_browser_v1"
    assert recent[1]["code"] == "WEBDRIVER_TAMPERED"
    assert recent[0]["category"] == "insufficient"
    export = reports.sessions(db, site_filter={"site_id": "downloader"}, days=1, now=NOW)["sessions"]
    assert {row["sessionId"]: row.get("click_id") for row in export}["a"] == "c1"


def test_click_lookup_endpoint(db, monkeypatch):
    monkeypatch.setattr(main.settings, "READ_TOKEN", "read-secret")
    add(db, "a", "SUSPECT", click="c1", source="z1", state="INSUFFICIENT_EVIDENCE", decision_deferred=True)
    add(db, "b", "BOT", click="c1", source="z1", age_minutes=5, decision_basis="forged_browser")
    add(db, "c", "HUMAN", click="c3", source="z2")
    client = TestClient(main.app)
    headers = {"X-Read-Token": "read-secret"}
    body = client.get("/api/v1/clicks/c1", headers=headers).json()
    assert (body["click_id"], body["click_source"], body["verdict"]) == ("c1", "z1", "BOT")
    assert [s["verdict"] for s in body["sessions"]] == ["BOT", "INSUFFICIENT_EVIDENCE"]
    assert client.get("/api/v1/clicks/c3", headers=headers).json()["verdict"] == "HUMAN"
    assert client.get("/api/v1/clicks/nope", headers=headers).status_code == 404
    assert client.get("/api/v1/clicks/%7Bclickid%7D", headers=headers).status_code == 422
    assert client.get("/api/v1/clicks/c1").status_code in (401, 403)
