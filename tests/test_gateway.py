"""Policy 24: gateway page views, telemetry provenance, action gating and unmonitored traffic."""

from datetime import datetime, timedelta, timezone

import mongomock
import pytest

from api_service import gateway

PV = "0123456789abcdef0123456789abcdef"
OTHER_PV = "fedcba9876543210fedcba9876543210"
CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/156.0.0.0 Safari/537.36")
SHOP = "silkmoon.datacat.io.vn"


@pytest.fixture
def db():
    database = mongomock.MongoClient(tz_aware=True)["bot_detection"]
    gateway.ensure_indexes(database)
    return database


def view(db, pv=PV, *, age=0, ua=CHROME, ip="203.0.113.7", purpose="", linked=None):
    gateway.record_page_view(db, pv, ip=ip, user_agent=ua, host=SHOP, path="/products", purpose=purpose)
    db["page_views"].update_one({"_id": pv}, {"$set": {"ts": datetime.now(timezone.utc) - timedelta(seconds=age),
                                                       "session_id": linked}})


def session(db, session_id, verdict, *, pv=PV, basis="ensemble", state="FINAL", visitor="dev-1",
            ip="203.0.113.7", age=0):
    db["detection_results"].insert_one({
        "sessionId": session_id, "verdict": verdict, "decision_state": state, "page_view_id": pv,
        "visitorId": visitor, "client_ip": ip, "breakdown": {"decision_basis": basis},
        "updated_at": datetime.now(timezone.utc) - timedelta(seconds=age),
    })


@pytest.mark.parametrize("ua, expected", [
    ("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", "declared_bot"),
    ("facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)", "declared_bot"),
    ("curl/8.5.0", "non_browser"),
    ("python-requests/2.32.3", "non_browser"),
    ("", "non_browser"),
    ("Go-http-client/2.0", "non_browser"),
    (CHROME, "browser"),
    # Phone brands and in-app browsers carry words that a naive "bot" match would catch.
    ("Mozilla/5.0 (Linux; Android 10; Cubot X30) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36",
     "browser"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
     "Zalo iOS/599 ZaloTheme/light ZaloLanguage/vi", "browser"),
    ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/154.0.0.0 Safari/537.36",
     "declared_bot"),
])
def test_classify_client(ua, expected):
    assert gateway.classify_client(ua) == expected


def test_page_view_states(db):
    state = lambda **kw: gateway.page_view_state(db, tracked_hosts=[SHOP], session_id="s1", user_agent=CHROME, **kw)  # noqa: E731
    assert gateway.page_view_state(db, host="partner.example", tracked_hosts=[SHOP], page_view_id=None,
                                   session_id="s1") == "untracked"
    assert state(host=SHOP, page_view_id=None) == "missing"
    assert state(host=SHOP, page_view_id="not-a-request-id") == "missing"
    assert state(host=SHOP, page_view_id=PV) == "unknown"
    view(db)
    assert state(host=SHOP, page_view_id=PV) == "verified"
    assert db["page_views"].find_one({"_id": PV})["session_id"] == "s1"
    assert gateway.page_view_state(None, host=SHOP, tracked_hosts=[SHOP], page_view_id=PV,
                                   session_id="s1") == "unavailable"
    # The page was fetched by one client and the telemetry claims to be another.
    assert gateway.page_view_state(db, host=SHOP, tracked_hosts=[SHOP], page_view_id=PV, session_id="s2",
                                   user_agent="curl/8.5.0") == "mismatched"
    assert gateway.page_view_state(db, host=SHOP, tracked_hosts=[SHOP], page_view_id=PV, session_id="s2",
                                   user_agent="") == "mismatched"
    # Before the shop host is tracked, a greeting still links its page (the gate needs it).
    view(db, OTHER_PV)
    assert gateway.page_view_state(db, host=SHOP, tracked_hosts=[], page_view_id=OTHER_PV, session_id="s3",
                                   user_agent=CHROME) == "untracked"
    assert db["page_views"].find_one({"_id": OTHER_PV})["session_id"] == "s3"


def test_one_cookie_presented_by_many_sessions_is_reused(db):
    view(db)
    for index in range(gateway.PAGE_VIEW_REUSE_LIMIT):
        session(db, f"forged-{index}", "SUSPECT")
    assert gateway.page_view_state(db, host=SHOP, tracked_hosts=[SHOP], page_view_id=PV,
                                   session_id="forged-0") == "reused"
    # A person's few tabs share the cookie without being reused.
    db["detection_results"].delete_many({"sessionId": {"$nin": ["forged-0", "forged-1", "forged-2"]}})
    assert gateway.page_view_state(db, host=SHOP, tracked_hosts=[SHOP], page_view_id=PV,
                                   session_id="forged-0") == "verified"


