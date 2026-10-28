"""Website registry: origins, attribution by the browser's Origin, filters and the Websites page."""

from datetime import datetime, timedelta, timezone

import mongomock
import pytest
from fastapi.testclient import TestClient

from api_service import gateway, sites

SHOP = "https://shop.example.vn"
BLOG = "https://blog.example.vn"
ADMIN = {"X-Admin-Token": "admin-secret"}
READ = {"X-Read-Token": "read-secret"}


@pytest.fixture
def db():
    return mongomock.MongoClient(tz_aware=True)["bot_detection"]


@pytest.fixture(autouse=True)
def empty_registry():
    sites.registry.reload(mongomock.MongoClient()["empty"])
    yield
    sites.registry.reload(mongomock.MongoClient()["empty"])


@pytest.fixture
def api(db, monkeypatch, tmp_path):
    from api_service import main
    from api_service.spool import TelemetrySpool

    monkeypatch.setattr("api_service.database.get_db", lambda: db)
    monkeypatch.setattr("api_service.research_labels.get_db", lambda: db)
    monkeypatch.setattr(main, "_gateway_db", lambda: db)
    monkeypatch.setattr(main.settings, "ADMIN_TOKEN", "admin-secret")
    monkeypatch.setattr(main.settings, "READ_TOKEN", "read-secret")
    monkeypatch.setattr(main.settings, "TELEMETRY_ALLOWED_ORIGINS", ["https://silkmoon.datacat.io.vn"])
    monkeypatch.setattr(main.settings, "PUBLIC_API_URL", "https://api.datacat.io.vn")
    monkeypatch.setattr(main.settings, "CAPTURE_ENABLED", False)
    monkeypatch.setattr(main, "_spool", TelemetrySpool(tmp_path / "spool.sqlite", main.settings.MAX_BUFFER_SIZE))
    main._rate_limit_records.clear()
    return TestClient(main.app)


def doc(session_id, *, site=None, page=SHOP + "/", verdict="HUMAN", age=0):
    now = datetime.now(timezone.utc) - timedelta(seconds=age)
    row = {"sessionId": session_id, "pageUrl": page, "verdict": verdict, "decision_state": "FINAL",
           "created_at": now, "updated_at": now}
    if site:
        row["site_id"] = site
    return row


@pytest.mark.parametrize("value, expected", [
    ("shop.example.vn", "https://shop.example.vn"),
    ("Shop.Example.VN/", "https://shop.example.vn"),
    ("https://shop.example.vn/products?a=1", "https://shop.example.vn"),
    ("http://localhost:5173", "http://localhost:5173"),
    ("https://shop.example.vn:443", "https://shop.example.vn"),
])
def test_normalize_origin(value, expected):
    assert sites.normalize_origin(value) == expected


def test_international_domains_are_stored_as_browsers_send_them():
    origin = sites.normalize_origin("Cửahàng.vn")
    assert origin.startswith("https://xn--")
    assert origin[len("https://"):].encode("ascii").decode("idna") == "cửahàng.vn"


@pytest.mark.parametrize("value", ["", "ftp://shop.example.vn", "https://user:pw@shop.example.vn", "shop example",
                                   "https://shop.example.vn:99999", "javascript:alert(1)"])
def test_normalize_origin_rejects(value):
    with pytest.raises(ValueError):
        sites.normalize_origin(value)


def test_slug_from_vietnamese_name(db):
    assert sites.slugify("Cửa hàng Đồ gốm Bát Tràng") == "cua-hang-do-gom-bat-trang"
    sites.create_site(db, name="Cửa hàng", origins=[SHOP])
    assert sites.unique_site_id(db, "Cửa hàng") == "cua-hang-2"


