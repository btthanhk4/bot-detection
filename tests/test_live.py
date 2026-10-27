"""Live View aggregation: online count, verdict mix, places and networks."""

from datetime import datetime, timedelta, timezone

import pytest

from api_service import geoip, live

NOW = datetime(2026, 10, 27, 6, 0, tzinfo=timezone.utc)
GEO = {
    "42.113.160.186": {"country_code": "VN", "country": "Vietnam", "region": "Hanoi", "city": "Tây Đằng",
                       "latitude": 21.2, "longitude": 105.4, "asn": 18403, "isp": "FPT Telecom Company"},
    "27.72.100.1": {"country_code": "VN", "country": "Vietnam", "region": "Hanoi", "city": "Tây Hồ",
                    "latitude": 21.0, "longitude": 105.8, "asn": 7552, "isp": "Viettel Group"},
    "35.240.1.1": {"country_code": "BE", "country": "Belgium", "region": "Brussels Capital", "city": "Brussels",
                   "latitude": 50.8, "longitude": 4.4, "asn": 396982, "isp": "Google LLC"},
    "10.0.0.1": {"scope": "private"},
}


@pytest.fixture(autouse=True)
def fake_geo(monkeypatch):
    monkeypatch.setattr(geoip, "lookup", lambda ip: GEO.get(ip))


def _row(ip, verdict="HUMAN", state="FINAL", minutes_ago=1):
    return {"client_ip": ip, "verdict": verdict, "decision_state": state, "updated_at": NOW - timedelta(minutes=minutes_ago)}


def test_groups_by_region_and_counts_online_and_verdicts():
    view = live.build_live_view([
        _row("42.113.160.186"),
        _row("27.72.100.1", "BOT", minutes_ago=30),
        _row("35.240.1.1", "SUSPECT", "INSUFFICIENT_EVIDENCE"),
        _row("10.0.0.1"),
        _row(None, "SUSPECT"),
    ], now=NOW)
    assert view["sessions"] == 5 and view["online_now"] == 4
    assert view["verdicts"] == {"human": 2, "bot": 1, "suspect": 1, "pending": 1}
    assert view["unlocated"] == 2
    hanoi = view["points"][0]
    assert (hanoi["region"], hanoi["sessions"], hanoi["online"], hanoi["human"], hanoi["bot"]) == ("Hanoi", 2, 1, 1, 1)
    assert hanoi["lat"] == 21.1 and hanoi["lon"] == 105.6, "mean of the sessions' coordinates"
    assert view["top_locations"][0]["label"] == "Hanoi, Vietnam"
    assert {row["isp"] for row in view["top_isps"]} == {"FPT Telecom Company", "Viettel Group", "Google LLC"}
    assert view["attribution"]["url"] == "https://db-ip.com"


def test_naive_timestamps_are_utc_and_empty_input_is_valid():
    naive = {"client_ip": "42.113.160.186", "verdict": "HUMAN", "updated_at": (NOW - timedelta(seconds=30)).replace(tzinfo=None)}
    assert live.build_live_view([naive], now=NOW)["online_now"] == 1
    empty = live.build_live_view([], now=NOW)
    assert empty["sessions"] == 0 and empty["points"] == [] and empty["top_locations"] == []


def test_live_endpoint_requires_read_access_and_queries_the_window(monkeypatch):
    from fastapi.testclient import TestClient

    from api_service import database, main

    seen = {}

    def fake_sessions(since, limit=20000):
        seen["since"] = since
        return [_row("42.113.160.186")]

    monkeypatch.setattr(database, "get_live_sessions", fake_sessions)
    monkeypatch.setattr(main.settings, "READ_TOKEN", "read-secret")
    client = TestClient(main.app)
    assert client.get("/api/v1/live").status_code == 401
    response = client.get("/api/v1/live?window_minutes=60", headers={"X-Read-Token": "read-secret"})
    assert response.status_code == 200
    assert response.json()["window_minutes"] == 60 and response.json()["sessions"] == 1
    assert timedelta(minutes=59) < datetime.now(timezone.utc) - seen["since"] < timedelta(minutes=61)
    monkeypatch.setattr(database, "get_live_sessions", lambda since, limit=20000: None)
    assert client.get("/api/v1/live", headers={"X-Read-Token": "read-secret"}).status_code == 503