def gate(db, pv=PV, method="POST", strict=False, ua=CHROME):
    return gateway.gate_decision(db, page_view_id=pv, method=method, strict=strict, grace_seconds=60, user_agent=ua)


def test_gate_lets_reads_through_and_fails_open_without_a_database(db):
    assert gate(db, pv=None, method="GET") == (True, "read_only")
    assert gate(None) == (True, "unavailable")


def test_gate_refuses_requests_without_a_page_the_gateway_served(db):
    assert gate(db, pv=None) == (False, "no_page_view")
    assert gate(db, pv=OTHER_PV) == (False, "no_page_view")


def test_gate_requires_the_collector_greeting(db):
    # A scraper that fetched the HTML and posts at once: no collector ever greeted the API.
    view(db, age=1)
    assert gate(db) == (False, "no_collector")
    # The collector greeted the API: the scored telemetry follows within seconds.
    view(db, age=30, linked="s1")
    assert gate(db) == (True, "pending")
    view(db, age=90, linked="s1")
    assert gate(db) == (False, "no_telemetry")


def test_gate_requires_the_browser_that_loaded_the_page(db):
    view(db, age=120, linked="s1")
    session(db, "s1", "HUMAN")
    assert gate(db, ua="python-requests/2.32.3") == (False, "ua_mismatch")
    assert gate(db) == (True, "ok")


def test_gate_refuses_forged_telemetry_on_every_gated_path(db):
    view(db, age=120, linked="s1")
    session(db, "s1", "SUSPECT", basis="desktop_risk")
    db["detection_results"].update_one({"sessionId": "s1"}, {"$set": {
        "breakdown.desktop_risk.codes": ["NON_BROWSER_REQUEST"]}})
    assert gate(db) == (False, "forged")
    db["detection_results"].update_one({"sessionId": "s1"}, {"$set": {
        "breakdown.desktop_risk.codes": ["FRAME_LOCKED_POINTER"]}})
    assert gate(db) == (True, "ok")
    db["detection_results"].update_one({"sessionId": "s1"}, {"$set": {
        "breakdown.desktop_risk.codes": [], "breakdown.mobile_human.risk": ["UNVERIFIED_PAGE_LOAD"],
        "breakdown.decision_basis": "mobile_risk"}})
    assert gate(db) == (False, "forged")


def test_gate_decides_on_the_session_verdict(db):
    view(db, age=120, linked="s1")
    session(db, "s1", "HUMAN")
    assert gate(db) == (True, "ok")
    db["detection_results"].update_one({"sessionId": "s1"}, {"$set": {
        "verdict": "SUSPECT", "breakdown": {"decision_basis": "desktop_risk"}}})
    assert gate(db) == (True, "ok")
    assert gate(db, strict=True) == (False, "risk")
    db["detection_results"].update_one({"sessionId": "s1"}, {"$set": {
        "verdict": "SUSPECT", "decision_state": "INSUFFICIENT_EVIDENCE", "breakdown": {"decision_basis": "insufficient_evidence"}}})
    assert gate(db, strict=True) == (True, "ok")
    session(db, "s2", "BOT")  # another tab of the same cookie
    assert gate(db) == (False, "bot")