def test_origin_decision_follows_registry_then_allowlist(db):
    configured = ["https://silkmoon.datacat.io.vn"]
    registry = sites.registry
    # Nothing configured, nothing registered: every origin (local runs).
    assert registry.origin_decision("https://anything.dev", []) == (True, None)
    sites.create_site(db, name="Shop", origins=[SHOP])
    allowed, site = registry.origin_decision(SHOP, configured)
    assert allowed and site["site_id"] == "shop"
    assert registry.origin_decision("https://silkmoon.datacat.io.vn", configured) == (True, None)
    assert registry.origin_decision("https://evil.dev", configured) == (False, None)
    # Once sites are registered, an empty allowlist no longer means "everyone".
    assert registry.origin_decision("https://evil.dev", []) == (False, None)
    # Server-side callers send no Origin.
    assert registry.origin_decision("", configured) == (True, None)
    sites.update_site(db, "shop", {"status": "paused"})
    allowed, site = registry.origin_decision(SHOP, configured)
    assert not allowed and site["site_id"] == "shop"
    assert not registry.allows_cors(SHOP)


def test_an_origin_belongs_to_one_site(db):
    sites.create_site(db, name="Shop", origins=[SHOP, "www.shop.example.vn"])
    with pytest.raises(LookupError):
        sites.create_site(db, name="Copy", origins=["https://www.shop.example.vn"])
    blog = sites.create_site(db, name="Blog", origins=[BLOG])
    with pytest.raises(LookupError):
        sites.update_site(db, blog["site_id"], {"origins": [BLOG, SHOP]})
    with pytest.raises(LookupError):
        sites.create_site(db, name="Again", site_id="shop", origins=["https://other.vn"])


def test_registering_a_site_attributes_its_earlier_sessions(db):
    db["detection_results"].insert_many([
        doc("old-1"), doc("old-2", page=SHOP + "?utm=1"), doc("blog-1", page=BLOG + "/post"),
        doc("lookalike", page="https://shop.example.vn.evil.dev/"), doc("taken", site="other"),
    ])
    db["research_sessions"].insert_many([{"_id": "old-1", "traffic_number": 1}, {"_id": "blog-1", "traffic_number": 2}])
    sites.create_site(db, name="Shop", origins=[SHOP])
    owner = {row["sessionId"]: row.get("site_id") for row in db["detection_results"].find()}
    assert owner == {"old-1": "shop", "old-2": "shop", "blog-1": None, "lookalike": None, "taken": "other"}
    assert db["research_sessions"].find_one({"_id": "old-1"})["attributed_site_id"] == "shop"
    sites.update_site(db, "shop", {"origins": [SHOP, BLOG]})
    assert db["detection_results"].find_one({"sessionId": "blog-1"})["site_id"] == "shop"


def test_overview_reports_install_state_and_unregistered_traffic(db):
    sites.create_site(db, name="Shop", origins=[SHOP])
    sites.create_site(db, name="Blog", origins=[BLOG])
    sites.create_site(db, name="Paused", origins=["https://paused.vn"], status="paused")
    db["detection_results"].insert_many([
        doc("s1", site="shop", verdict="HUMAN"), doc("s2", site="shop", verdict="BOT"),
        doc("s3", site="shop", verdict="SUSPECT", age=3 * 86400),
        doc("b1", site="blog", age=2 * 86400),
        doc("gone", site="deleted-site"),
        doc("u1", page="https://unknown.vn/a"), doc("u2", page="https://unknown.vn/b"),
        # DATACAT's own dashboard and a shop opened by IP are not websites to register.
        doc("own", page="https://www.datacat.io.vn/dashboard"), doc("ip", page="http://152.42.205.62/"),
    ])
    view = sites.overview(db, collector_base="https://api.datacat.io.vn", own_hosts=["datacat.io.vn"])
    by_id = {site["site_id"]: site for site in view["sites"]}
    shop = by_id["shop"]
    assert (shop["sessions"], shop["sessions_24h"], shop["humans_24h"], shop["bots_24h"]) == (3, 2, 1, 1)
    assert shop["install_state"] == "receiving"
    assert by_id["blog"]["install_state"] == "quiet"
    assert by_id["paused"]["install_state"] == "paused"
    assert 'data-site-id="shop"' in shop["snippet"]
    assert shop["snippet"].startswith('<script defer src="https://api.datacat.io.vn/bot-collector.js"')
    assert [row["site_id"] for row in view["removed_sites"]] == ["deleted-site"]
    assert view["unassigned"]["sessions"] == 4
    assert view["unregistered_origins"] == [
        {"origin": "https://unknown.vn", "sessions": 2, "last_seen": view["unregistered_origins"][0]["last_seen"]}]
    empty = sites.create_site(db, name="New", origins=["https://new.vn"])
    assert {s["site_id"]: s for s in sites.overview(db, collector_base="x")["sites"]}[
        empty["site_id"]]["install_state"] == "waiting"


