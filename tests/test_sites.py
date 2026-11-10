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


@pytest.mark.parametrize("value, expected", [
    ("uettrk1.com", "https://uettrk1.com"),
    ("uettrk1.com/", "https://uettrk1.com"),
    ("https://UETTRK1.com/Page1/?utm_source=fb#top", "https://uettrk1.com/page1"),
    ("uettrk1.com//page1//sub/", "https://uettrk1.com/page1/sub"),
    ("https://dantri.com.vn/phap-luat/shark-binh-bi-de-nghi-9-10-nam-tu-20261104090546885.htm",
     "https://dantri.com.vn/phap-luat/shark-binh-bi-de-nghi-9-10-nam-tu-20261104090546885.htm"),
    ("shop.vn/Blog/*", "https://shop.vn/blog/*"),
    ("shop.vn/blog/*/", "https://shop.vn/blog/*"),
    ("shop.vn/*", "https://shop.vn"),
    ("uettrk1.com/khuyến-mãi", "https://uettrk1.com/khuy%e1%ba%bfn-m%c3%a3i"),
    ("uettrk1.com/khuy%E1%BA%BFn-m%C3%A3i", "https://uettrk1.com/khuy%e1%ba%bfn-m%c3%a3i"),
])
def test_a_site_entry_is_a_domain_or_a_page(value, expected):
    assert sites.normalize_scope(value) == expected


def test_a_page_entry_is_that_page_alone_a_group_covers_its_subpages():
    entries = [("", "domain"), ("/page1", "one"), ("/blog/*", "blog"), ("/blog/vip/*", "vip"), ("/blog/vip/a", "a")]
    assert sites.match_path(entries, "/page1") == "one"
    assert sites.match_path(entries, "/page1/x") == "domain"
    assert sites.match_path(entries, "/blog") == "blog"
    assert sites.match_path(entries, "/blog/post") == "blog"
    assert sites.match_path(entries, "/blog/vip/b") == "vip"
    assert sites.match_path(entries, "/blog/vip/a") == "a"
    assert sites.match_path(entries, "/blogs") == "domain"
    assert sites.match_path(entries[1:], "/page10") is None
    assert sites.match_path(entries[1:], "") is None


@pytest.mark.parametrize("registered", [
    "https://uettrk1.com/landers/Download/Pinsubmit_BOT/index.html",
    "https://uettrk1.com/landers/Download/Pinsubmit_BOT/",
    "uettrk1.com/landers/download/pinsubmit_bot",
])
def test_a_directory_and_its_index_file_are_one_page(db, registered):
    lander = "https://uettrk1.com/landers/Download/Pinsubmit_BOT/"
    sites.create_site(db, name="Lander", origins=[registered])
    for page in [lander, lander + "?sub=1", lander + "index.html", lander + "index.htm#x", lander[:-1]]:
        allowed, site = sites.registry.origin_decision("https://uettrk1.com", [], page)
        assert allowed and site["site_id"] == "lander", page
    # Other pages of the folder, and the same folder's sibling, are still separate pages.
    for page in [lander + "thanks.html", lander + "index.html/x", "https://uettrk1.com/landers/Download/"]:
        assert sites.registry.origin_decision("https://uettrk1.com", [], page) == (False, None), page
    with pytest.raises(LookupError):
        sites.create_site(db, name="Twin", origins=[lander + "index.php"])
    import re
    pattern = re.compile(sites.page_url_pattern(sites.normalize_scope(registered)), re.I)
    assert pattern.match(lander + "index.html?x=1") and pattern.match(lander) and not pattern.match(lander + "a.html")


def test_a_site_root_index_file_stays_a_page():
    assert sites.normalize_scope("shop.vn/index.html") == "https://shop.vn/index.html"
    assert sites.normalize_scope("shop.vn/blog/index.html") == "https://shop.vn/blog"
    assert sites.normalize_scope("shop.vn/blog/*") == "https://shop.vn/blog/*"