def test_unmonitored_page_views_become_sessions(db):
    view(db, PV, age=600, ua="curl/8.5.0", ip="198.51.100.1")
    view(db, "1" * 32, age=500, ua="curl/8.5.0", ip="198.51.100.1")
    view(db, "2" * 32, age=600, ua=CHROME, ip="198.51.100.2")
    view(db, "3" * 32, age=600, ua="Mozilla/5.0 (compatible; bingbot/2.0)", ip="198.51.100.3")
    view(db, "4" * 32, age=600, ua=CHROME, ip="198.51.100.4", purpose="prefetch")
    view(db, "5" * 32, age=600, ua=CHROME, ip="198.51.100.5", linked="real-session")
    view(db, "6" * 32, age=5, ua=CHROME, ip="198.51.100.6")
    accounted = gateway.account_unmonitored(db, after_seconds=120, policy_version="24")
    assert accounted == 5  # both curl views, Chrome, bingbot, the prefetch
    docs = {doc["client_ip"]: doc for doc in db["detection_results"].find()}
    assert set(docs) == {"198.51.100.1", "198.51.100.2", "198.51.100.3"}
    assert (docs["198.51.100.1"]["verdict"], docs["198.51.100.1"]["breakdown"]["decision_basis"]) == (
        "BOT", "non_browser_client")
    assert docs["198.51.100.1"]["no_telemetry_pages"] == 2 and docs["198.51.100.1"]["verdict_locked"] is True
    assert (docs["198.51.100.2"]["verdict"], docs["198.51.100.2"]["breakdown"]["decision_basis"]) == (
        "SUSPECT", "no_telemetry")
    assert docs["198.51.100.3"]["breakdown"]["decision_basis"] == "declared_crawler"
    # Nothing is counted twice; the recent page view still waits for its collector.
    assert gateway.account_unmonitored(db, after_seconds=120, policy_version="24") == 0
    assert db["page_views"].find_one({"_id": "6" * 32})["accounted"] is False
    # The same client later on continues its session; after a 30-minute pause it starts another.
    view(db, "7" * 32, age=200, ua="curl/8.5.0", ip="198.51.100.1")
    gateway.account_unmonitored(db, after_seconds=120, policy_version="24")
    assert db["detection_results"].count_documents({"client_ip": "198.51.100.1"}) == 1
    assert db["detection_results"].find_one({"client_ip": "198.51.100.1"})["no_telemetry_pages"] == 3
    view(db, "8" * 32, age=7200, ua="Wget/1.21", ip="198.51.100.9")
    view(db, "9" * 32, age=600, ua="Wget/1.21", ip="198.51.100.9")
    gateway.account_unmonitored(db, after_seconds=120, policy_version="24")
    assert db["detection_results"].count_documents({"client_ip": "198.51.100.9"}) == 2


def test_device_sessions_count_one_device_on_one_address(db):
    for index in range(4):
        session(db, f"farm-{index}", "SUSPECT", visitor="dev-farm", age=index * 600)
    session(db, "old", "SUSPECT", visitor="dev-farm", age=7200)
    session(db, "elsewhere", "SUSPECT", visitor="dev-farm", ip="192.0.2.9")
    assert gateway.device_sessions(db, visitor_id="dev-farm", ip="203.0.113.7", session_id="new") == 5
    assert gateway.device_sessions(db, visitor_id="dev-farm", ip="203.0.113.7", session_id="farm-0") == 4
    assert gateway.device_sessions(db, visitor_id=None, ip="203.0.113.7", session_id="x") is None


def test_gateway_secret_comparison():
    assert gateway.gateway_authorized("s3cret", "s3cret")
    assert not gateway.gateway_authorized("", "s3cret")
    assert not gateway.gateway_authorized("anything", "")


# ---- API endpoints ----

@pytest.fixture
def api(db, monkeypatch):
    from fastapi.testclient import TestClient
    from api_service import main
    monkeypatch.setattr(main.settings, "GATEWAY_SECRET", "gw-secret")
    monkeypatch.setattr(main.settings, "PAGEVIEW_HOSTS", [SHOP])
    monkeypatch.setattr(main, "_gateway_db", lambda: db)
    return TestClient(main.app)


GW = {"X-Datacat-Gateway": "gw-secret"}


def test_gateway_endpoints_need_the_secret(api, monkeypatch):
    from api_service import main
    assert api.get("/api/v1/pageview", headers={"X-Datacat-PV": PV}).status_code == 403
    assert api.get("/api/v1/gate", headers={"X-Datacat-Gateway": "wrong"}).status_code == 403
    monkeypatch.setattr(main.settings, "GATEWAY_SECRET", "")
    assert api.get("/api/v1/gate", headers=GW).status_code == 404


def test_page_view_mirror_and_gate_round_trip(api, db):
    mirrored = api.get("/api/v1/pageview", headers={
        **GW, "X-Datacat-PV": PV, "X-Original-URI": "/checkout", "Host": SHOP, "User-Agent": CHROME,
        "Accept-Language": "vi-VN"})
    assert mirrored.status_code == 204
    stored = db["page_views"].find_one({"_id": PV})
    assert (stored["path"], stored["host"], stored["accept_language"]) == ("/checkout", SHOP, True)
    assert api.get("/api/v1/pageview", headers={**GW, "X-Datacat-PV": "bad"}).status_code == 422

    write = {**GW, "X-Original-Method": "POST", "X-Original-URI": "/api/v1/orders", "User-Agent": CHROME}
    denied = api.get("/api/v1/gate", headers=write)
    assert (denied.status_code, denied.headers["X-Datacat-Gate"]) == (403, "no_page_view")
    api.cookies.set(gateway.PAGE_VIEW_COOKIE, PV)
    silent = api.get("/api/v1/gate", headers=write)
    assert (silent.status_code, silent.headers["X-Datacat-Gate"]) == (403, "no_collector")
    greeted = api.post("/api/v1/telemetry", json={"sessionId": "sess-1", "action": "hello"},
                       headers={"Host": SHOP, "User-Agent": CHROME})
    assert greeted.status_code == 202
    fresh = api.get("/api/v1/gate", headers=write)
    assert (fresh.status_code, fresh.headers["X-Datacat-Gate"]) == (204, "pending")


