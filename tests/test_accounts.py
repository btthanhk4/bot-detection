"""Customer accounts: an administrator creates them; a customer reads only its own websites."""

from datetime import datetime, timedelta, timezone

import mongomock
import pytest
from fastapi.testclient import TestClient

from api_service import auth, main, sites
from api_service.config import settings

CSRF = {"X-Requested-With": "datacat"}
ADMIN_PASSWORD = "Adm1nPassphrase"


@pytest.fixture
def db(monkeypatch):
    database = mongomock.MongoClient(tz_aware=True)["bot_detection"]
    monkeypatch.setattr("api_service.database.get_db", lambda: database)
    monkeypatch.setattr("api_service.research_labels.get_db", lambda: database)
    monkeypatch.setattr(settings, "READ_TOKEN", "read-token")
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "admin-token")
    auth.invalidate_user_cache()
    auth._failures.clear()
    main._rate_limit_records.clear()
    auth.configure_secret("accounts-test-secret")
    sites.create_site(database, name="Shop", site_id="shop", origins=["https://shop.vn"])
    sites.create_site(database, name="Blog", site_id="blog", origins=["https://blog.vn"])
    now = datetime.now(timezone.utc)
    for number, (sid, site, verdict) in enumerate([("s1", "shop", "BOT"), ("s2", "shop", "HUMAN"),
                                                   ("b1", "blog", "BOT"), ("n1", None, "HUMAN")], 1):
        doc = {"sessionId": sid, "verdict": verdict, "decision_state": "FINAL", "client_ip": "203.0.113.9",
               "created_at": now - timedelta(minutes=5), "updated_at": now, "breakdown": {}, "pageUrl": "https://x/"}
        if site:
            doc["site_id"] = site
        database["detection_results"].insert_one(doc)
        database["research_sessions"].insert_one({"_id": sid, "sessionId": sid, "traffic_number": number,
                                                  "first_received_at": 1, "attributed_site_id": site})
    database["research_counters"].insert_one({"_id": "initialized", "ready": True})
    auth.create_user("boss", ADMIN_PASSWORD, "admin")
    yield database
    sites.registry.reload(mongomock.MongoClient()["empty"])
    auth.invalidate_user_cache()


def signed_in(username, password):
    client = TestClient(main.app)
    res = client.post("/api/v1/auth/login", json={"username": username, "password": password}, headers=CSRF)
    assert res.status_code == 200, res.text
    return client


def create(admin, username, role, sites_=None, expect=201):
    res = admin.post("/api/v1/users", json={"username": username, "role": role, "sites": sites_ or []}, headers=CSRF)
    assert res.status_code == expect, res.text
    return res.json()


def customer_client(admin, username="khach@shop.vn", sites_=("shop",)):
    temp = create(admin, username, "customer", list(sites_))["password"]
    client = signed_in(username, temp)
    new_password = "Kh4chHangMoi99"
    assert client.post("/api/v1/auth/password", json={"current_password": temp, "new_password": new_password},
                       headers=CSRF).status_code == 200
    return client


def test_new_account_must_change_its_temporary_password(db):
    admin = signed_in("boss", ADMIN_PASSWORD)
    created = create(admin, "khach@shop.vn", "customer", ["shop"])
    assert len(created["password"]) >= 10 and created["user"]["must_change_password"] is True
    assert "password_hash" not in created["user"]
    client = signed_in("khach@shop.vn", created["password"])
    me = client.get("/api/v1/auth/me").json()
    assert me["must_change_password"] is True and me["sites"] == [{"site_id": "shop", "name": "Shop"}]
    blocked = client.get("/api/v1/stats/summary")
    assert blocked.status_code == 403 and blocked.json()["detail"] == "PASSWORD_CHANGE_REQUIRED"
    assert client.post("/api/v1/auth/password", json={"current_password": created["password"],
                                                      "new_password": "Kh4chHangMoi99"}, headers=CSRF).status_code == 200
    assert client.get("/api/v1/stats/summary").status_code == 200
    assert client.get("/api/v1/auth/me").json()["must_change_password"] is False


def test_customer_reads_only_its_websites(db):
    admin = signed_in("boss", ADMIN_PASSWORD)
    client = customer_client(admin)
    summary = client.get("/api/v1/stats/summary").json()
    assert summary["total"] == 2 and summary["bots"] == 1
    assert client.get("/api/v1/stats/summary", params={"site": "shop"}).json()["total"] == 2
    for site in ("blog", "_none"):
        assert client.get("/api/v1/stats/summary", params={"site": site}).status_code == 403
        assert client.get("/api/v1/reports/summary", params={"site": site}).status_code == 403
    recent = client.get("/api/v1/telemetry/recent").json()
    assert {row["sessionId"] for row in recent["sessions"]} == {"s1", "s2"} and recent["total"] == 2
    traffic = client.get("/api/v1/research/traffic").json()
    assert {row["sessionId"] for row in traffic["sessions"]} == {"s1", "s2"} and traffic["total"] == 2
    report = client.get("/api/v1/reports/summary", params={"days": 1}).json()
    assert report["totals"]["sessions"] == 2
    exported = client.get("/api/v1/reports/sessions", params={"days": 1}).json()
    assert {row["sessionId"] for row in exported["sessions"]} == {"s1", "s2"}
    live = client.get("/api/v1/live").json()
    assert live["sessions"] == 2
    # Another customer's session looks like a missing one.
    assert client.get("/api/v1/sessions/b1/detail").status_code == 404
    assert client.get("/api/v1/telemetry/raw/b1").status_code == 404
    assert client.get("/api/v1/sessions/n1/detail").status_code == 404
    assert client.get("/api/v1/sessions/s1/detail").status_code == 200
    listed = client.get("/api/v1/sites").json()
    assert [site["site_id"] for site in listed["sites"]] == ["shop"]
    assert listed["unregistered_origins"] == [] and listed["unassigned"]["sessions"] == 0
    assert client.get("/api/v1/touch-samples/stats").status_code == 403
    # No administration.
    assert client.get("/api/v1/users").status_code == 401
    assert client.post("/api/v1/sites", json={"name": "X", "origins": ["x.vn"]}, headers=CSRF).status_code == 401
    assert client.delete("/api/v1/sessions/s1", headers=CSRF).status_code == 401


