"""Website registry: the sites DATACAT monitors and the pages they are served from.

An operator registers a site on the dashboard with its entries: a page by its full address
(the default), a group of pages ('shop.vn/blog/*') or a whole domain ('shop.vn'). Pages of one
domain are independent sites, as ad landing pages and articles are. From then on:

* pages on those origins may post telemetry and pass CORS at once, without editing the
  server's environment (origins in ``BOT_TELEMETRY_ORIGINS`` stay allowed as before);
* every session is attributed by the browser's ``Origin`` header, which a page cannot set,
  never by the site id the tag declares (a copied tag would claim another site); among the
  sites of that domain, the page the session landed on picks its entry (see ``match_path``);
* a paused site's pages are refused, so monitoring stops without touching the customer's code.

Lookups on the request path read an in-memory snapshot. The snapshot is reloaded after every
write here and by the maintenance loop, so the CORS middleware never waits on MongoDB.
"""

import ipaddress
import re
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote, unquote, urlsplit

SITE_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
_SITE_ID = re.compile(SITE_ID_PATTERN)
# Query value that selects sessions no registered site claims.
UNASSIGNED = "_none"
SITE_FILTER_PATTERN = r"^(_none|[a-z0-9][a-z0-9_-]{0,63})$"
STATUSES = ("active", "paused")
# How the tag reaches the site's pages; the dashboard shows the matching install steps.
PLATFORMS = ("gtm", "wordpress", "shopify", "haravan", "sapo", "wix", "code", "nginx")
MAX_ORIGINS = 20
# Study id the pilot tag carries; research captures group by it.
STUDY_ID = "datacat_live"
RECEIVING_SECONDS = 24 * 3600
_HOST = re.compile(r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$")
_BACKFILL_CHUNK = 1000


def normalize_origin(value) -> str:
    """'Shop.Example.com', 'https://shop.example.com/path' -> 'https://shop.example.com'."""
    text = str(value or "").strip()
    if not text:
        raise ValueError("Domain is empty")
    if "://" not in text:
        text = "https://" + text
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError as exc:
        raise ValueError(f"{value!r} is not a valid domain") from exc
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or parts.username or parts.password:
        raise ValueError(f"{value!r} must be an http(s) domain")
    host = (parts.hostname or "").rstrip(".")
    try:
        # Browsers send internationalised names in punycode (xn--...).
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError(f"{value!r} is not a valid domain") from exc
    if not _HOST.match(host):
        raise ValueError(f"{value!r} is not a valid domain")
    default_port = 443 if scheme == "https" else 80
    return f"{scheme}://{host}" + (f":{port}" if port and port != default_port else "")


def normalize_path(path) -> str:
    """URL path compared case-insensitively, percent-encoded as browsers send it, without a
    trailing slash ('' for the root)."""
    path = quote(unquote(str(path or "")), safe="/-._~!$&'()*+,;=:@").lower()
    return directory_page(re.sub(r"/{2,}", "/", path).rstrip("/"))


# A directory and its index file are one page: ads link to '/lander/' while the page was
# registered as '/lander/index.html' (or the reverse). The site root keeps '/index.html', so
# registering a home page this way never widens to the whole domain.
_DIRECTORY_INDEX = re.compile(r"/(index|default)\.(html?|php|aspx?|jsp)$")
_DIRECTORY_INDEX_URL = r"(/(index|default)\.(html?|php|aspx?|jsp))?"


def directory_page(path: str) -> str:
    if path.endswith("/*"):
        return path
    return _DIRECTORY_INDEX.sub("", path) or path


# Entry suffix for a group of pages: 'shop.vn/blog/*' is /blog and every page under it.
WILDCARD = "/*"


def normalize_scope(value) -> str:
    """A site's entry, one of:

    * a page, the default: 'dantri.com.vn/phap-luat/bai-viet.htm' is that page alone (query
      and fragment ignored, so ad parameters do not split it);
    * a group of pages: 'shop.vn/blog/*' is /blog and every page under it;
    * a domain: 'shop.vn' is every page of the domain.
    """
    origin = normalize_origin(value)
    text = str(value).strip()
    path = normalize_path(urlsplit(text if "://" in text else "https://" + text).path)
    if path == "/*" or path.endswith(WILDCARD):
        base = path[:-1].rstrip("/")
        return origin + (base + WILDCARD if base else "")
    return origin + path


# URL parameters an ad network appends to a page ('?clickid={clickid}&t1={t1}'): kept as written so
# the operator sees them, and read by api_service.clicks; traffic still matches the page without them.
_PARAM_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
_PARAM_VALUE = re.compile(r"^(\{[A-Za-z0-9_.-]{1,40}\}|[A-Za-z0-9._~:@+-]{0,128})$")
MAX_QUERY_PARAMS = 10


def entry_query(value) -> str:
    """'shop.vn/a.html?clickid={clickid}&t1={t1}' -> 'clickid={clickid}&t1={t1}' ('' when none)."""
    text = str(value or "").strip()
    if "?" not in text:
        return ""
    pairs = []
    for part in text.split("?", 1)[1].split("#", 1)[0].split("&"):
        name, _, raw = part.partition("=")
        name, raw = unquote(name).strip(), unquote(raw).strip()
        if part and _PARAM_NAME.match(name) and _PARAM_VALUE.match(raw) and len(pairs) < MAX_QUERY_PARAMS:
            pairs.append(f"{name}={raw}")
    return "&".join(pairs)


def page_queries(entries) -> list:
    """[{'scope': normalized entry, 'query': its parameters}] for the entries written with some."""
    found = {}
    for entry in entries:
        query = entry_query(entry)
        if query:
            found[normalize_scope(entry)] = query
    return [{"scope": scope, "query": query} for scope, query in sorted(found.items())]


def split_scope(scope: str) -> tuple:
    origin = normalize_origin(scope)
    # Entries saved before directory pages were merged may still end in /index.html.
    return origin, directory_page(scope[len(origin):])


def page_path(page_url) -> str:
    try:
        return normalize_path(urlsplit(str(page_url or "")).path)
    except ValueError:
        return ""


def origin_key(origin) -> str:
    """What makes two origins the same website: host and non-default port. The scheme and a
    leading 'www.' are ignored, so a site registered as 'shop.vn' also matches pages served as
    http://shop.vn or https://www.shop.vn (a common reason for silently lost telemetry)."""
    try:
        parts = urlsplit(normalize_origin(origin))
    except ValueError:
        return ""
    host = (parts.hostname or "").rstrip(".").lower()
    if host.startswith("www."):
        host = host[4:]
    return host + (f":{parts.port}" if parts.port else "")


def scope_key(scope: str) -> str:
    origin, path = split_scope(scope)
    return origin_key(origin) + path


def match_path(paths, path: str):
    """The entry that covers ``path``: its exact page first, then the longest group of pages
    ('/blog/*' covers '/blog' and '/blog/a', not '/blogs'), then the domain (''); None when
    no entry does. ``paths`` is an iterable of (entry path, value)."""
    best, best_rank = None, None
    for entry, value in paths:
        if not entry:
            rank = (0, 0)
        elif entry.endswith(WILDCARD):
            base = entry[:-len(WILDCARD)]
            if path != base and not path.startswith(base + "/"):
                continue
            rank = (1, len(base))
        elif path == entry:
            rank = (2, 0)
        else:
            continue
        if best_rank is None or rank > best_rank:
            best, best_rank = value, rank
    return best


def page_url_pattern(scope: str) -> str:
    """Regex for the page URLs an entry covers, for back-filling stored sessions."""
    origin, path = split_scope(scope)
    host = r"https?://(www\.)?" + re.escape(origin_key(origin))
    if path.endswith(WILDCARD):
        return "^" + host + re.escape(path[:-len(WILDCARD)]) + r"([/?#]|$)"
    if not path:
        return "^" + host + r"([/?#]|$)"
    index = "" if _DIRECTORY_INDEX.search(path) else _DIRECTORY_INDEX_URL
    return "^" + host + re.escape(path) + index + r"/?([?#]|$)"


def origin_host(origin: str) -> str:
    return (urlsplit(origin).hostname or "").lower()


def slugify(name: str) -> str:
    text = unicodedata.normalize("NFD", str(name or "")).replace("đ", "d").replace("Đ", "D")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:40].strip("-") or "site"


