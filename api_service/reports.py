"""Website reports: what an operator sends a customer for a period.

Numbers are aggregated in MongoDB over the sessions that started in the period, so they are
exact however many sessions there are. Reasons come back as raw decision keys; the dashboard
labels them with the same wording as the traffic table.
"""

import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from api_service import geoip

PERIOD_DAYS = (1, 7, 30)
EXPORT_LIMIT = 50000
TOP_IPS = 20
TOP_GROUPS = 6
TOP_CLICK_SOURCES = 25
RECENT_CLICKS = 100
CLICK_PAGE_SIZE = 50
CLICK_VERDICTS = ("bot", "suspect", "human", "insufficient")
_IP_GROUP_LIMIT = 5000
_NOT_DEFERRED = {"decision_state": {"$ne": "INSUFFICIENT_EVIDENCE"}, "breakdown.decision_deferred": {"$ne": True}}


# The first evidence code of a risk-based verdict (a BOT from a rule also carries risk codes; they
# do not name its reason). A declared crawler is told apart by whether its address is its operator's.
_CRAWLER = "$breakdown.automation_evidence.crawler"
_FIRST_CODE = {"$switch": {"branches": [
    {"case": {"$in": ["$breakdown.decision_basis", ["desktop_risk", "mobile_risk"]]},
     "then": {"$ifNull": [{"$arrayElemAt": ["$breakdown.desktop_risk.codes", 0]},
                          {"$arrayElemAt": ["$breakdown.mobile_human.risk", 0]}]}},
    {"case": {"$eq": ["$breakdown.decision_basis", "client_forgery"]},
     "then": {"$ifNull": [{"$arrayElemAt": ["$breakdown.client_forgery.evidence", 0]},
                          {"$arrayElemAt": ["$breakdown.client_forgery.codes", 0]}]}},
    {"case": {"$eq": [_CRAWLER + ".verified", True]}, "then": "VERIFIED_CRAWLER"},
    {"case": {"$eq": [_CRAWLER + ".verified", False]}, "then": "SPOOFED_CRAWLER"},
], "default": None}}


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

    # Why sessions were judged BOT or SUSPECT: decision basis, rule, and for the risk-based verdicts
    # the first evidence code (a BOT from a rule also carries risk codes; they do not name its reason).
    # A declared crawler is told apart by whether its address is its operator's (policy 25).
    crawler = _CRAWLER
    first_code = _FIRST_CODE
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
        {"$group": {"_id": "$client_ip", "sessions": {"$sum": 1}, "last_seen": {"$max": "$updated_at"},
                    "verified_crawler": {"$sum": {"$cond": [{"$eq": [crawler + ".verified", True]}, 1, 0]}},
                    "crawler": {"$max": crawler + ".name"}}},
        {"$sort": {"sessions": -1, "_id": 1}},
        {"$limit": _IP_GROUP_LIMIT}]))
    # An address that also served people (a carrier's shared CGNAT address, an office) must not be
    # blocked whole; neither should a verified search crawler.
    top_ips = [row["_id"] for row in groups[:TOP_IPS] if row["_id"]]
    people = {row["_id"]: int(row["sessions"]) for row in db["detection_results"].aggregate([
        {"$match": {**match, **_NOT_DEFERRED, "verdict": "HUMAN", "client_ip": {"$in": top_ips}}},
        {"$group": {"_id": "$client_ip", "sessions": {"$sum": 1}}}])} if top_ips else {}
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
            verified = int(row.get("verified_crawler") or 0) == int(row["sessions"])
            bot_ips.append({"client_ip": row["_id"], "sessions": int(row["sessions"]),
                            "last_seen": _ms(row.get("last_seen")), "geo": geo,
                            "human_sessions": people.get(row["_id"], 0),
                            "verified_crawler": row.get("crawler") if verified else None})
    clicks, click_sources, recent_clicks = _click_attribution(db, match, deferred, first_code)
    return {
        "period": {"days": days, "from": _ms(since), "to": _ms(until)},
        "totals": totals,
        # Ad clicks (api_service.clicks): their verdicts, by source, and the latest ones.
        "clicks": clicks,
        "click_sources": click_sources,
        "recent_clicks": recent_clicks,
        "reasons": reasons,
        "bot_ips": bot_ips,
        "bot_ip_count": len([row for row in groups if row["_id"]]),
        "bot_ip_count_capped": len(groups) >= _IP_GROUP_LIMIT,
        # The code lets the dashboard name the country in Vietnamese.
        "bot_countries": [{"code": code, "name": country_names[code], "sessions": count}
                          for code, count in countries.most_common(TOP_GROUPS)],
        "bot_networks": [{"name": name, "sessions": count} for name, count in networks.most_common(TOP_GROUPS)],
    }