def test_back_fill_patterns_follow_the_entry_kind():
    import re
    page = re.compile(sites.page_url_pattern("https://shop.vn/a.htm"), re.I)
    assert page.match("https://shop.vn/a.htm?utm=1") and page.match("https://shop.vn/A.htm/")
    assert not page.match("https://shop.vn/a.html") and not page.match("https://shop.vn/a.htm/b")
    group = re.compile(sites.page_url_pattern("https://shop.vn/blog/*"), re.I)
    assert group.match("https://shop.vn/blog") and group.match("https://shop.vn/blog/x")
    assert not group.match("https://shop.vn/blogs")
    assert re.match(sites.page_url_pattern("https://shop.vn"), "https://shop.vn/any/page")


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
    # http/https and www are the same website, so they are the same page too.
    sites.create_site(db, name="Page", origins=["uettrk1.com/page1"])
    for twin in ["http://uettrk1.com/page1", "https://www.uettrk1.com/page1"]:
        with pytest.raises(LookupError):
            sites.create_site(db, name="Twin", origins=[twin])
    sites.create_site(db, name="Other page", origins=["http://www.uettrk1.com/page2"])


@pytest.mark.parametrize("origin, page", [
    ("http://shop.example.vn", "http://shop.example.vn/"),
    ("https://www.shop.example.vn", "https://www.shop.example.vn/cart"),
    ("https://shop.example.vn.", "https://shop.example.vn./"),
    ("https://SHOP.example.vn", "https://SHOP.example.vn/"),
])
def test_scheme_www_case_and_trailing_dot_reach_the_same_site(db, origin, page):
    sites.create_site(db, name="Shop", origins=[SHOP])
    allowed, site = sites.registry.origin_decision(origin, [], page)
    assert allowed and site["site_id"] == "shop"
    assert sites.registry.allows_cors(origin)


def test_a_port_is_another_website(db):
    sites.create_site(db, name="Shop", origins=[SHOP])
    assert sites.registry.origin_decision("https://shop.example.vn:8443", [], "https://shop.example.vn:8443/") == (False, None)


def test_unregistered_pages_continue_the_landing_site_of_the_same_website_only(db):
    page1 = sites.create_site(db, name="Page 1", origins=["uettrk1.com/page1"])
    sites.create_site(db, name="Blog", origins=[BLOG])
    trk = "https://uettrk1.com"
    # A new visitor on a page nobody registered: refused.
    assert sites.registry.origin_decision(trk, [], trk + "/cart") == (False, None)
    # The same session after landing on page 1: kept on page 1.
    allowed, site = sites.registry.origin_decision(trk, [], trk + "/cart", session_site=page1)
    assert allowed and site["site_id"] == "page-1"
    # A session that landed on another website cannot be carried here.
    blog = sites.registry.get("blog")
    assert sites.registry.origin_decision(trk, [], trk + "/cart", session_site=lambda: blog) == (False, None)
    # Paused landing site: refused, and the reason says so.
    sites.update_site(db, "page-1", {"status": "paused"})
    allowed, site = sites.registry.origin_decision(trk, [], trk + "/cart", session_site=sites.registry.get("page-1"))
    assert not allowed and site["site_id"] == "page-1"


def test_requests_without_origin(db):
    # Local runs: nothing registered and nothing configured accepts everything.
    assert sites.registry.unverified_decision(None, None, []) == (True, None)
    sites.create_site(db, name="Shop", origins=[SHOP])
    assert sites.registry.unverified_decision(None, SHOP + "/", []) == (False, None)
    assert sites.registry.unverified_decision("not a url", SHOP + "/", []) == (False, None)
    assert sites.registry.unverified_decision(BLOG + "/", SHOP + "/", []) == (False, None)
    allowed, site = sites.registry.unverified_decision("https://www.shop.example.vn/a?b=1", SHOP + "/x", [])
    assert allowed and site["site_id"] == "shop"
    # An allowlisted origin is accepted without a site, as with an Origin header.
    configured = ["https://silkmoon.datacat.io.vn"]
    assert sites.registry.unverified_decision(configured[0] + "/", configured[0] + "/", configured) == (True, None)


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
        # Registered, but posted without an Origin: not a domain to register again.
        doc("no-origin", page=SHOP + "/cart"),
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
    assert shop["snippet"].startswith('<script async src="https://api.datacat.io.vn/bot-collector.js"')
    assert [row["site_id"] for row in view["removed_sites"]] == ["deleted-site"]
    assert view["unassigned"]["sessions"] == 5
    assert view["unregistered_origins"] == [
        {"origin": "https://unknown.vn", "sessions": 2, "last_seen": view["unregistered_origins"][0]["last_seen"]}]
    empty = sites.create_site(db, name="New", origins=["https://new.vn"])
    assert {s["site_id"]: s for s in sites.overview(db, collector_base="x")["sites"]}[
        empty["site_id"]]["install_state"] == "waiting"


