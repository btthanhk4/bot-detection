"""Reverse-proxy integration: page views, telemetry provenance, action gating, unmonitored traffic.

Client-side detection fails open: a client that never runs the collector, or a script that
posts telemetry without loading the page, is invisible to it. The shop's gateway (nginx)
closes that gap with three hooks (policy 24, see deploy/silkmoon-gateway.conf):

* every HTML request is mirrored to ``/api/v1/pageview`` and the response sets an HttpOnly
  cookie holding that request's id, so telemetry can be tied to a page the gateway served;
* state-changing shop requests (login, register, orders, reviews, AI features) pass an
  ``auth_request`` to ``/api/v1/gate`` first;
* page views that never sent telemetry are turned into sessions ("no telemetry") so
  scrapers, link checkers and blocked collectors show up on the dashboard.

Both internal endpoints require the shared ``X-Datacat-Gateway`` secret.
"""

import hashlib
import hmac
import re
import threading
import time
from datetime import datetime, timedelta, timezone

PAGE_VIEW_COOKIE = "__dc_pv"
_PAGE_VIEW_ID = re.compile(r"^[0-9a-f]{32}$")
PAGE_VIEW_TTL_SECONDS = 7 * 24 * 3600
# A page view whose cookie is presented by this many sessions is a harvested cookie.
PAGE_VIEW_REUSE_LIMIT = 10
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# Codes that say the telemetry did not come from the browser that loaded the page: no
# browser headers, no page the gateway served (or another client's), rewritten timing APIs.
FORGERY_CODES = {"NON_BROWSER_REQUEST", "UNVERIFIED_PAGE_LOAD", "POINTER_API_TAMPERED"}
NO_TELEMETRY_WINDOW_SECONDS = 1800
NO_TELEMETRY_BATCH = 2000

# Named crawlers and link-preview fetchers. A list, not "bot": phone brands (Cubot) and
# in-app browsers (Zalo, Telegram) carry such words in the UA of a person.
_DECLARED_BOT = re.compile(
    r"googlebot|google-inspectiontool|googleother|storebot-google|bingbot|yandexbot|baiduspider|"
    r"duckduckbot|applebot|slurp|ahrefsbot|semrushbot|mj12bot|dotbot|petalbot|bytespider|gptbot|"
    r"chatgpt-user|oai-searchbot|claudebot|claude-user|perplexitybot|ccbot|amazonbot|twitterbot|"
    r"slackbot|discordbot|linkedinbot|telegrambot|pinterestbot|facebookexternalhit|"
    r"meta-externalagent|whatsapp/|skypeuripreview|iframely|embedly|chrome-lighthouse|gtmetrix|"
    r"pingdom|uptimerobot|headlesschrome|\bcrawler\b|\bspider\b", re.I)
_NON_BROWSER = re.compile(
    r"^$|curl/|wget/|python|aiohttp|httpx|go-http-client|java/|okhttp|apache-httpclient|libwww|"
    r"node-fetch|undici|axios/|scrapy|httpie|postmanruntime|insomnia|powershell|winhttp|php/|"
    r"ruby|perl|reqwest|dart:io|nmap|masscan|zgrab|nuclei|sqlmap|nikto", re.I)


_PHONE_UA = re.compile(r"iPhone|iPad|iPod|Android|Mobile", re.I)


def is_phone_user_agent(user_agent: str) -> bool:
    return bool(_PHONE_UA.search(str(user_agent or "")))


def valid_page_view_id(value) -> bool:
    return isinstance(value, str) and bool(_PAGE_VIEW_ID.match(value))


def gateway_authorized(supplied: str, secret: str) -> bool:
    return bool(secret) and bool(supplied) and hmac.compare_digest(supplied.encode(), secret.encode())


def classify_client(user_agent: str) -> str:
    """declared_bot | non_browser | browser, from the request User-Agent only."""
    ua = str(user_agent or "")
    if _NON_BROWSER.search(ua) or "Mozilla/" not in ua:
        return "declared_bot" if _DECLARED_BOT.search(ua) else "non_browser"
    return "declared_bot" if _DECLARED_BOT.search(ua) else "browser"


