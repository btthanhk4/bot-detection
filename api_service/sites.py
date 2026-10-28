"""Website registry: the sites DATACAT monitors and the origins their pages are served from.

An operator registers a site on the dashboard with its origins. From then on:

* pages on those origins may post telemetry and pass CORS at once, without editing the
  server's environment (origins in ``BOT_TELEMETRY_ORIGINS`` stay allowed as before);
* every session is attributed to a site by the browser's ``Origin`` header, which a page
  cannot set, never by the site id the tag declares (a copied tag would claim another site);
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
from urllib.parse import urlsplit

SITE_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
_SITE_ID = re.compile(SITE_ID_PATTERN)
# Query value that selects sessions no registered site claims.
UNASSIGNED = "_none"
SITE_FILTER_PATTERN = r"^(_none|[a-z0-9][a-z0-9_-]{0,63})$"
STATUSES = ("active", "paused")
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
    """Snapshot of the ``sites`` collection: site id -> site, origin -> site."""

    def __init__(self):
        self._lock = threading.Lock()
        self._sites = {}
        self._by_origin = {}
        self._by_host = {}

    def reload(self, db) -> bool:
        if db is None:
            return False
        try:
            rows = list(db["sites"].find({}, {"_id": 0}))
        except Exception:
            # Keep serving the last good snapshot through a database hiccup.
            return False
        sites = {row["site_id"]: row for row in rows if row.get("site_id")}
        by_origin, by_host = {}, {}
        for row in sites.values():
            for origin in row.get("origins") or []:
                by_origin[origin] = row
                by_host.setdefault(origin_host(origin), row)
        with self._lock:
            self._sites, self._by_origin, self._by_host = sites, by_origin, by_host
        return True

    def sites(self) -> dict:
        return self._sites

    def get(self, site_id: str) -> Optional[dict]:
        return self._sites.get(site_id)

    def for_origin(self, origin: str) -> Optional[dict]:
        return self._by_origin.get(str(origin or "").rstrip("/").lower())

    def for_host(self, host: str) -> Optional[dict]:
        return self._by_host.get(str(host or "").split(":")[0].lower())

    def allows_cors(self, origin: str) -> bool:
        site = self.for_origin(origin)
        return bool(site) and site.get("status") == "active"

    def origin_decision(self, origin: str, configured) -> tuple:
        """(allowed, site) for a browser posting telemetry from ``origin``.

        No Origin header (a server-side caller) is not judged here. A registered origin
        follows its site's status; otherwise the configured allowlist applies, and with
        neither an allowlist nor any registered site every origin is accepted (local runs).
        """
        origin = str(origin or "").rstrip("/")
        if not origin:
            return True, None
        site = self.for_origin(origin)
        if site is not None:
            return site.get("status") == "active", site
        if origin in (configured or ()):
            return True, None
        return not configured and not self._sites, None


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
    return {key: site.get(key) for key in ("site_id", "name", "origins", "status", "contact", "notes",
                                          "created_at", "updated_at")}


def _conflicts(db, origins, site_id: Optional[str] = None) -> Optional[tuple]:
    query = {"origins": {"$in": list(origins)}}
    if site_id:
        query["site_id"] = {"$ne": site_id}
    other = db["sites"].find_one(query, {"site_id": 1, "origins": 1})
    if other:
        taken = sorted(set(origins) & set(other.get("origins") or []))
        return (taken[0] if taken else "", other["site_id"])
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
        pattern = "^" + re.escape(origin) + r"([/?#]|$)"
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


def create_site(db, *, name: str, origins, site_id: Optional[str] = None, contact: Optional[str] = None,
                notes: Optional[str] = None, status: str = "active") -> dict:
    """Raises ValueError (bad input) or LookupError (id or origin already taken)."""
    origins = sorted({normalize_origin(origin) for origin in origins})
    if not origins or len(origins) > MAX_ORIGINS:
        raise ValueError(f"A site needs 1 to {MAX_ORIGINS} domains")
    if site_id is not None and not _SITE_ID.match(site_id):
        raise ValueError("Site id may use lowercase letters, digits, '-' and '_'")
    if status not in STATUSES:
        raise ValueError("Unknown status")
    conflict = _conflicts(db, origins)
    if conflict:
        raise LookupError(f"{conflict[0]} already belongs to site {conflict[1]}")
    site_id = site_id or unique_site_id(db, name)
    if db["sites"].find_one({"site_id": site_id}, {"_id": 1}):
        raise LookupError(f"Site id {site_id} is already used")
    now = datetime.now(timezone.utc)
    site = {"site_id": site_id, "name": name.strip(), "origins": origins, "status": status,
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
        origins = sorted({normalize_origin(origin) for origin in changes["origins"]})
        if not origins or len(origins) > MAX_ORIGINS:
            raise ValueError(f"A site needs 1 to {MAX_ORIGINS} domains")
        conflict = _conflicts(db, origins, site_id)
        if conflict:
            raise LookupError(f"{conflict[0]} already belongs to site {conflict[1]}")
        update["origins"] = origins
    if changes.get("status") is not None:
        if changes["status"] not in STATUSES:
            raise ValueError("Unknown status")
        update["status"] = changes["status"]
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
    test traffic, not a customer's website to register.
    """
    now = now or datetime.now(timezone.utc)
    ignored = {_bare_host(host) for host in ignore_hosts if host}
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
        entry = counts.setdefault(origin, {"origin": origin, "sessions": 0, "last_seen": None})
        entry["sessions"] += 1
        seen = _as_utc(doc.get("updated_at"))
        if seen and (entry["last_seen"] is None or seen > entry["last_seen"]):
            entry["last_seen"] = seen
    rows = sorted(counts.values(), key=lambda row: (-row["sessions"], row["origin"]))[:limit]
    return [{**row, "last_seen": _ms(row["last_seen"])} for row in rows]


def install_snippet(collector_base: str, site_id: str) -> str:
    return (f'<script defer src="{collector_base}/bot-collector.js" data-datacat '
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