def test_sessions_without_origin_after_registration_are_repaired_once(db):
    sites.create_site(db, name="Shop", origins=[SHOP])
    db["detection_results"].insert_many([
        doc("late", page=SHOP + "/"), doc("other", page="https://unknown.vn/"),
        doc("verified", site="shop"),
    ])
    db["research_sessions"].insert_one({"_id": "late", "traffic_number": 1})
    assert sites.attribute_unverified_history(db) == 1
    late = db["detection_results"].find_one({"sessionId": "late"})
    assert (late["site_id"], late["site_unverified"]) == ("shop", True)
    assert db["research_sessions"].find_one({"_id": "late"})["attributed_site_id"] == "shop"
    assert db["detection_results"].find_one({"sessionId": "other"}).get("site_id") is None
    assert "site_unverified" not in db["detection_results"].find_one({"sessionId": "verified"})
    # Runs once: later sessions without an Origin are judged by the Referer at ingestion.
    db["detection_results"].insert_one(doc("later", page=SHOP + "/"))
    assert sites.attribute_unverified_history(db) == 0
    assert db["detection_results"].find_one({"sessionId": "later"}).get("site_id") is None


def test_no_telemetry_sessions_take_the_site_of_their_host(db):
    sites.create_site(db, name="Shop", origins=[SHOP])
    gateway.record_page_view(db, "0123456789abcdef0123456789abcdef", ip="203.0.113.9", user_agent="curl/8.5.0",
                             host="shop.example.vn", path="/", purpose="")
    db["page_views"].update_many({}, {"$set": {"ts": datetime.now(timezone.utc) - timedelta(minutes=10)}})
    resolve = lambda host, path="": (sites.registry.for_host(host, path) or {}).get("site_id")  # noqa: E731
    assert gateway.account_unmonitored(db, after_seconds=60, policy_version="24", site_for_host=resolve) == 1
    assert db["detection_results"].find_one({"no_telemetry_client": "non_browser"})["site_id"] == "shop"


# ---- API ----

def test_site_remembers_how_it_is_connected(api, db):
    created = api.post("/api/v1/sites", json={"name": "Shop", "origins": [SHOP], "platform": "wordpress"},
                       headers=ADMIN).json()
    assert created["platform"] == "wordpress"
    assert api.post("/api/v1/sites", json={"name": "Blog", "origins": [BLOG], "platform": "joomla"},
                    headers=ADMIN).status_code == 422
    assert api.patch("/api/v1/sites/shop", json={"platform": "gtm"}, headers=ADMIN).json()["platform"] == "gtm"
    assert api.patch("/api/v1/sites/shop", json={"platform": None}, headers=ADMIN).json()["platform"] is None
    # Changing other fields leaves the method alone.
    api.patch("/api/v1/sites/shop", json={"platform": "shopify"}, headers=ADMIN)
    assert api.patch("/api/v1/sites/shop", json={"name": "Shop 2"}, headers=ADMIN).json()["platform"] == "shopify"
    assert api.get("/api/v1/sites", headers=READ).json()["sites"][0]["platform"] == "shopify"
    with pytest.raises(ValueError):
        sites.create_site(db, name="X", origins=["https://x.vn"], platform="joomla")


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
    # A configured origin outside the registry: accepted, unattributed.
    assert api.post("/api/v1/telemetry", json=telemetry("t-silk"),
                    headers={"Origin": "https://silkmoon.datacat.io.vn"}).status_code == 200
    # No Origin and nothing that names a registered page, or a foreign Origin: refused.
    none = api.post("/api/v1/telemetry", json=telemetry("t-none"))
    assert (none.status_code, none.json()["detail"]) == (403, "This page is not registered for monitoring")
    rejected = api.post("/api/v1/telemetry", json=telemetry("t-evil"), headers={"Origin": "https://evil.dev"})
    assert rejected.status_code == 403
    owner = {row["sessionId"]: row.get("site_id") for row in db["detection_results"].find()}
    assert owner == {"t-shop": "shop", "t-blog": "blog", "t-silk": None}
    assert db["research_sessions"].find_one({"_id": "t-blog"})["attributed_site_id"] == "blog"

    api.patch("/api/v1/sites/shop", json={"status": "paused"}, headers=ADMIN)
    paused = api.post("/api/v1/telemetry", json=telemetry("t-shop-2"), headers={"Origin": SHOP})
    assert paused.status_code == 403
    assert paused.json()["detail"] == "Monitoring is paused for this site"


