"""Live View: where recent traffic comes from, aggregated for the dashboard globe.

Sessions seen in the window are located with the offline GeoIP lookup and
grouped by region (DB-IP "cities" are often wards or districts, too fine for a
world map). A session is online when it sent telemetry in the last
ONLINE_SECONDS and its last event was not "pagehide" (tab closed or left). The
collector sends on load, every 15 s while the visitor is active and at least
every 60 s while idle, so two minutes covers an idle open tab; a closed tab
drops out at once.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from api_service import geoip

ONLINE_SECONDS = 120
MAX_POINTS = 500
TOP_N = 6


def _verdict_bucket(row):
    if row.get("decision_state") == "INSUFFICIENT_EVIDENCE":
        return "pending"
    verdict = str(row.get("verdict") or "").upper()
    return {"HUMAN": "human", "BOT": "bot", "SUSPECT": "suspect"}.get(verdict, "pending")


def _as_utc(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def is_online(row, since):
    updated = _as_utc(row.get("updated_at"))
    return bool(updated and updated >= since and row.get("last_action") != "pagehide")


def _place_key(geo):
    return f"{geo.get('country_code') or ''}|{geo.get('region') or geo.get('city') or ''}"


def build_online_view(rows, now=None):
    """The cheap, frequent part of the Live View: who is on the site right now."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(seconds=ONLINE_SECONDS)
    places = defaultdict(int)
    online = 0
    for row in rows:
        if not is_online(row, since):
            continue
        online += 1
        geo = geoip.lookup(row.get("client_ip")) if row.get("client_ip") else None
        if geo and geo.get("latitude") is not None:
            places[_place_key(geo)] += 1
    return {"generated_at": int(now.timestamp() * 1000), "online_seconds": ONLINE_SECONDS,
            "online_now": online, "places": dict(places)}


def build_live_view(rows, now=None, window_minutes=1440):
    now = now or datetime.now(timezone.utc)
    online_since = now - timedelta(seconds=ONLINE_SECONDS)
    totals = defaultdict(int)
    places = {}
    isps = defaultdict(int)
    online = unlocated = 0
    for row in rows:
        bucket = _verdict_bucket(row)
        totals[bucket] += 1
        online_now = is_online(row, online_since)
        online += online_now
        geo = geoip.lookup(row.get("client_ip")) if row.get("client_ip") else None
        if not geo or geo.get("latitude") is None or geo.get("longitude") is None:
            unlocated += 1
            continue
        key = _place_key(geo)
        place = places.get(key)
        if place is None:
            place = places[key] = {
                "key": key,
                "region": geo.get("region") or geo.get("city"), "country": geo.get("country"),
                "country_code": geo.get("country_code"), "lat_sum": 0.0, "lon_sum": 0.0,
                "sessions": 0, "online": 0, "human": 0, "bot": 0, "suspect": 0, "pending": 0,
            }
        place["lat_sum"] += geo["latitude"]
        place["lon_sum"] += geo["longitude"]
        place["sessions"] += 1
        place["online"] += online_now
        place[bucket] += 1
        if geo.get("isp"):
            isps[(geo["isp"], geo.get("asn"))] += 1
    points = []
    for place in sorted(places.values(), key=lambda p: -p["sessions"])[:MAX_POINTS]:
        point = {k: v for k, v in place.items() if k not in ("lat_sum", "lon_sum")}
        point["lat"] = round(place["lat_sum"] / place["sessions"], 3)
        point["lon"] = round(place["lon_sum"] / place["sessions"], 3)
        points.append(point)
    return {
        "generated_at": int(now.timestamp() * 1000),
        "window_minutes": window_minutes,
        "online_seconds": ONLINE_SECONDS,
        "online_now": online,
        "sessions": sum(totals.values()),
        "verdicts": {key: totals[key] for key in ("human", "bot", "suspect", "pending")},
        "points": points,
        "top_locations": [
            {"label": ", ".join(dict.fromkeys(x for x in (p["region"], p["country"]) if x)),
             "key": p["key"], "country_code": p["country_code"], "sessions": p["sessions"], "online": p["online"],
             "lat": p["lat"], "lon": p["lon"]}
            for p in points[:TOP_N]
        ],
        "top_isps": [{"isp": isp, "asn": asn, "sessions": n}
                     for (isp, asn), n in sorted(isps.items(), key=lambda item: -item[1])[:TOP_N]],
        "unlocated": unlocated,
        "attribution": geoip.ATTRIBUTION,
    }
