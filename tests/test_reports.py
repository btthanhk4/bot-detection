"""Website reports: exact totals, reasons and bot sources for a period."""

from datetime import datetime, timedelta, timezone

import mongomock
import pytest
from fastapi.testclient import TestClient

from api_service import reports

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
READ = {"X-Read-Token": "read-secret"}


@pytest.fixture
def db():
    return mongomock.MongoClient(tz_aware=True)["bot_detection"]


def add(db, sid, verdict, *, site="shop", age_hours=1, ip="203.0.113.1", state="FINAL", **breakdown):
    created = NOW - timedelta(hours=age_hours)
    doc = {"sessionId": sid, "verdict": verdict, "decision_state": state, "client_ip": ip,
           "created_at": created, "updated_at": created + timedelta(seconds=30), "breakdown": breakdown,
           "fingerprint": {"userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, "pageUrl": "https://shop.vn/"}
    if site:
        doc["site_id"] = site
    db["detection_results"].insert_one(doc)


@pytest.fixture(autouse=True)
def no_geoip(monkeypatch):
    places = {"203.0.113.1": {"country": "Vietnam", "country_code": "VN", "isp": "Viettel"},
              "198.51.100.7": {"country": "United States", "country_code": "US", "isp": "Google"}}
    monkeypatch.setattr(reports.geoip, "lookup", lambda ip: places.get(ip, {}))


def test_summary_counts_the_period_and_the_site(db):
    add(db, "h1", "HUMAN")
    add(db, "h2", "HUMAN", age_hours=30)
    add(db, "d1", "SUSPECT", state="INSUFFICIENT_EVIDENCE", decision_deferred=True)
    add(db, "s1", "SUSPECT", decision_basis="desktop_risk", desktop_risk={"codes": ["FRAME_LOCKED_POINTER", "CDP_ATTACHED"]})
    add(db, "b1", "BOT", decision_basis="automation_marker", automation_rule="automation_marker_v1")
    add(db, "b2", "BOT", decision_basis="automation_marker", automation_rule="automation_marker_v1", ip="198.51.100.7")
    add(db, "b3", "BOT", decision_basis="automation_marker", automation_rule="automation_marker_v1", ip="198.51.100.7",
        desktop_risk={"codes": ["CDP_ATTACHED"]})
    add(db, "old", "BOT", age_hours=24 * 40)
    add(db, "other", "BOT", site="blog")

    day = reports.summary(db, site_filter={"site_id": "shop"}, days=1, now=NOW)
    assert day["totals"] == {"sessions": 6, "human": 1, "bot": 3, "suspect": 1, "insufficient": 1}
    week = reports.summary(db, site_filter={"site_id": "shop"}, days=7, now=NOW)
    assert week["totals"]["sessions"] == 7 and week["totals"]["human"] == 2

    reasons = {(r["verdict"], r["decision_basis"], r["code"]): r["sessions"] for r in day["reasons"]}
    assert reasons == {("BOT", "automation_marker", None): 3, ("SUSPECT", "desktop_risk", "FRAME_LOCKED_POINTER"): 1}
    assert [(row["client_ip"], row["sessions"]) for row in day["bot_ips"]] == [("198.51.100.7", 2), ("203.0.113.1", 1)]
    assert day["bot_ips"][0]["geo"]["isp"] == "Google"
    assert day["bot_countries"] == [{"code": "US", "name": "United States", "sessions": 2},
                                    {"code": "VN", "name": "Vietnam", "sessions": 1}]
    assert day["bot_ip_count"] == 2
    every_site = reports.summary(db, site_filter={}, days=1, now=NOW)
    assert every_site["totals"]["bot"] == 4


def test_export_lists_sessions_oldest_first_and_reports_truncation(db, monkeypatch):
    add(db, "a", "HUMAN", age_hours=5)
    add(db, "b", "BOT", age_hours=2, decision_basis="automation_marker")
    add(db, "c", "BOT", site=None)
    out = reports.sessions(db, site_filter={"site_id": "shop"}, days=1, now=NOW)
    assert [row["sessionId"] for row in out["sessions"]] == ["a", "b"]
    assert out["truncated"] is False
    first = out["sessions"][0]
    assert isinstance(first["created_at"], int) and first["updated_at"] - first["created_at"] == 30000
    assert first["fingerprint"]["userAgent"].startswith("Mozilla") and first["geo"]["isp"] == "Viettel"
    assert "mouse_trajectory" not in first
    monkeypatch.setattr(reports, "EXPORT_LIMIT", 1)
    assert reports.sessions(db, site_filter={}, days=1, now=NOW)["truncated"] is True


def test_report_endpoints_need_read_access_and_valid_periods(db, monkeypatch):
    from api_service import main

    monkeypatch.setattr("api_service.database.get_db", lambda: db)
    monkeypatch.setattr(main.settings, "READ_TOKEN", "read-secret")
    add(db, "b1", "BOT", age_hours=0)
    client = TestClient(main.app)
    assert client.get("/api/v1/reports/summary").status_code == 401
    ok = client.get("/api/v1/reports/summary", params={"days": 1, "site": "shop"}, headers=READ)
    assert ok.status_code == 200 and ok.json()["totals"]["bot"] == 1
    assert client.get("/api/v1/reports/summary", params={"days": 3}, headers=READ).status_code == 422
    assert client.get("/api/v1/reports/summary", params={"site": "Bad!"}, headers=READ).status_code == 422
    exported = client.get("/api/v1/reports/sessions", params={"days": 30}, headers=READ)
    assert exported.status_code == 200 and [row["sessionId"] for row in exported.json()["sessions"]] == ["b1"]