def record_page_view(db, page_view_id: str, *, ip: str, user_agent: str, host: str, path: str,
                     purpose: str = "", accept_language: bool = False, fetch_dest: str = "") -> bool:
    if db is None or not valid_page_view_id(page_view_id):
        return False
    now = datetime.now(timezone.utc)
    doc = {
        "_id": page_view_id,
        "ts": now,
        "ip": str(ip or "")[:64],
        "ua": str(user_agent or "")[:512],
        "host": str(host or "")[:128],
        "path": str(path or "")[:512],
        # Speculative loads (link prefetch, prerender) do not run page scripts.
        "prefetch": "prefetch" in str(purpose or "").lower(),
        "accept_language": bool(accept_language),
        "fetch_dest": str(fetch_dest or "")[:32],
        "session_id": None,
        "accounted": False,
    }
    try:
        db["page_views"].update_one({"_id": page_view_id}, {"$setOnInsert": doc}, upsert=True)
        return True
    except Exception:
        return False


GATEWAY_LIVE_SECONDS = 600
_gateway_live = {}
_gateway_live_lock = threading.Lock()


def gateway_live(db, host: str) -> bool:
    """Whether the gateway recorded a page view for this host recently (memoised for a minute)."""
    if db is None:
        return False
    key = str(host or "").lower()
    with _gateway_live_lock:
        cached = _gateway_live.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
    try:
        since = datetime.now(timezone.utc) - timedelta(seconds=GATEWAY_LIVE_SECONDS)
        live = db["page_views"].find_one({"host": key, "ts": {"$gte": since}}, {"_id": 1}) is not None
    except Exception:
        live = False
    with _gateway_live_lock:
        _gateway_live[key] = (time.monotonic() + 60, live)
    return live


def page_view_state(db, *, host: str, tracked_hosts, page_view_id, session_id: str, link: bool = True,
                    user_agent: str = None) -> str:
    """untracked | missing | unknown | mismatched | reused | verified for one telemetry request.

    ``mismatched``: the page was loaded by a client with another User-Agent (a scraper that
    fetched the HTML with one tool and posts telemetry claiming to be a browser).
    """
    tracked = bool(tracked_hosts) and str(host or "").lower() in tracked_hosts
    if not valid_page_view_id(page_view_id):
        if not tracked:
            return "untracked"
        # Without page views from the gateway lately it is not mirroring (not deployed yet,
        # or broken): a missing cookie then says nothing about the client.
        return "missing" if gateway_live(db, host) else "gateway_idle"
    if db is None:
        return "unavailable" if tracked else "untracked"
    try:
        views = db["page_views"]
        # Linking does not depend on tracking: the gate needs it as soon as nginx sets cookies.
        if link and session_id:
            views.update_one({"_id": page_view_id, "session_id": None},
                             {"$set": {"session_id": str(session_id)[:128], "linked_at": datetime.now(timezone.utc)}})
        if not tracked:
            return "untracked"
        view = views.find_one({"_id": page_view_id}, {"ua": 1})
        if view is None:
            return "unknown"
        if user_agent is not None and view.get("ua") and view["ua"] != str(user_agent)[:512]:
            return "mismatched"
        claimants = db["detection_results"].count_documents(
            {"page_view_id": page_view_id, "sessionId": {"$ne": str(session_id or "")}}, limit=PAGE_VIEW_REUSE_LIMIT)
        return "reused" if claimants >= PAGE_VIEW_REUSE_LIMIT - 1 else "verified"
    except Exception:
        return "unavailable"


class _VelocityCache:
    """Per-session memo so a heartbeat every few seconds does not re-count every time."""

    def __init__(self, ttl_seconds: float = 60.0, capacity: int = 20000):
        self.ttl = ttl_seconds
        self.capacity = capacity
        self.values = {}
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            hit = self.values.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]
        return None

    def put(self, key, value):
        with self.lock:
            if len(self.values) >= self.capacity:
                now = time.monotonic()
                self.values = {k: v for k, v in self.values.items() if v[0] > now}
                if len(self.values) >= self.capacity:
                    self.values.clear()
            self.values[key] = (time.monotonic() + self.ttl, value)