def site_filter(site: Optional[str]) -> dict:
    """Mongo condition for a dashboard ``site`` parameter (None: every site)."""
    if not site:
        return {}
    return {"site_id": None if site == UNASSIGNED else site}


class SiteRegistry:
    """Snapshot of the ``sites`` collection: site id -> site, origin -> [(path, site)].

    Several sites may share a domain: 'shop.vn/page1' and 'shop.vn/page2' are independent
    sites, and a page belongs to the entry ``match_path`` picks for it.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._sites = {}
        self._by_origin = {}

    def reload(self, db) -> bool:
        if db is None:
            return False
        try:
            rows = list(db["sites"].find({}, {"_id": 0}))
        except Exception:
            # Keep serving the last good snapshot through a database hiccup.
            return False
        sites = {row["site_id"]: row for row in rows if row.get("site_id")}
        by_origin = {}
        for row in sites.values():
            for scope in row.get("origins") or []:
                try:
                    origin, path = split_scope(scope)
                except ValueError:
                    continue
                by_origin.setdefault(origin_key(origin), []).append((path, row))
        with self._lock:
            self._sites, self._by_origin = sites, by_origin
        return True

    def sites(self) -> dict:
        return self._sites

    def get(self, site_id: str) -> Optional[dict]:
        return self._sites.get(site_id)

    def _entries(self, origin) -> list:
        return self._by_origin.get(origin_key(origin)) or []

    def for_page(self, origin: str, page_url=None) -> Optional[dict]:
        """The site of a page on ``origin``. The path comes from the page URL the collector
        reports, used only when that URL is on the same website (else: the domain-wide site)."""
        path = ""
        if page_url and origin_key(str(page_url).split("?")[0]) == origin_key(origin):
            path = page_path(page_url)
        return match_path(self._entries(origin), path)

    def for_host(self, host: str, path: str = "") -> Optional[dict]:
        return match_path(self._entries("https://" + str(host or "")), normalize_path(path))

    def allows_cors(self, origin: str) -> bool:
        return any(site.get("status") == "active" for _, site in self._entries(origin))

    def _same_website(self, site: Optional[dict], origin) -> bool:
        key = origin_key(origin)
        return bool(site) and any(origin_key(scope) == key for scope in site.get("origins") or [])

    def origin_decision(self, origin: str, configured, page_url=None, session_site=None) -> tuple:
        """(allowed, site) for a request from ``origin``; telemetry is accepted only from
        registered pages.

        * No Origin: not judged here (``/detect`` from a site backend); telemetry goes through
          ``unverified_decision`` instead.
        * A registered page follows its site's status (paused: refused).
        * Another page of a registered website is refused, unless the tab's session already
          belongs to a site of that website: a visitor who landed on a monitored page and
          followed a link stays with that page. ``session_site`` is called only then.
        * Otherwise the configured allowlist applies, and with neither an allowlist nor any
          registered site every origin is accepted (local runs).
        """
        origin = str(origin or "").strip().rstrip("/")
        if not origin:
            return True, None
        if self._entries(origin):
            site = self.for_page(origin, page_url)
            if site is None:
                prior = session_site() if callable(session_site) else session_site
                site = prior if self._same_website(prior, origin) else None
            if site is not None:
                return site.get("status") == "active", site
        if origin in (configured or ()):
            return True, None
        return not configured and not self._sites, None

    def unverified_decision(self, referer, page_url, configured, session_site=None) -> tuple:
        """(allowed, site) for telemetry without a usable Origin (absent, or "null" from a
        sandboxed or privacy-redirected document). The Referer and the reported page must name
        the same website, which is then judged like an Origin; any HTTP client can set both, so
        callers mark the attribution unverified. Neither present or agreeing: refused."""
        if not configured and not self._sites:
            return True, None
        try:
            origin = normalize_origin(str(referer or "").split("?")[0])
        except ValueError:
            return False, None
        if origin_key(origin) != origin_key(str(page_url or "").split("?")[0]):
            return False, None
        return self.origin_decision(origin, configured, page_url, session_site)


registry = SiteRegistry()


def ensure_indexes(db) -> bool:
    try:
        db["sites"].create_index([("site_id", 1)], name="site_id_1", unique=True)
        db["detection_results"].create_index([("site_id", 1), ("updated_at", -1)], name="site_id_1_updated_at_-1")
        db["research_sessions"].create_index([("attributed_site_id", 1), ("traffic_number", -1)],
                                             name="attributed_site_id_1_traffic_number_-1")
        return True
    except Exception:
        return False


def _public(site: dict) -> dict:
    return {key: site.get(key) for key in ("site_id", "name", "origins", "page_queries", "status", "platform",
                                          "contact", "notes", "created_at", "updated_at")}


def _conflicts(db, origins, site_id: Optional[str] = None) -> Optional[tuple]:
    """(entry, other site id) when an entry is already another site's. Entries compare like
    traffic is matched: http and https, with and without 'www.', are the same page."""
    wanted = {scope_key(scope): scope for scope in origins}
    query = {"site_id": {"$ne": site_id}} if site_id else {}
    for other in db["sites"].find(query, {"site_id": 1, "origins": 1}):
        taken = sorted(wanted[key] for key in {scope_key(scope) for scope in other.get("origins") or []} if key in wanted)
        if taken:
            return taken[0], other["site_id"]
    return None


def unique_site_id(db, name: str) -> str:
    base = slugify(name)
    candidate, number = base, 2
    while db["sites"].find_one({"site_id": candidate}, {"_id": 1}):
        candidate = f"{base[:36]}-{number}"
        number += 1
    return candidate


def attribute_history(db, site_id: str, origins) -> int:
    """Give unattributed sessions from these origins to the site (sessions recorded before it
    was registered). Their page URL came through the origin check of that time."""
    detections = db["detection_results"]
    moved = 0
    for origin in origins:
        pattern = page_url_pattern(origin)
        ids = [doc["sessionId"] for doc in detections.find(
            {"site_id": None, "pageUrl": {"$regex": pattern, "$options": "i"}}, {"sessionId": 1})
            if doc.get("sessionId")]
        for start in range(0, len(ids), _BACKFILL_CHUNK):
            chunk = ids[start:start + _BACKFILL_CHUNK]
            moved += detections.update_many(
                {"sessionId": {"$in": chunk}, "site_id": None}, {"$set": {"site_id": site_id}}).modified_count
            db["research_sessions"].update_many(
                {"_id": {"$in": chunk}, "attributed_site_id": None}, {"$set": {"attributed_site_id": site_id}})
    return moved


UNVERIFIED_BACKFILL = "site_unverified_backfill_v1"


def attribute_unverified_history(db) -> int:
    """One-time repair: sessions recorded after their site was registered but posted without an
    Origin header kept no site. Give them the site of their page, marked unverified."""
    counters = db["research_counters"]
    if counters.find_one({"_id": UNVERIFIED_BACKFILL}):
        return 0
    detections = db["detection_results"]
    moved = 0
    for site in db["sites"].find({}, {"site_id": 1, "origins": 1, "created_at": 1}):
        for origin in site.get("origins") or []:
            query = {"site_id": None, "pageUrl": {"$regex": page_url_pattern(origin), "$options": "i"}}
            if site.get("created_at"):
                query["created_at"] = {"$gte": site["created_at"]}
            ids = [doc["sessionId"] for doc in detections.find(query, {"sessionId": 1}) if doc.get("sessionId")]
            for start in range(0, len(ids), _BACKFILL_CHUNK):
                chunk = ids[start:start + _BACKFILL_CHUNK]
                moved += detections.update_many(
                    {"sessionId": {"$in": chunk}, "site_id": None},
                    {"$set": {"site_id": site["site_id"], "site_unverified": True}}).modified_count
                db["research_sessions"].update_many(
                    {"_id": {"$in": chunk}, "attributed_site_id": None},
                    {"$set": {"attributed_site_id": site["site_id"]}})
    counters.update_one({"_id": UNVERIFIED_BACKFILL},
                        {"$set": {"moved": moved, "at": datetime.now(timezone.utc)}}, upsert=True)
    return moved


def create_site(db, *, name: str, origins, site_id: Optional[str] = None, contact: Optional[str] = None,
                notes: Optional[str] = None, status: str = "active", platform: Optional[str] = None) -> dict:
    """Raises ValueError (bad input) or LookupError (id or origin already taken)."""
    entries = list(origins)
    origins = sorted({normalize_scope(origin) for origin in entries})
    if not origins or len(origins) > MAX_ORIGINS:
        raise ValueError(f"A site needs 1 to {MAX_ORIGINS} domains")
    if site_id is not None and not _SITE_ID.match(site_id):
        raise ValueError("Site id may use lowercase letters, digits, '-' and '_'")
    if status not in STATUSES:
        raise ValueError("Unknown status")
    if platform is not None and platform not in PLATFORMS:
        raise ValueError("Unknown platform")
    conflict = _conflicts(db, origins)
    if conflict:
        raise LookupError(f"{conflict[0]} already belongs to site {conflict[1]}")
    site_id = site_id or unique_site_id(db, name)
    if db["sites"].find_one({"site_id": site_id}, {"_id": 1}):
        raise LookupError(f"Site id {site_id} is already used")
    now = datetime.now(timezone.utc)
    site = {"site_id": site_id, "name": name.strip(), "origins": origins, "page_queries": page_queries(entries),
            "status": status, "platform": platform,
            "contact": (contact or "").strip() or None, "notes": (notes or "").strip() or None,
            "created_at": now, "updated_at": now}
    db["sites"].insert_one(dict(site))
    attribute_history(db, site_id, origins)
    registry.reload(db)
    return _public(site)


def update_site(db, site_id: str, changes: dict) -> dict:
    current = db["sites"].find_one({"site_id": site_id})
    if not current:
        raise KeyError(site_id)
    update = {}
    if changes.get("name") is not None:
        update["name"] = changes["name"].strip()
    if changes.get("origins") is not None:
        origins = sorted({normalize_scope(origin) for origin in changes["origins"]})
        if not origins or len(origins) > MAX_ORIGINS:
            raise ValueError(f"A site needs 1 to {MAX_ORIGINS} domains")
        conflict = _conflicts(db, origins, site_id)
        if conflict:
            raise LookupError(f"{conflict[0]} already belongs to site {conflict[1]}")
        update["origins"] = origins
        update["page_queries"] = page_queries(changes["origins"])
    if changes.get("status") is not None:
        if changes["status"] not in STATUSES:
            raise ValueError("Unknown status")
        update["status"] = changes["status"]
    if "platform" in changes:
        if changes["platform"] is not None and changes["platform"] not in PLATFORMS:
            raise ValueError("Unknown platform")
        update["platform"] = changes["platform"]
    for key in ("contact", "notes"):
        if key in changes:
            update[key] = (changes[key] or "").strip() or None
    update["updated_at"] = datetime.now(timezone.utc)
    db["sites"].update_one({"site_id": site_id}, {"$set": update})
    added = set(update.get("origins") or []) - set(current.get("origins") or [])
    if added:
        attribute_history(db, site_id, sorted(added))
    registry.reload(db)
    return _public({**current, **update})


def delete_site(db, site_id: str) -> bool:
    """Remove a site from the registry; its sessions keep their attribution."""
    deleted = db["sites"].delete_one({"site_id": site_id}).deleted_count > 0
    registry.reload(db)
    return deleted


def _install_state(site: dict, last_seen, now) -> str:
    if site.get("status") == "paused":
        return "paused"
    if last_seen is None:
        return "waiting"
    return "receiving" if (now - last_seen).total_seconds() <= RECEIVING_SECONDS else "quiet"


def _as_utc(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def _ms(value) -> Optional[int]:
    value = _as_utc(value)
    return int(value.timestamp() * 1000) if value else None


def site_activity(db, now=None) -> dict:
    """Per site id (None: unattributed): sessions kept, last activity, the last 24 hours by verdict."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(seconds=RECEIVING_SECONDS)
    recent = {"$gte": ["$updated_at", since]}

    def recent_verdict(verdict):
        return {"$sum": {"$cond": [{"$and": [recent, {"$eq": ["$verdict", verdict]}]}, 1, 0]}}

    rows = db["detection_results"].aggregate([
        {"$group": {
            "_id": "$site_id",
            "sessions": {"$sum": 1},
            "last_seen": {"$max": "$updated_at"},
            "sessions_24h": {"$sum": {"$cond": [recent, 1, 0]}},
            "humans_24h": recent_verdict("HUMAN"),
            "bots_24h": recent_verdict("BOT"),
        }},
    ])
    activity = {}
    for row in rows:
        sessions_24h = int(row.get("sessions_24h") or 0)
        humans, bots = int(row.get("humans_24h") or 0), int(row.get("bots_24h") or 0)
        activity[row["_id"]] = {
            "sessions": int(row.get("sessions") or 0),
            "last_seen": _as_utc(row.get("last_seen")),
            "sessions_24h": sessions_24h, "humans_24h": humans, "bots_24h": bots,
            "suspects_24h": max(0, sessions_24h - humans - bots),
        }
    return activity


