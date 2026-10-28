"""Website reports: what an operator sends a customer for a period.

Numbers are aggregated in MongoDB over the sessions that started in the period, so they are
exact however many sessions there are. Reasons come back as raw decision keys; the dashboard
labels them with the same wording as the traffic table.
"""

from collections import Counter
from datetime import datetime, timedelta, timezone

from api_service import geoip

PERIOD_DAYS = (1, 7, 30)
EXPORT_LIMIT = 50000
TOP_IPS = 20
TOP_GROUPS = 6
_IP_GROUP_LIMIT = 5000
_NOT_DEFERRED = {"decision_state": {"$ne": "INSUFFICIENT_EVIDENCE"}, "breakdown.decision_deferred": {"$ne": True}}


def _ms(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp() * 1000)
    return None


def _period(days, now=None):
    now = now or datetime.now(timezone.utc)
    return now - timedelta(days=days), now


def summary(db, *, site_filter: dict, days: int, now=None) -> dict:
    since, until = _period(days, now)
    match = {**site_filter, "created_at": {"$gte": since, "$lt": until}}

    totals = {"sessions": 0, "human": 0, "bot": 0, "suspect": 0, "insufficient": 0}
    deferred = {"$or": [{"$eq": ["$decision_state", "INSUFFICIENT_EVIDENCE"]},
                        {"$eq": ["$breakdown.decision_deferred", True]}]}
    for row in db["detection_results"].aggregate([
            {"$match": match},
            {"$group": {"_id": {"verdict": "$verdict", "deferred": {"$cond": [deferred, True, False]}},
                        "sessions": {"$sum": 1}}}]):
        verdict = str(row["_id"].get("verdict") or "").upper()
        count = int(row["sessions"])
        totals["sessions"] += count
        if row["_id"].get("deferred"):
            totals["insufficient"] += count
        elif verdict == "HUMAN":
            totals["human"] += count
        elif verdict == "BOT":
            totals["bot"] += count
        else:
            totals["suspect"] += count

    # Why sessions were judged BOT or SUSPECT: decision basis, rule and the first evidence code.
    first_code = {"$ifNull": [{"$arrayElemAt": ["$breakdown.desktop_risk.codes", 0]},
                              {"$arrayElemAt": ["$breakdown.mobile_human.risk", 0]}]}
    reasons = [
        {"verdict": row["_id"].get("verdict"), "decision_basis": row["_id"].get("basis"),
         "automation_rule": row["_id"].get("rule"), "code": row["_id"].get("code"), "sessions": int(row["sessions"])}
        for row in db["detection_results"].aggregate([
            {"$match": {**match, **_NOT_DEFERRED, "verdict": {"$in": ["BOT", "SUSPECT"]}}},
            {"$group": {"_id": {"verdict": "$verdict", "basis": "$breakdown.decision_basis",
                                "rule": "$breakdown.automation_rule", "code": first_code},
                        "sessions": {"$sum": 1}}},
            {"$sort": {"sessions": -1}},
            {"$limit": 12}])
    ]

    # Where bot sessions come from: addresses, then their country and network.
    groups = list(db["detection_results"].aggregate([
        {"$match": {**match, "verdict": "BOT"}},
        {"$group": {"_id": "$client_ip", "sessions": {"$sum": 1}, "last_seen": {"$max": "$updated_at"}}},
        {"$sort": {"sessions": -1, "_id": 1}},
        {"$limit": _IP_GROUP_LIMIT}]))
    countries, networks, country_names = Counter(), Counter(), {}
    bot_ips = []
    for index, row in enumerate(groups):
        if not row["_id"]:
            continue
        geo = geoip.lookup(row["_id"]) or {}
        code = geo.get("country_code") or ""
        country_names.setdefault(code, geo.get("country") or "Không rõ")
        countries[code] += row["sessions"]
        networks[geo.get("isp") or "Không rõ"] += row["sessions"]
        if index < TOP_IPS:
            bot_ips.append({"client_ip": row["_id"], "sessions": int(row["sessions"]),
                            "last_seen": _ms(row.get("last_seen")), "geo": geo})
    return {
        "period": {"days": days, "from": _ms(since), "to": _ms(until)},
        "totals": totals,
        "reasons": reasons,
        "bot_ips": bot_ips,
        "bot_ip_count": len([row for row in groups if row["_id"]]),
        "bot_ip_count_capped": len(groups) >= _IP_GROUP_LIMIT,
        # The code lets the dashboard name the country in Vietnamese.
        "bot_countries": [{"code": code, "name": country_names[code], "sessions": count}
                          for code, count in countries.most_common(TOP_GROUPS)],
        "bot_networks": [{"name": name, "sessions": count} for name, count in networks.most_common(TOP_GROUPS)],
    }


_EXPORT_FIELDS = {
    "_id": 0, "sessionId": 1, "site_id": 1, "client_ip": 1, "pageUrl": 1, "verdict": 1, "decision_state": 1,
    "created_at": 1, "updated_at": 1, "user_agent": 1, "fingerprint.userAgent": 1,
    "breakdown.decision_basis": 1, "breakdown.automation_rule": 1, "breakdown.decision_deferred": 1,
    "breakdown.desktop_risk.codes": 1, "breakdown.mobile_human.risk": 1, "breakdown.mobile_human.gestures": 1,
    "breakdown.unsupported_mobile": 1, "breakdown.legacy_touch_ambiguous": 1, "breakdown.touch_records_excluded": 1,
    "breakdown.mouse_points": 1, "breakdown.minimum_mouse_points": 1,
}


def sessions(db, *, site_filter: dict, days: int, now=None) -> dict:
    """Sessions of the period for the CSV export (oldest first, capped)."""
    since, until = _period(days, now)
    rows = list(db["detection_results"].find(
        {**site_filter, "created_at": {"$gte": since, "$lt": until}}, _EXPORT_FIELDS,
    ).sort("created_at", 1).limit(EXPORT_LIMIT + 1))
    truncated = len(rows) > EXPORT_LIMIT
    rows = rows[:EXPORT_LIMIT]
    for row in rows:
        row["created_at"] = _ms(row.get("created_at"))
        row["updated_at"] = _ms(row.get("updated_at"))
    geoip.attach(rows)
    return {"period": {"days": days, "from": _ms(since), "to": _ms(until)}, "sessions": rows, "truncated": truncated}