TRK = "https://uettrk1.com"


def page_telemetry(session_id, page, **extra):
    return {**telemetry(session_id), "pageUrl": page, **extra}


def test_pages_of_one_domain_are_independent_sites(api, db):
    assert api.post("/api/v1/sites", json={"name": "Page 1", "origins": ["uettrk1.com/page1"]},
                    headers=ADMIN).status_code == 201
    assert api.post("/api/v1/sites", json={"name": "Page 2", "origins": ["uettrk1.com/page2"]},
                    headers=ADMIN).status_code == 201
    # The same page cannot belong to two sites; the domain and one of its pages can.
    assert api.post("/api/v1/sites", json={"name": "Dup", "origins": ["https://uettrk1.com/Page2/"]},
                    headers=ADMIN).status_code == 409
    origin = {"Origin": TRK}
    for session_id, page in [("p1", TRK + "/page1?utm_source=fb"), ("p2", TRK + "/PAGE2/#form")]:
        assert api.post("/api/v1/telemetry", json=page_telemetry(session_id, page), headers=origin).status_code == 200
    # Pages of the website that are not registered do not send data, the hello included.
    for session_id, page in [("p2-sub", TRK + "/page2/step-2"), ("p10", TRK + "/page10"), ("root", TRK + "/")]:
        assert api.post("/api/v1/telemetry", json=page_telemetry(session_id, page), headers=origin).status_code == 403
    assert api.post("/api/v1/telemetry", json=page_telemetry("p10", TRK + "/page10", action="hello"),
                    headers=origin).status_code == 403
    owner = {row["sessionId"]: row.get("site_id") for row in db["detection_results"].find()}
    assert owner == {"p1": "page-1", "p2": "page-2"}
    assert db["research_sessions"].find_one({"_id": "p2"})["attributed_site_id"] == "page-2"
    assert sites.overview(db, collector_base="https://api.datacat.io.vn")["unregistered_origins"] == []

    # A visitor who follows a link from page 1 to page 2 stays with page 1, where they landed,
    # and so does one who goes on to a page nobody registered (the cart).
    later = page_telemetry("p1", TRK + "/page2", timestamp=1_800_000_060_000)
    assert api.post("/api/v1/telemetry", json=later, headers=origin).status_code == 200
    cart = page_telemetry("p1", TRK + "/cart", timestamp=1_800_000_120_000)
    assert api.post("/api/v1/telemetry", json=cart, headers=origin).status_code == 200
    p1 = db["detection_results"].find_one({"sessionId": "p1"})
    assert (p1["site_id"], p1["pageUrl"], p1["landing_url"]) == ("page-1", TRK + "/cart", TRK + "/page1?utm_source=fb")

    # A domain-wide site takes the pages no page entry covers.
    api.post("/api/v1/sites", json={"name": "Rest", "origins": ["uettrk1.com"]}, headers=ADMIN)
    api.post("/api/v1/telemetry", json=page_telemetry("p3", TRK + "/page3"), headers=origin)
    api.post("/api/v1/telemetry", json=page_telemetry("p2b", TRK + "/page2"), headers=origin)
    owner = {row["sessionId"]: row.get("site_id") for row in db["detection_results"].find()}
    assert (owner["p3"], owner["p2b"]) == ("rest", "page-2")

    # Pausing one page stops that page only.
    api.patch("/api/v1/sites/page-2", json={"status": "paused"}, headers=ADMIN)
    assert api.post("/api/v1/telemetry", json=page_telemetry("p2c", TRK + "/page2"),
                    headers=origin).status_code == 403
    assert api.post("/api/v1/telemetry", json=page_telemetry("p1b", TRK + "/page1"),
                    headers=origin).status_code == 200
    # The gateway's no-telemetry sessions resolve by host and path too.
    assert sites.registry.for_host("uettrk1.com", "/page1/")["site_id"] == "page-1"
    assert sites.registry.for_host("uettrk1.com", "/elsewhere")["site_id"] == "rest"