def _bare_host(host) -> str:
    host = str(host or "").split(":")[0].lower()
    return host[4:] if host.startswith("www.") else host


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def unregistered_origins(db, now=None, limit: int = 10, ignore_hosts=()) -> list:
    """Origins of recent unattributed sessions: sites sending data that nobody registered.

    DATACAT's own hosts (dashboard, collector) and bare IP addresses are left out: that is
    test traffic, not a customer's website to register. So are pages a registered entry
    covers: their unattributed sessions came without a usable Origin, and offering to
    register them again would only fail as a duplicate. A domain registered page by page
    lists its other pages one by one, ready to register.
    """
    now = now or datetime.now(timezone.utc)
    ignored = {_bare_host(host) for host in ignore_hosts if host}
    registered = {}
    for row in db["sites"].find({}, {"origins": 1}):
        for scope in row.get("origins") or []:
            try:
                origin, path = split_scope(scope)
            except ValueError:
                continue
            registered.setdefault(origin_key(origin), []).append((path, True))
    counts = {}
    for doc in db["detection_results"].find(
            {"site_id": None, "updated_at": {"$gte": now - timedelta(days=7)}, "pageUrl": {"$type": "string"}},
            {"pageUrl": 1, "updated_at": 1}).sort("updated_at", -1).limit(5000):
        try:
            origin = normalize_origin(doc["pageUrl"].split("?")[0])
        except ValueError:
            continue
        host = origin_host(origin)
        if _bare_host(host) in ignored or _is_ip(host):
            continue
        if origin_key(origin) in registered:
            path = page_path(doc["pageUrl"])
            if match_path(registered[origin_key(origin)], path):
                continue
            origin += path
        entry = counts.setdefault(origin, {"origin": origin, "sessions": 0, "last_seen": None})
        entry["sessions"] += 1
        seen = _as_utc(doc.get("updated_at"))
        if seen and (entry["last_seen"] is None or seen > entry["last_seen"]):
            entry["last_seen"] = seen
    rows = sorted(counts.values(), key=lambda row: (-row["sessions"], row["origin"]))[:limit]
    return [{**row, "last_seen": _ms(row["last_seen"])} for row in rows]