_velocity_cache = _VelocityCache()


def device_sessions(db, *, visitor_id, ip: str, session_id: str):
    """Sessions in the last hour from this device fingerprint on this address, this one included."""
    if db is None or not visitor_id or not ip:
        return None
    key = (str(visitor_id), str(ip), str(session_id))
    cached = _velocity_cache.get(key)
    if cached is not None:
        return cached
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        others = db["detection_results"].count_documents(
            {"visitorId": str(visitor_id), "client_ip": str(ip), "updated_at": {"$gte": since},
             "sessionId": {"$ne": str(session_id)}}, limit=1000)
    except Exception:
        return None
    value = int(others) + 1
    _velocity_cache.put(key, value)
    return value


def _risk_codes(session) -> set:
    breakdown = session.get("breakdown") or {}
    return set((breakdown.get("desktop_risk") or {}).get("codes") or []) | set(
        (breakdown.get("mobile_human") or {}).get("risk") or [])


def gate_decision(db, *, page_view_id, method: str, strict: bool, grace_seconds: int, user_agent: str = None):
    """(allowed, reason) for one state-changing shop request."""
    if str(method or "").upper() not in WRITE_METHODS:
        return True, "read_only"
    if db is None:
        return True, "unavailable"
    if not valid_page_view_id(page_view_id):
        return False, "no_page_view"
    try:
        view = db["page_views"].find_one({"_id": page_view_id}, {"ts": 1, "session_id": 1, "linked_at": 1, "ua": 1})
        if view is None:
            return False, "no_page_view"
        sessions = list(db["detection_results"].find(
            {"page_view_id": page_view_id},
            {"verdict": 1, "decision_state": 1, "breakdown.decision_basis": 1, "updated_at": 1,
             "breakdown.desktop_risk.codes": 1, "breakdown.mobile_human.risk": 1},
        ).sort("updated_at", -1).limit(5))
    except Exception:
        return True, "unavailable"
    # The browser that loaded the page sends its writes; a tool that fetched the page does not.
    if user_agent is not None and view.get("ua") and view["ua"] != str(user_agent)[:512]:
        return False, "ua_mismatch"
    if not sessions:
        # The collector greets the API the moment it loads, long before a person can submit
        # anything; its first scored telemetry follows within seconds.
        if not view.get("session_id"):
            return False, "no_collector"
        linked = view.get("linked_at") or view.get("ts")
        if linked is not None and linked.tzinfo is None:
            linked = linked.replace(tzinfo=timezone.utc)
        if linked is not None and (datetime.now(timezone.utc) - linked).total_seconds() <= grace_seconds:
            return True, "pending"
        return False, "no_telemetry"
    if any(s.get("verdict") == "BOT" for s in sessions):
        return False, "bot"
    if any(_risk_codes(s) & FORGERY_CODES for s in sessions):
        return False, "forged"
    if strict and any(
        s.get("verdict") == "SUSPECT" and s.get("decision_state") == "FINAL"
        and (s.get("breakdown") or {}).get("decision_basis") in ("desktop_risk", "mobile_risk")
        for s in sessions
    ):
        return False, "risk"
    return True, "ok"


def _no_telemetry_verdict(client: str):
    if client == "declared_bot":
        return "BOT", "declared_crawler", "Declared crawler or link preview: the page was fetched without running scripts"
    if client == "non_browser":
        return "BOT", "non_browser_client", "Non-browser HTTP client: the page was fetched without running scripts"
    return "SUSPECT", "no_telemetry", (
        "Browser user agent, but the page never ran the collector (scripts disabled or blocked, "
        "the tab closed at once, or a script that only fetches HTML)")