def test_timeline_is_scoped(db, monkeypatch):
    seen = {}

    def fake_timeline(window_minutes, bucket_minutes, utc_offset_minutes=0, site_filter=None):
        seen["filter"] = site_filter
        return {"buckets": []}

    monkeypatch.setattr("api_service.database.get_traffic_timeline", fake_timeline)
    admin = signed_in("boss", ADMIN_PASSWORD)
    client = customer_client(admin, sites_=("shop", "blog"))
    client.get("/api/v1/traffic/timeline")
    assert seen["filter"] == {"site_id": {"$in": ["blog", "shop"]}}
    admin.get("/api/v1/traffic/timeline")
    assert seen["filter"] == {}


def test_staff_viewer_reads_everything_but_changes_nothing(db):
    admin = signed_in("boss", ADMIN_PASSWORD)
    temp = create(admin, "nhanvien", "viewer")["password"]
    client = signed_in("nhanvien", temp)
    client.post("/api/v1/auth/password", json={"current_password": temp, "new_password": "Xem2026Toanbo"}, headers=CSRF)
    assert client.get("/api/v1/stats/summary").json()["total"] == 4
    assert client.get("/api/v1/sessions/b1/detail").status_code == 200
    assert client.post("/api/v1/users", json={"username": "x1x", "role": "admin"}, headers=CSRF).status_code == 401


def test_account_rules(db):
    admin = signed_in("boss", ADMIN_PASSWORD)
    create(admin, "khach@shop.vn", "customer", [], expect=422)
    create(admin, "khach@shop.vn", "customer", ["ghost"], expect=422)
    create(admin, "BOSS", "viewer", expect=409)
    create(admin, "x", "viewer", expect=422)
    # The last administrator cannot be demoted, disabled or deleted, least of all by itself.
    assert admin.patch("/api/v1/users/boss", json={"role": "viewer"}, headers=CSRF).status_code == 409
    assert admin.patch("/api/v1/users/boss", json={"disabled": True}, headers=CSRF).status_code == 409
    assert admin.delete("/api/v1/users/boss", headers=CSRF).status_code == 409
    assert admin.post("/api/v1/users/boss/reset-password", headers=CSRF).status_code == 409
    # With the API admin token (no account), the last-admin rule still holds.
    token = TestClient(main.app)
    assert token.patch("/api/v1/users/boss", json={"disabled": True}, headers={"X-Admin-Token": "admin-token"}).status_code == 409
    # Moving a customer between websites and back.
    create(admin, "khach@shop.vn", "customer", ["shop"])
    moved = admin.patch("/api/v1/users/khach@shop.vn", json={"sites": ["blog"]}, headers=CSRF).json()["user"]
    assert moved["sites"] == ["blog"]
    assert admin.patch("/api/v1/users/khach@shop.vn", json={"sites": []}, headers=CSRF).status_code == 422
    assert admin.patch("/api/v1/users/nobody", json={"disabled": True}, headers=CSRF).status_code == 404
    users = admin.get("/api/v1/users").json()["users"]
    assert [u["username"] for u in users] == ["boss", "khach@shop.vn"]
    assert all("password_hash" not in u for u in users)


def test_disabling_or_resetting_ends_open_sessions(db):
    admin = signed_in("boss", ADMIN_PASSWORD)
    client = customer_client(admin)
    assert client.get("/api/v1/stats/summary").status_code == 200
    assert admin.patch("/api/v1/users/khach@shop.vn", json={"disabled": True}, headers=CSRF).status_code == 200
    auth.invalidate_user_cache()
    assert client.get("/api/v1/stats/summary").status_code == 401
    assert TestClient(main.app).post("/api/v1/auth/login", json={"username": "khach@shop.vn", "password": "Kh4chHangMoi99"},
                                     headers=CSRF).status_code == 401
    admin.patch("/api/v1/users/khach@shop.vn", json={"disabled": False}, headers=CSRF)
    client = signed_in("khach@shop.vn", "Kh4chHangMoi99")
    temp = admin.post("/api/v1/users/khach@shop.vn/reset-password", headers=CSRF).json()["password"]
    auth.invalidate_user_cache()
    assert client.get("/api/v1/stats/summary").status_code == 401
    fresh = signed_in("khach@shop.vn", temp)
    assert fresh.get("/api/v1/auth/me").json()["must_change_password"] is True
    assert admin.delete("/api/v1/users/khach@shop.vn", headers=CSRF).status_code == 200
    auth.invalidate_user_cache()
    assert fresh.get("/api/v1/auth/me").status_code == 401