def test_no_telemetry_sessions_take_the_site_of_their_host(db):
    sites.create_site(db, name="Shop", origins=[SHOP])
    gateway.record_page_view(db, "0123456789abcdef0123456789abcdef", ip="203.0.113.9", user_agent="curl/8.5.0",
                             host="shop.example.vn", path="/", purpose="")
    db["page_views"].update_many({}, {"$set": {"ts": datetime.now(timezone.utc) - timedelta(minutes=10)}})
    resolve = lambda host: (sites.registry.for_host(host) or {}).get("site_id")  # noqa: E731
    assert gateway.account_unmonitored(db, after_seconds=60, policy_version="24", site_for_host=resolve) == 1
    assert db["detection_results"].find_one({"no_telemetry_client": "non_browser"})["site_id"] == "shop"


# ---- API ----

def test_site_management_needs_admin(api):
    body = {"name": "Shop", "origins": [SHOP]}
    assert api.post("/api/v1/sites", json=body, headers=READ).status_code == 401
    created = api.post("/api/v1/sites", json=body, headers=ADMIN)
    assert created.status_code == 201
    assert created.json()["site_id"] == "shop"
    assert 'data-site-id="shop"' in created.json()["snippet"]
    assert api.post("/api/v1/sites", json={"name": "Dup", "origins": [SHOP]}, headers=ADMIN).status_code == 409
    assert api.post("/api/v1/sites", json={"name": "Bad", "origins": ["ftp://x"]}, headers=ADMIN).status_code == 422
    assert api.post("/api/v1/sites", json={"name": "Bad", "origins": []}, headers=ADMIN).status_code == 422
    listed = api.get("/api/v1/sites", headers=READ).json()
    assert [site["site_id"] for site in listed["sites"]] == ["shop"]
    assert listed["collector_base"] == "https://api.datacat.io.vn"
    assert api.patch("/api/v1/sites/shop", json={"status": "paused"}, headers=READ).status_code == 401
    assert api.patch("/api/v1/sites/shop", json={"status": "paused"}, headers=ADMIN).json()["status"] == "paused"
    assert api.patch("/api/v1/sites/none", json={"status": "paused"}, headers=ADMIN).status_code == 404
    assert api.delete("/api/v1/sites/shop", headers=ADMIN).status_code == 200
    assert api.delete("/api/v1/sites/shop", headers=ADMIN).status_code == 404