def test_a_domain_registered_page_by_page_passes_cors(api):
    api.post("/api/v1/sites", json={"name": "Page 1", "origins": ["uettrk1.com/page1"]}, headers=ADMIN)
    assert sites.registry.allows_cors(TRK)
    api.patch("/api/v1/sites/page-1", json={"status": "paused"}, headers=ADMIN)
    assert not sites.registry.allows_cors(TRK)


def test_a_request_without_origin_keeps_its_site_when_referer_and_page_agree(api, db):
    api.post("/api/v1/sites", json={"name": "Shop", "origins": [SHOP]}, headers=ADMIN)
    assert api.post("/api/v1/telemetry", json=telemetry("r-shop"),
                    headers={"Referer": SHOP + "/products?a=1"}).status_code == 200
    # Origin "null" (sandboxed iframe, privacy redirect) is treated like no Origin.
    assert api.post("/api/v1/telemetry", json=telemetry("r-null"),
                    headers={"Origin": "null", "Referer": SHOP + "/"}).status_code == 200
    # Referer and reported page disagree, or name no registered site, or no Referer: refused.
    assert api.post("/api/v1/telemetry", json=telemetry("r-mismatch"),
                    headers={"Referer": BLOG + "/"}).status_code == 403
    assert api.post("/api/v1/telemetry", json={**telemetry("r-elsewhere"), "pageUrl": BLOG + "/"},
                    headers={"Referer": BLOG + "/"}).status_code == 403
    assert api.post("/api/v1/telemetry", json=telemetry("r-noref"), headers={"Origin": "null"}).status_code == 403
    # An Origin, when sent, decides alone: a Referer cannot move it to another site.
    assert api.post("/api/v1/telemetry", json=telemetry("r-origin"),
                    headers={"Origin": "https://silkmoon.datacat.io.vn", "Referer": SHOP + "/"}).status_code == 200
    rows = {row["sessionId"]: row for row in db["detection_results"].find()}
    assert (rows["r-shop"]["site_id"], rows["r-shop"]["site_unverified"]) == ("shop", True)
    assert (rows["r-null"]["site_id"], rows["r-null"]["site_unverified"]) == ("shop", True)
    assert db["research_sessions"].find_one({"_id": "r-shop"})["attributed_site_id"] == "shop"
    assert set(rows) == {"r-shop", "r-null", "r-origin"} and rows["r-origin"].get("site_id") is None
    assert api.post("/api/v1/telemetry", json=telemetry("t-verified"), headers={"Origin": SHOP}).status_code == 200
    assert db["detection_results"].find_one({"sessionId": "t-verified"})["site_unverified"] is False

    api.patch("/api/v1/sites/shop", json={"status": "paused"}, headers=ADMIN)
    paused = api.post("/api/v1/telemetry", json=telemetry("r-paused"), headers={"Referer": SHOP + "/"})
    assert paused.status_code == 403


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


