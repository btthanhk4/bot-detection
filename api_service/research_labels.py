"""Persistent session numbers and operator attestations, separate from model inputs."""

import logging
import threading
import time
from datetime import datetime, timezone

from pymongo import ReturnDocument

from api_service.database import _writes_are_blocked, get_db

logger = logging.getLogger("bot_detection.research")
_lock = threading.RLock()


def _milliseconds(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp() * 1000)
    return int(value) if value is not None else int(time.time() * 1000)


def _register(db, data):
    collection = db["research_sessions"]
    identifier = data["sessionId"]
    if _writes_are_blocked(db, identifier):
        return {}
    existing = collection.find_one({"_id": identifier})
    if existing:
        if existing.get("deleted"):
            collection.update_one({"_id": identifier}, {"$set": {"deleted": False}})
        if data.get("_site_id") and not existing.get("attributed_site_id"):
            # A session that began before its website was registered.
            collection.update_one({"_id": identifier}, {"$set": {"attributed_site_id": data["_site_id"]}})
        return existing
    counter = db["research_counters"].find_one_and_update(
        {"_id": "traffic"}, {"$inc": {"value": 1}}, upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    meta = data.get("collector") or {}
    doc = {
        "_id": identifier, "sessionId": identifier, "traffic_number": counter["value"],
        "first_received_at": _milliseconds(data.get("received_at") or data.get("created_at")),
        "study_id": data.get("study_id") or meta.get("studyId"),
        "site_id": data.get("site_id") or meta.get("siteId"),
        # site_id is what the tag declared (study metadata); attributed_site_id is the
        # registered website its Origin belongs to, which the dashboard filters by.
        "attributed_site_id": data.get("_site_id"),
        "revision": 0, "manual_label": None,
    }
    # $setOnInsert makes retries and concurrent first snapshots idempotent.
    return collection.find_one_and_update(
        {"_id": identifier}, {"$setOnInsert": doc}, upsert=True,
        return_document=ReturnDocument.AFTER,
    )


def _prepare(db):
    """Backfill surviving legacy sessions once, ordered by server first-seen time."""
    control = db["research_counters"].find_one({"_id": "initialized"})
    if control:
        return
    db["research_sessions"].create_index("traffic_number", unique=True)
    db["labeled_captures"].create_index([("sessionId", 1), ("received_at", 1)])
    db["labeled_captures"].create_index([("study_id", 1), ("site_id", 1), ("received_at", 1), ("event_id", 1)])
    history = {}
    for doc in db["detection_results"].find(
        {}, {"sessionId": 1, "created_at": 1, "updated_at": 1},
    ):
        if doc.get("sessionId"):
            history[doc["sessionId"]] = {**doc, "received_at": _milliseconds(
                doc.get("created_at") or doc.get("updated_at")),
            }
    # Aggregate in MongoDB rather than loading every raw snapshot into API RAM.
    for doc in db["telemetry_captures"].aggregate([
        {"$group": {"_id": "$sessionId", "received_at": {"$min": "$received_at"}}},
    ]):
        identifier = doc.get("_id")
        if not identifier or not isinstance(doc.get("received_at"), int):
            continue
        previous = history.get(identifier)
        if previous is None or doc["received_at"] < previous["received_at"]:
            history[identifier] = {"sessionId": identifier, "received_at": doc["received_at"]}
    for doc in sorted(history.values(), key=lambda value: (value["received_at"], value["sessionId"])):
        _register(db, doc)
    db["research_counters"].update_one(
        {"_id": "initialized"}, {"$set": {"ready": True}}, upsert=True,
    )


def register_traffic(data):
    """Number at the first successful server registration, before inference.

    During Mongo outages this returns None; replay registers when storage recovers.
    Numbers are identities, not totals: deletes or interrupted allocations leave gaps.
    """
    try:
        db = get_db()
        if db is None:
            return None
        with _lock:
            _prepare(db)
            return _register(db, data).get("traffic_number")
    except Exception:
        logger.warning("Session numbering unavailable", exc_info=True)
        return None


def enrich_sessions(sessions):
    if not sessions:
        return sessions
    db = get_db()
    if db is None:
        return sessions
    with _lock:
        _prepare(db)
    metadata = {doc["_id"]: doc for doc in db["research_sessions"].find(
        {"_id": {"$in": [row["sessionId"] for row in sessions]}},
        {"traffic_number": 1, "first_received_at": 1, "revision": 1, "manual_label": 1},
    )}
    return [{**row, **{key: value for key, value in metadata.get(row["sessionId"], {}).items()
                      if key != "_id"}} for row in sessions]


# The dashboard's verdict filter, as its table labels sessions: a deferred decision reads
# "not enough data" whatever the verdict, and so does a session the model has not scored yet.
VERDICT_FILTERS = ("bot", "suspect", "pending", "human")
_DECIDED = {"decision_state": {"$ne": "INSUFFICIENT_EVIDENCE"}, "breakdown.decision_deferred": {"$ne": True}}


# Every open dashboard polls the table every 5 s; the id lists are shared for a few seconds.
VERDICT_CACHE_SECONDS = 15
_verdict_cache = {}
_verdict_cache_lock = threading.Lock()


def _decided_ids(db, verdict):
    """Session ids with a decided verdict (``None``: any), read from the ``table_verdict`` index."""
    key = (id(db), verdict)
    now = time.monotonic()
    with _verdict_cache_lock:
        cached = _verdict_cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
    query = {**_DECIDED, "verdict": verdict} if verdict else {
        **_DECIDED, "verdict": {"$in": ["BOT", "SUSPECT", "HUMAN"]}}
    ids = db["detection_results"].distinct("sessionId", query)
    with _verdict_cache_lock:
        _verdict_cache[key] = (now + VERDICT_CACHE_SECONDS, ids)
    return ids


def _country_ids(db, country):
    """Session ids of one country (``None``: no known country), from the ``country_code`` index."""
    key = (id(db), "country", country)
    now = time.monotonic()
    with _verdict_cache_lock:
        cached = _verdict_cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
    ids = db["detection_results"].distinct("sessionId", {"country_code": country})
    with _verdict_cache_lock:
        _verdict_cache[key] = (now + VERDICT_CACHE_SECONDS, ids)
    return ids


def _verdict_condition(db, verdict):
    if verdict == "pending":
        return {"sessionId": {"$nin": _decided_ids(db, None)}}
    return {"sessionId": {"$in": _decided_ids(db, verdict.upper())}}


def _display_numbers(collection, scope, rows, consecutive):
    """Each row's place among the live sessions of ``scope``, oldest first: the table's STT.

    Every website counts from 1, and so does the view of all websites; deleted sessions do not
    count, so after "delete all" the next session is 1 again. ``rows`` are newest first;
    ``consecutive`` when nothing but the scope filtered them (no verdict filter)."""
    if not rows:
        return []
    top = rows[0]["traffic_number"]
    place = collection.count_documents({**scope, "traffic_number": {"$lte": top}})
    if consecutive:
        return [place - index for index in range(len(rows))]
    # A filtered page skips sessions: count the scope's sessions between its first and last row.
    span = collection.find({**scope, "traffic_number": {"$gte": rows[-1]["traffic_number"], "$lte": top}},
                           {"_id": 0, "traffic_number": 1}).sort("traffic_number", -1)
    offset = {doc["traffic_number"]: index for index, doc in enumerate(span)}
    return [place - offset.get(row["traffic_number"], 0) for row in rows]


def traffic_page(limit=50, before_number=None, site_filter=None, verdict=None, country=None):
    """``site_filter`` is the dashboard's condition on ``site_id`` (one site, a list, or none);
    ``verdict`` one of ``VERDICT_FILTERS`` or None; ``country`` an ISO code, "_none" (unknown) or
    None. Rows carry ``display_number``, their STT within the website, whatever the filters."""
    db = get_db()
    if db is None:
        raise RuntimeError("Database unavailable")
    with _lock:
        _prepare(db)
    query = {"deleted": {"$ne": True}}
    if site_filter and "site_id" in site_filter:
        query["attributed_site_id"] = site_filter["site_id"]
    unfiltered = dict(query)
    if country:
        query["$and"] = [{"sessionId": {"$in": _country_ids(db, None if country == "_none" else country)}}]
    every_verdict = dict(query)
    if verdict:
        query.update(_verdict_condition(db, verdict))
    if before_number is not None:
        query["traffic_number"] = {"$lt": before_number}
    rows = list(db["research_sessions"].find(query, {"label_history": 0})
                .sort("traffic_number", -1).limit(limit + 1))
    has_more = len(rows) > limit
    rows = rows[:limit]
    detections = {doc["sessionId"]: doc for doc in db["detection_results"].find(
        {"sessionId": {"$in": [row["sessionId"] for row in rows]}},
        {"_id": 0, "mouse_trajectory": 0},
    )} if rows else {}
    numbers = _display_numbers(db["research_sessions"], unfiltered, rows, consecutive=not verdict and not country)
    sessions = []
    for row, number in zip(rows, numbers):
        doc = detections.get(row["sessionId"], {
            "sessionId": row["sessionId"], "verdict": "SUSPECT", "decision_state": "INSUFFICIENT_EVIDENCE",
            "breakdown": {"decision_deferred": True, "has_enough_mouse_data": False},
        })
        doc = {**doc, **{key: row.get(key) for key in (
            "traffic_number", "first_received_at", "revision", "manual_label",
        )}, "received_at": row["first_received_at"], "display_number": number}
        for field in ("created_at", "updated_at"):
            if isinstance(doc.get(field), datetime):
                doc[field] = _milliseconds(doc[field])
        sessions.append(doc)
    total = db["research_sessions"].count_documents(
        {key: value for key, value in query.items() if key != "traffic_number"})
    return {"sessions": sessions, "returned": len(sessions), "total": total,
            # Every session of the site and country, whatever the verdict (the KPI cards count from it).
            "all_total": db["research_sessions"].count_documents(every_verdict) if verdict else total,
            "next_before": rows[-1]["traffic_number"] if has_more else None}


def _set_manual_label(session_id, annotation, expected_revision):
    """One atomic compare-and-swap writes the current label and audit history."""
    db = get_db()
    if db is None:
        raise RuntimeError("Database unavailable")
    collection = db["research_sessions"]
    current = collection.find_one({"_id": session_id})
    if current is None or current.get("deleted") or _writes_are_blocked(db, session_id):
        raise LookupError("Session not found")
    if current["revision"] != expected_revision:
        raise FileExistsError("Label changed in another tab; refresh before saving")
    # Freeze available raw snapshots separately; the operational capture TTL must
    # not silently erase data the operator explicitly selected for the dataset.
    archived = db["labeled_captures"]
    if annotation["label"] != "UNKNOWN":
        reference = archived.find_one({"sessionId": session_id})
        for snapshot in db["telemetry_captures"].find({
            "sessionId": session_id, "expires_at_ms": {"$gt": int(time.time() * 1000)},
        }):
            if reference is not None and any(snapshot.get(key) != reference.get(key)
                                             for key in ("visitorId", "study_id", "site_id")):
                raise ValueError("Session contains conflicting visitor/study/site identities; review before labeling")
            reference = reference or snapshot
            retained = {key: value for key, value in snapshot.items() if key != "expires_at"}
            archived.update_one({"_id": snapshot["_id"]}, {"$setOnInsert": retained}, upsert=True)
        if archived.find_one({"sessionId": session_id}, {"_id": 1}) is None:
            raise ValueError("No research snapshots remain; enable capture before collecting dataset traffic")
    saved = {**annotation, "updated_at": int(time.time() * 1000),
             "revision": expected_revision + 1}
    result = collection.find_one_and_update(
        {"_id": session_id, "revision": expected_revision},
        {"$set": {"manual_label": saved}, "$inc": {"revision": 1},
         "$push": {"label_history": saved}},
        return_document=ReturnDocument.AFTER,
    )
    if result is None:
        raise FileExistsError("Label changed in another tab; refresh before saving")
    return {"sessionId": session_id, "traffic_number": result["traffic_number"],
            "revision": result["revision"], "manual_label": result["manual_label"]}


def set_manual_label(session_id, annotation, expected_revision):
    with _lock:
        return _set_manual_label(session_id, annotation, expected_revision)


def delete_research_data(session_id=None):
    with _lock:
        return _delete_research_data(session_id)


def delete_research_sessions(session_ids) -> int:
    """The research data of many sessions (a website's), in chunks."""
    ids = list(session_ids)
    deleted = 0
    with _lock:
        for start in range(0, len(ids), 1000):
            deleted += _delete_research_data({"$in": ids[start:start + 1000]})
    return deleted


def _delete_research_data(session_id=None):
    """Explicit administrative deletion includes retained dataset snapshots/labels."""
    db = get_db()
    if db is None:
        raise RuntimeError("Database unavailable")
    query = {"sessionId": session_id} if session_id is not None else {}
    active = db["research_sessions"].count_documents({**query, "deleted": {"$ne": True}})
    db["labeled_captures"].delete_many(query)
    # Keep numeric identities to prevent number reuse, but erase attestations.
    db["research_sessions"].update_many(
        query, {"$set": {"manual_label": None, "deleted": True},
                "$unset": {"label_history": ""}, "$inc": {"revision": 1}},
    )
    return active