def test_registered_origin_passes_cors_without_a_restart(api):
    from starlette.applications import Starlette

    from api_service.main import SiteAwareCORSMiddleware

    app = Starlette()
    app.add_middleware(SiteAwareCORSMiddleware, allow_origins=["https://silkmoon.datacat.io.vn"],
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    client = TestClient(app)
    preflight = {"Origin": SHOP, "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "content-type"}
    assert client.options("/x", headers=preflight).status_code == 400
    api.post("/api/v1/sites", json={"name": "Shop", "origins": [SHOP]}, headers=ADMIN)
    allowed = client.options("/x", headers=preflight)
    assert allowed.status_code == 200 and allowed.headers["access-control-allow-origin"] == SHOP
    assert client.options("/x", headers={**preflight, "Origin": "https://silkmoon.datacat.io.vn"}).status_code == 200
    api.patch("/api/v1/sites/shop", json={"status": "paused"}, headers=ADMIN)
    assert client.options("/x", headers=preflight).status_code == 400


def telemetry(session_id, declared_site="shop"):
    return {"sessionId": session_id, "visitorId": "visitor-" + session_id, "timestamp": 1_800_000_000_000,
            "pageUrl": SHOP + "/", "mouse": {"records": []},
            "collector": {"schemaVersion": 1, "sdkVersion": "1.10.0", "pageInstanceId": "p-" + session_id,
                          "studyId": "datacat_live", "siteId": declared_site}}


def test_sessions_are_attributed_by_origin_not_by_the_declared_site(api, db):
    api.post("/api/v1/sites", json={"name": "Shop", "origins": [SHOP]}, headers=ADMIN)
    api.post("/api/v1/sites", json={"name": "Blog", "origins": [BLOG]}, headers=ADMIN)
    assert api.post("/api/v1/telemetry", json=telemetry("t-shop"), headers={"Origin": SHOP}).status_code == 200
    # Blog's page carrying a tag copied from the shop: still the blog's traffic.
    assert api.post("/api/v1/telemetry", json=telemetry("t-blog"), headers={"Origin": BLOG}).status_code == 200
    # A configured origin outside the registry, and a server-side caller: unattributed.
    assert api.post("/api/v1/telemetry", json=telemetry("t-silk"),
                    headers={"Origin": "https://silkmoon.datacat.io.vn"}).status_code == 200
    assert api.post("/api/v1/telemetry", json=telemetry("t-none")).status_code == 200
    rejected = api.post("/api/v1/telemetry", json=telemetry("t-evil"), headers={"Origin": "https://evil.dev"})
    assert rejected.status_code == 403
    owner = {row["sessionId"]: row.get("site_id") for row in db["detection_results"].find()}
    assert owner == {"t-shop": "shop", "t-blog": "blog", "t-silk": None, "t-none": None}
    assert db["research_sessions"].find_one({"_id": "t-blog"})["attributed_site_id"] == "blog"

    api.patch("/api/v1/sites/shop", json={"status": "paused"}, headers=ADMIN)
    paused = api.post("/api/v1/telemetry", json=telemetry("t-shop-2"), headers={"Origin": SHOP})
    assert paused.status_code == 403
    assert paused.json()["detail"] == "Monitoring is paused for this site"


def test_monitoring_endpoints_filter_by_site(api, db, monkeypatch):
    sites.create_site(db, name="Shop", origins=[SHOP])
    db["detection_results"].insert_many([
        doc("a", site="shop", verdict="BOT"), doc("b", site="shop"), doc("c", site="blog"), doc("d")])
    db["research_sessions"].insert_many([
        {"_id": "a", "sessionId": "a", "traffic_number": 1, "first_received_at": 1, "attributed_site_id": "shop"},
        {"_id": "b", "sessionId": "b", "traffic_number": 2, "first_received_at": 2, "attributed_site_id": "shop"},
        {"_id": "d", "sessionId": "d", "traffic_number": 3, "first_received_at": 3}])
    db["research_counters"].insert_one({"_id": "initialized", "ready": True})

    def summary(site=None):
        return api.get("/api/v1/stats/summary", params={"site": site} if site else {}, headers=READ).json()

    assert (summary()["total"], summary("shop")["total"], summary("shop")["bots"], summary("_none")["total"]) == (4, 2, 1, 1)
    recent = api.get("/api/v1/telemetry/recent", params={"site": "shop"}, headers=READ).json()
    assert recent["total"] == 2 and {row["site_id"] for row in recent["sessions"]} == {"shop"}
    seen = {}

    def fake_timeline(window_minutes, bucket_minutes, utc_offset_minutes=0, site_filter=None):
        seen["filter"] = site_filter
        return {"buckets": []}

    monkeypatch.setattr("api_service.database.get_traffic_timeline", fake_timeline)
    api.get("/api/v1/traffic/timeline", params={"site": "blog"}, headers=READ)
    assert seen["filter"] == {"site_id": "blog"}
    api.get("/api/v1/traffic/timeline", headers=READ)
    assert seen["filter"] == {}
    traffic = api.get("/api/v1/research/traffic", params={"site": "shop"}, headers=READ).json()
    assert [row["sessionId"] for row in traffic["sessions"]] == ["b", "a"] and traffic["total"] == 2
    unassigned = api.get("/api/v1/research/traffic", params={"site": "_none"}, headers=READ).json()
    assert [row["sessionId"] for row in unassigned["sessions"]] == ["d"]
    assert api.get("/api/v1/live", params={"site": "shop"}, headers=READ).status_code == 200
    assert api.get("/api/v1/live/online", params={"site": "shop"}, headers=READ).status_code == 200
    assert api.get("/api/v1/stats/summary", params={"site": "Bad Site!"}, headers=READ).status_code == 422