def account_unmonitored(db, *, after_seconds: int, policy_version: str, now=None) -> int:
    """Turn page views that never sent telemetry into sessions; returns page views accounted."""
    if db is None:
        return 0
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=after_seconds)
    views = db["page_views"]
    try:
        pending = list(views.find(
            {"session_id": None, "accounted": False, "ts": {"$lt": cutoff}},
            {"ts": 1, "ip": 1, "ua": 1, "host": 1, "path": 1, "prefetch": 1, "accept_language": 1},
        ).sort("ts", 1).limit(NO_TELEMETRY_BATCH))
    except Exception:
        return 0
    # One session per client (address + user agent) until it pauses for 30 minutes, the
    # usual web-analytics session; a later batch continues the session it belongs to.
    gap = timedelta(seconds=NO_TELEMETRY_WINDOW_SECONDS)
    groups, open_groups = [], {}
    for view in pending:
        if view.get("prefetch"):
            continue
        ts = view["ts"] if view["ts"].tzinfo else view["ts"].replace(tzinfo=timezone.utc)
        client_key = (str(view.get("ip") or ""), str(view.get("ua") or ""))
        group = open_groups.get(client_key)
        if group is None or ts - group["last"] > gap:
            group = {"key": client_key, "views": [], "first": ts, "last": ts, "sample": view}
            open_groups[client_key] = group
            groups.append(group)
        group["views"].append(view)
        group["last"] = max(group["last"], ts)
    detections = db["detection_results"]
    for group in groups:
        sample = group["sample"]
        client = classify_client(sample.get("ua"))
        verdict, basis, reason = _no_telemetry_verdict(client)
        ip, ua = group["key"]
        try:
            previous = detections.find_one(
                {"no_telemetry_client": {"$exists": True}, "client_ip": ip, "user_agent": ua,
                 "updated_at": {"$gte": group["first"] - gap}},
                {"sessionId": 1}, sort=[("updated_at", -1)])
        except Exception:
            previous = None
        session_id = previous["sessionId"] if previous else "nojs_" + hashlib.sha256(
            f"{ip}|{ua}|{group['first'].isoformat()}".encode()).hexdigest()[:24]
        paths = sorted({str(v.get("path") or "") for v in group["views"]})[:20]
        try:
            detections.update_one(
                {"sessionId": session_id},
                {
                    "$setOnInsert": {
                        "sessionId": session_id, "visitorId": None, "created_at": group["first"],
                        "client_ip": ip, "user_agent": ua, "no_telemetry_client": client,
                        "pageUrl": f"https://{sample.get('host') or ''}{paths[0] if paths else ''}",
                        "verdict": verdict, "is_bot": verdict == "BOT", "decision_state": "FINAL",
                        "verdict_locked": verdict == "BOT", "bot_probability": 0.0, "confidence": 0.0,
                        "policy_version": str(policy_version), "score_calibrated": False,
                        "mouse_points_captured": 0, "last_action": "no_telemetry",
                        "fingerprint": {"userAgent": sample.get("ua")},
                        "breakdown": {"decision_basis": basis, "no_telemetry": {
                            "client": client, "accept_language": bool(sample.get("accept_language"))}},
                        "reasons": [reason],
                    },
                    "$max": {"updated_at": group["last"]},
                    "$inc": {"no_telemetry_pages": len(group["views"])},
                    "$addToSet": {"no_telemetry_paths": {"$each": paths}},
                },
                upsert=True,
            )
        except Exception:
            continue
    try:
        if pending:
            views.update_many({"_id": {"$in": [v["_id"] for v in pending]}, "session_id": None},
                              {"$set": {"accounted": True}})
    except Exception:
        return 0
    return len(pending)


def ensure_indexes(db) -> bool:
    try:
        db["page_views"].create_index([("ts", 1)], name="ts_1", expireAfterSeconds=PAGE_VIEW_TTL_SECONDS)
        db["page_views"].create_index([("session_id", 1), ("accounted", 1), ("ts", 1)],
                                      name="session_id_1_accounted_1_ts_1")
        db["detection_results"].create_index([("page_view_id", 1)], name="page_view_id_1", sparse=True)
        db["detection_results"].create_index([("visitorId", 1), ("client_ip", 1), ("updated_at", -1)],
                                             name="visitorId_1_client_ip_1_updated_at_-1")
        db["detection_results"].create_index(
            [("client_ip", 1), ("user_agent", 1), ("updated_at", -1)], name="no_telemetry_client",
            partialFilterExpression={"no_telemetry_client": {"$exists": True}})
        return True
    except Exception:
        return False