def test_refused_pages_are_logged_once_without_query(api, db, caplog):
    from api_service import main

    main._refused_pages.clear()
    api.post("/api/v1/sites", json={"name": "Shop", "origins": [SHOP + "/sale"]}, headers=ADMIN)
    body = {**telemetry("log-1"), "pageUrl": SHOP + "/cart?token=secret"}
    with caplog.at_level("WARNING", logger="bot_detection.api"):
        for session_id in ("log-1", "log-2"):
            response = api.post("/api/v1/telemetry", json={**body, "sessionId": session_id}, headers={"Origin": SHOP})
            assert response.status_code == 403
    lines = [r.getMessage() for r in caplog.records if "Telemetry refused" in r.getMessage()]
    assert lines == [f"Telemetry refused for an unregistered page: origin={SHOP} path=/cart"]


TEMPLATE = "https://toprewards4u7.online/Download/Downloader/index.html?clickid={clickid}&t1={t1}"


def test_a_page_keeps_the_ad_parameters_written_after_it(db):
    site = sites.create_site(db, name="Downloader", origins=[TEMPLATE, "shop.vn"])
    page = "https://toprewards4u7.online/download/downloader"
    assert site["origins"] == ["https://shop.vn", page]
    assert site["page_queries"] == [{"scope": page, "query": "clickid={clickid}&t1={t1}"}]
    # Traffic still matches the page whatever values the network fills in.
    found = sites.registry.for_page("https://toprewards4u7.online",
                                    "https://toprewards4u7.online/Download/Downloader/index.html?clickid=abc&t1=z9")
    assert found["site_id"] == site["site_id"]
    # Saving the address again keeps the parameters; dropping them clears them; junk is not kept.
    again = sites.update_site(db, site["site_id"], {"origins": [TEMPLATE]})
    assert again["page_queries"] == [{"scope": page, "query": "clickid={clickid}&t1={t1}"}]
    assert sites.update_site(db, site["site_id"], {"origins": [page]})["page_queries"] == []
    odd = sites.update_site(db, site["site_id"], {"origins": [page + "?clickid=%7Bclickid%7D&x=<b>&t1={t1}"]})
    assert odd["page_queries"] == [{"scope": page, "query": "clickid={clickid}&t1={t1}"}]


def test_delete_all_with_a_site_deletes_only_that_sites_sessions(api, db):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    for sid, site in (("a1", "shop"), ("a2", "shop"), ("b1", "blog"), ("u1", None)):
        db["detection_results"].insert_one({"sessionId": sid, "site_id": site, "verdict": "HUMAN", "created_at": now})
        db["research_sessions"].insert_one({"_id": sid, "sessionId": sid, "attributed_site_id": site,
                                            "traffic_number": len(sid) + ord(sid[0]), "revision": 0})
        db["telemetry_captures"].insert_one({"sessionId": sid, "event_id": "e-" + sid})
    # A shop session the model has not scored yet is in the registry only.
    db["research_sessions"].insert_one({"_id": "a3", "sessionId": "a3", "attributed_site_id": "shop", "traffic_number": 99,
                                        "revision": 0})

    body = api.delete("/api/v1/sessions", params={"site": "shop"}, headers=ADMIN).json()
    assert body == {"status": "deleted", "site": "shop", "count": 3}
    assert sorted(d["sessionId"] for d in db["detection_results"].find()) == ["b1", "u1"]
    assert sorted(d["sessionId"] for d in db["telemetry_captures"].find()) == ["b1", "u1"]
    assert {d["sessionId"] for d in db["research_sessions"].find({"deleted": True})} == {"a1", "a2", "a3"}
    # Their open tabs are told to start new sessions, as after a single deletion.
    assert {d["sessionId"] for d in db["deleted_sessions"].find()} == {"a1", "a2", "a3"}

    assert api.delete("/api/v1/sessions", params={"site": "_none"}, headers=ADMIN).json()["count"] == 1
    assert [d["sessionId"] for d in db["detection_results"].find()] == ["b1"]
    assert api.delete("/api/v1/sessions", params={"site": "Bad Site!"}, headers=ADMIN).status_code == 422
    assert api.delete("/api/v1/sessions", params={"site": "blog"}, headers=READ).status_code in (401, 403)
    assert [d["sessionId"] for d in db["detection_results"].find()] == ["b1"]