def test_collector_greeting_links_the_page_view(api, db):
    view(db, age=40)
    api.cookies.set(gateway.PAGE_VIEW_COOKIE, PV)
    greeted = api.post("/api/v1/telemetry", json={"sessionId": "sess-hello", "action": "hello"},
                       headers={"Host": SHOP, "User-Agent": CHROME})
    assert greeted.status_code == 202
    assert db["page_views"].find_one({"_id": PV})["session_id"] == "sess-hello"
    allowed = api.get("/api/v1/gate", headers={**GW, "X-Original-Method": "POST", "X-Original-URI": "/api/v1/orders",
                                                "User-Agent": CHROME})
    assert allowed.headers["X-Datacat-Gate"] == "pending"


def test_server_context_marks_telemetry_without_a_served_page(api, db, monkeypatch):
    from starlette.requests import Request
    from api_service import main

    def request(cookie=None, host=SHOP):
        headers = [(b"host", host.encode()), (b"user-agent", CHROME.encode())]
        if cookie:
            headers.append((b"cookie", f"{gateway.PAGE_VIEW_COOKIE}={cookie}".encode()))
        return Request({"type": "http", "method": "POST", "path": "/api/v1/telemetry", "headers": headers,
                        "client": ("203.0.113.7", 1234), "query_string": b""})

    data = {"sessionId": "s9", "visitorId": "dev-9", "client_ip": "203.0.113.7"}
    main._attach_server_context(request(), data, link=True)
    assert data["_server_headers"]["page_view"] == "missing"
    assert data["_server_headers"]["device_sessions"] == 1
    view(db)
    data = {"sessionId": "s9", "visitorId": "dev-9", "client_ip": "203.0.113.7"}
    main._attach_server_context(request(PV), data, link=True)
    assert data["_server_headers"]["page_view"] == "verified" and data["_page_view_id"] == PV
    data = {"sessionId": "s9", "visitorId": "dev-9", "client_ip": "203.0.113.7"}
    main._attach_server_context(request(host="partner.example"), data, link=True)
    assert data["_server_headers"]["page_view"] == "untracked"
    # Phones share fingerprints and carrier addresses: no device count for them.
    phone = {"sessionId": "s10", "visitorId": "dev-10", "client_ip": "203.0.113.7",
             "fingerprint": {"userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15"}}
    main._attach_server_context(request(PV), phone, link=True)
    assert phone["_server_headers"]["device_sessions"] is None


# ---- Two-strike lock for BOT verdicts of the mouse models ----

def test_model_bot_locks_on_the_second_snapshot(db, monkeypatch):
    from api_service import database

    monkeypatch.setattr(database, "get_db", lambda: db)
    stamp = [1_800_000_000_000]

    def save(verdict, *, rule_locked=None):
        stamp[0] += 5000
        breakdown = {"decision_basis": "ensemble"}
        if rule_locked is not None:
            breakdown["verdict_locked"] = rule_locked
        database.save_detection_result(
            {"sessionId": "s-two", "visitorId": "v", "timestamp": stamp[0], "received_at": stamp[0]},
            {"verdict": verdict, "decision_state": "FINAL", "breakdown": breakdown})
        return db["detection_results"].find_one({"sessionId": "s-two"})

    first = save("BOT", rule_locked=False)
    assert (first["verdict"], first["verdict_locked"], first["bot_strikes"]) == ("BOT", False, 1)
    later = save("HUMAN", rule_locked=False)
    assert (later["verdict"], later["bot_strikes"]) == ("HUMAN", 1)
    second = save("BOT", rule_locked=False)
    assert (second["verdict"], second["verdict_locked"], second["bot_strikes"]) == ("BOT", True, 2)
    assert save("HUMAN", rule_locked=False)["verdict"] == "BOT"


def test_rule_bot_locks_at_once(db, monkeypatch):
    from api_service import database

    monkeypatch.setattr(database, "get_db", lambda: db)
    database.save_detection_result(
        {"sessionId": "s-rule", "visitorId": "v", "timestamp": 1_800_000_000_000},
        {"verdict": "BOT", "decision_state": "FINAL", "breakdown": {"verdict_locked": True}})
    stored = db["detection_results"].find_one({"sessionId": "s-rule"})
    assert (stored["verdict_locked"], stored["bot_strikes"]) == (True, 0)