def _click_attribution(db, match, deferred, first_code):
    """Sessions an ad click brought (``click_id``/``click_source``), labelled as the traffic table
    labels them: a deferred decision is "insufficient" whatever the verdict."""
    category = {"$cond": [deferred, "insufficient", {"$switch": {"branches": [
        {"case": {"$eq": ["$verdict", "HUMAN"]}, "then": "human"},
        {"case": {"$eq": ["$verdict", "BOT"]}, "then": "bot"}], "default": "suspect"}}]}
    attributed = {**match, "$or": [{"click_id": {"$type": "string"}}, {"click_source": {"$type": "string"}}]}
    clicks = {"sessions": 0, "human": 0, "bot": 0, "suspect": 0, "insufficient": 0}
    sources = {}
    for row in db["detection_results"].aggregate([
            {"$match": attributed},
            {"$group": {"_id": {"source": "$click_source", "category": category}, "sessions": {"$sum": 1}}}]):
        count = int(row["sessions"])
        kind = row["_id"].get("category") or "suspect"
        clicks["sessions"] += count
        clicks[kind] += count
        source = row["_id"].get("source")
        entry = sources.setdefault(source, {"source": source, "sessions": 0, "human": 0, "bot": 0,
                                            "suspect": 0, "insufficient": 0})
        entry["sessions"] += count
        entry[kind] += count
    ranked = sorted(sources.values(), key=lambda s: (-s["bot"], -s["sessions"], str(s["source"])))
    recent = []
    for row in db["detection_results"].aggregate([
            {"$match": {**match, "click_id": {"$type": "string"}}},
            {"$sort": {"created_at": -1}},
            {"$limit": RECENT_CLICKS},
            {"$project": {"_id": 0, "click_id": 1, "click_source": 1, "sessionId": 1, "verdict": 1,
                          "created_at": 1, "category": category, "decision_basis": "$breakdown.decision_basis",
                          "automation_rule": "$breakdown.automation_rule", "code": first_code}}]):
        row["created_at"] = _ms(row.get("created_at"))
        recent.append(row)
    return clicks, ranked[:TOP_CLICK_SOURCES], recent


def clicks_page(db, *, site_filter: dict, days: int, verdict=None, query=None, page=1, now=None) -> dict:
    """Every ad click of the period, newest first, as the network lists its clicks (Click ID, Token 1),
    with DATACAT's verdict; filtered by verdict and by a Click ID or Token 1 prefix."""
    since, until = _period(days, now)
    match = {**site_filter, "created_at": {"$gte": since, "$lt": until}, "click_id": {"$type": "string"}}
    deferred_query = {"$or": [{"decision_state": "INSUFFICIENT_EVIDENCE"}, {"breakdown.decision_deferred": True}]}
    if verdict == "insufficient":
        match = {"$and": [match, deferred_query]}
    elif verdict in ("bot", "suspect", "human"):
        match = {**match, **_NOT_DEFERRED, "verdict": verdict.upper()}
    if query:
        prefix = {"$regex": "^" + re.escape(query)}
        match = {"$and": [match, {"$or": [{"click_id": prefix}, {"click_source": prefix}]}]}
    total = db["detection_results"].count_documents(match)
    page = max(1, int(page))
    deferred = {"$or": [{"$eq": ["$decision_state", "INSUFFICIENT_EVIDENCE"]},
                        {"$eq": ["$breakdown.decision_deferred", True]}]}
    category = {"$cond": [deferred, "insufficient", {"$switch": {"branches": [
        {"case": {"$eq": ["$verdict", "HUMAN"]}, "then": "human"},
        {"case": {"$eq": ["$verdict", "BOT"]}, "then": "bot"}], "default": "suspect"}}]}
    rows = []
    for row in db["detection_results"].aggregate([
            {"$match": match},
            {"$sort": {"created_at": -1, "sessionId": 1}},
            {"$skip": (page - 1) * CLICK_PAGE_SIZE},
            {"$limit": CLICK_PAGE_SIZE},
            {"$project": {"_id": 0, "click_id": 1, "click_source": 1, "sessionId": 1, "verdict": 1, "client_ip": 1,
                          "created_at": 1, "category": category, "decision_basis": "$breakdown.decision_basis",
                          "automation_rule": "$breakdown.automation_rule", "code": _FIRST_CODE}}]):
        row["created_at"] = _ms(row.get("created_at"))
        rows.append(row)
    geoip.attach(rows)
    return {"period": {"days": days, "from": _ms(since), "to": _ms(until)}, "clicks": rows, "total": total,
            "page": page, "page_size": CLICK_PAGE_SIZE}


_EXPORT_FIELDS = {
    "_id": 0, "sessionId": 1, "site_id": 1, "client_ip": 1, "pageUrl": 1, "verdict": 1, "decision_state": 1,
    "created_at": 1, "updated_at": 1, "user_agent": 1, "fingerprint.userAgent": 1,
    "breakdown.decision_basis": 1, "breakdown.automation_rule": 1, "breakdown.decision_deferred": 1,
    "breakdown.desktop_risk.codes": 1, "breakdown.mobile_human.risk": 1, "breakdown.mobile_human.gestures": 1,
    "breakdown.client_forgery.codes": 1, "breakdown.client_forgery.evidence": 1, "breakdown.unsupported_mobile": 1, "breakdown.legacy_touch_ambiguous": 1, "breakdown.touch_records_excluded": 1,
    "breakdown.mouse_points": 1, "breakdown.minimum_mouse_points": 1, "click_id": 1, "click_source": 1,
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