def install_snippet(collector_base: str, site_id: str) -> str:
    # async, not defer: deferred scripts run in document order with the site's own deferred and
    # module scripts, so a DATACAT host that hangs would keep the customer's app from starting.
    return (f'<script async src="{collector_base}/bot-collector.js" data-datacat '
            f'data-study-id="{STUDY_ID}" data-site-id="{site_id}"></script>')


def overview(db, *, collector_base: str, own_hosts=(), now=None) -> dict:
    """Everything the Websites page shows, in one call."""
    now = now or datetime.now(timezone.utc)
    activity = site_activity(db, now)
    empty = {"sessions": 0, "last_seen": None, "sessions_24h": 0, "humans_24h": 0, "bots_24h": 0,
             "suspects_24h": 0}
    sites = []
    for site in sorted(db["sites"].find({}, {"_id": 0}), key=lambda row: str(row.get("name") or "").lower()):
        stats = activity.get(site["site_id"], empty)
        sites.append({
            **_public(site),
            "created_at": _ms(site.get("created_at")), "updated_at": _ms(site.get("updated_at")),
            **stats, "last_seen": _ms(stats["last_seen"]),
            "install_state": _install_state(site, stats["last_seen"], now),
            "snippet": install_snippet(collector_base, site["site_id"]),
        })
    registered = {site["site_id"] for site in sites}
    # Sessions of a site that was later deleted keep its id; show them rather than lose them.
    removed = [{"site_id": key, **value, "last_seen": _ms(value["last_seen"])}
               for key, value in activity.items() if key is not None and key not in registered]
    unassigned = activity.get(None, empty)
    return {
        "sites": sites,
        "removed_sites": removed,
        "unassigned": {**unassigned, "last_seen": _ms(unassigned["last_seen"])},
        "unregistered_origins": unregistered_origins(db, now, ignore_hosts=own_hosts),
        "collector_base": collector_base,
        "study_id": STUDY_ID,
        "checked_at": _ms(now),
    }
