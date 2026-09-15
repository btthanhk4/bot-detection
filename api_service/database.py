"""
MongoDB Database Module for Bot Detection Results
===================================================
Provides persistent storage for detection sessions, replacing the in-memory
JSON file buffer. Uses pymongo with connection pooling and automatic reconnection.

Collections:
  - detection_results: All analyzed sessions with AI verdicts
"""

import os
import logging
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from pymongo.errors import DuplicateKeyError
from core_ml.features.mouse_features import (
    MAX_MOUSE_RECORDS,
    compute_statistical_features,
    records_to_chunks,
    sanitize_mouse_records,
)

logger = logging.getLogger("bot_detection.database")

# ── MongoDB Connection ──
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://silkmoon-mongodb:27017")
MONGO_DB = os.environ.get("MONGO_DB", "bot_detection")

_client = None
_db = None
_connect_lock = threading.Lock()
_retry_after = 0.0

def get_db():
    """Lazy-initialize MongoDB connection with retry logic."""
    global _client, _db, _retry_after
    if _db is not None:
        return _db
    if time.monotonic() < _retry_after:
        return None
    with _connect_lock:
        if _db is not None:
            return _db
        if time.monotonic() < _retry_after:
            return None
        try:
            from pymongo import MongoClient
            _client = MongoClient(
                MONGO_URI,
                serverSelectionTimeoutMS=1500,
                connectTimeoutMS=1500,
                maxPoolSize=10,
                tz_aware=True,
            )
            _client.admin.command("ping")
            _db = _client[MONGO_DB]
            _ensure_indexes(_db)
            logger.info(f"[DB] Connected to MongoDB database: {MONGO_DB}")
            return _db
        except Exception as e:
            logger.error(f"[DB] MongoDB connection failed: {e}")
            if _client is not None:
                _client.close()
            _client = None
            _db = None
            _retry_after = time.monotonic() + 10.0
            return None


def is_database_ready() -> bool:
    """Ping MongoDB so readiness detects a stale or disconnected client."""
    db = get_db()
    if db is None or _client is None:
        return False
    try:
        _client.admin.command("ping")
        return True
    except Exception:
        return False


def _ensure_indexes(db):
    """Create indexes for efficient queries."""
    indexes = [
        (db["detection_results"], "created_at_-1", [("created_at", -1)], {"expireAfterSeconds": 86400 * 30}),
        (db["detection_results"], "sessionId_1", [("sessionId", 1)], {"unique": True}),
        (db["detection_results"], "verdict_1", [("verdict", 1)], {}),
        (db["detection_results"], "visitorId_1", [("visitorId", 1)], {}),
        (db["detection_results"], "updated_at_-1", [("updated_at", -1)], {}),
        (db["deleted_sessions"], "expires_at_1", [("expires_at", 1)], {"expireAfterSeconds": 0}),
    ]
    for collection, name, keys, options in indexes:
        try:
            existing = collection.index_information().get(name)
            existing_keys = [tuple(item) for item in (existing or {}).get("key", [])]
            options_match = all(existing.get(key) == value for key, value in options.items()) if existing else False

            if existing and (existing_keys != keys or not options_match):
                logger.info(f"[DB] Rebuilding index {name} with updated options")
                collection.drop_index(name)
                existing = None

            if not existing:
                collection.create_index(keys, name=name, **options)
        except Exception as e:
            logger.warning(f"[DB] Index creation warning for {name}: {e}")


def _writes_are_blocked(db, session_id: str) -> bool:
    now = datetime.now(timezone.utc)
    control = db["service_control"].find_one({"_id": "ingestion"}, {"blocked_until": 1})
    if control and control.get("blocked_until") and control["blocked_until"] > now:
        return True
    return db["deleted_sessions"].find_one(
        {"sessionId": session_id, "expires_at": {"$gt": now}}, {"_id": 1}
    ) is not None


def save_detection_result(telemetry: dict, analysis: dict) -> Optional[str]:
    """
    Save a detection result to MongoDB.
    Uses upsert on sessionId to update existing sessions (multiple heartbeats).
    Skips if sessionId was recently deleted (blacklisted).
    Returns the inserted/updated document ID or None on failure.
    """
    db = get_db()
    if db is None:
        return None

    try:
        session_id = str(telemetry.get("sessionId") or f"unknown_{uuid.uuid4().hex}")[:128]

        if _writes_are_blocked(db, session_id):
            return None

        mouse_data = telemetry.get("mouse") or {}
        records = mouse_data.get("records") or mouse_data.get("trajectory") or []
        sanitized_records = sanitize_mouse_records(records, max_records=MAX_MOUSE_RECORDS)
        mouse_stats = compute_statistical_features(sanitized_records)
        mouse_stats["chunks_count"] = len(records_to_chunks(sanitized_records))
        mouse_stats["has_enough_data"] = mouse_stats["chunks_count"] > 0
        captured_count = len(sanitized_records)
        now = datetime.now(timezone.utc)
        raw_sequence = telemetry.get("sequence")
        raw_timestamp = telemetry.get("timestamp")
        raw_received_at = telemetry.get("received_at")
        if raw_timestamp is None:
            raw_timestamp = raw_received_at
        try:
            sequence = max(0, min(int(raw_sequence or 0), 999))
        except (TypeError, ValueError, OverflowError):
            sequence = 0
        try:
            if raw_timestamp is not None:
                # Millisecond timestamp is the lifecycle-safe primary order; sequence
                # only breaks ties. This allows a reused custom sessionId after reload.
                timestamp = max(0, min(int(raw_timestamp), 9_000_000_000_000))
                if raw_received_at is not None:
                    received_at = max(0, min(int(raw_received_at), 9_000_000_000_000))
                    timestamp = max(received_at - 86_400_000, min(timestamp, received_at + 300_000))
                event_order = timestamp * 1000 + sequence
            else:
                # Backward compatibility for callers that only provide sequence.
                event_order = max(0, min(int(raw_sequence), 9007199254740991))
        except (TypeError, ValueError, OverflowError):
            event_order = int(now.timestamp() * 1000) * 1000 + sequence

        doc = {
            "sessionId": session_id,
            "visitorId": telemetry.get("visitorId"),
            "client_ip": telemetry.get("client_ip"),
            "pageUrl": telemetry.get("pageUrl"),
            "referrer": telemetry.get("referrer"),
            "verdict": analysis.get("verdict", "UNKNOWN"),
            "bot_probability": round(analysis.get("bot_probability", 0), 4),
            "is_bot": analysis.get("is_bot", False),
            "confidence": round(analysis.get("confidence", 0), 4),
            "breakdown": analysis.get("breakdown", {}),
            "reasons": analysis.get("reasons", []),
            "mouse_points_captured": captured_count,
            # Store raw fingerprint + botd for detail panel
            "fingerprint": telemetry.get("fingerprint") or {},
            "botd": telemetry.get("botd") or {},
            "mouse_stats": mouse_stats,
            "mouse_trajectory": sanitized_records[-200:],
            "event_order": event_order,
            "event_timestamp": telemetry.get("timestamp"),
            "updated_at": now,
        }

        visitor_id = telemetry.get("visitorId")
        update_filter = {
            "sessionId": session_id,
            "$and": [
                {"$or": [{"event_order": {"$lte": event_order}}, {"event_order": {"$exists": False}}]},
                {"$or": [{"visitorId": visitor_id}, {"visitorId": None}]},
            ],
        }
        collection = db["detection_results"]
        result = collection.update_one(update_filter, {"$set": doc}, upsert=False)
        if result.matched_count == 0:
            insert_doc = {**doc, "created_at": now}
            try:
                collection.insert_one(insert_doc)
            except DuplicateKeyError:
                # A concurrent first heartbeat may have inserted the session. Retry
                # the conditional update; a stale or foreign visitor stays rejected.
                result = collection.update_one(update_filter, {"$set": doc}, upsert=False)
                if result.matched_count == 0:
                    return None

        # Close the delete/write race: a tombstone created during this write wins.
        if _writes_are_blocked(db, session_id):
            collection.delete_one({"sessionId": session_id})
            return None
        return session_id
    except Exception as e:
        logger.error(f"[DB] Save failed: {e}")
        return None


def get_recent_results(limit: int = 50) -> List[dict]:
    """Get most recent detection results, sorted by created_at descending."""
    db = get_db()
    if db is None:
        return []

    try:
        cursor = db["detection_results"].find(
            {},
            {
                "_id": 0,
                "sessionId": 1,
                "visitorId": 1,
                "client_ip": 1,
                "pageUrl": 1,
                "verdict": 1,
                "bot_probability": 1,
                "is_bot": 1,
                "confidence": 1,
                "breakdown": 1,
                "reasons": 1,
                "mouse_points_captured": 1,
                "fingerprint": 1,
                "botd": 1,
                "mouse_stats": 1,
                "created_at": 1,
                "updated_at": 1,
            },
        ).sort("updated_at", -1).limit(max(1, min(int(limit), 200)))
        results = []
        for doc in cursor:
            # Convert datetime to epoch ms for frontend compatibility
            if "created_at" in doc and doc["created_at"]:
                doc["received_at"] = int(doc.get("updated_at", doc["created_at"]).timestamp() * 1000)
            if "updated_at" in doc and doc["updated_at"]:
                doc["updated_at"] = int(doc["updated_at"].timestamp() * 1000)
            results.append(doc)
        return results
    except Exception as e:
        logger.error(f"[DB] Query failed: {e}")
        return []


def get_total_count() -> int:
    """Get total number of detection results."""
    db = get_db()
    if db is None:
        return 0
    try:
        return db["detection_results"].count_documents({})
    except Exception:
        return 0


def delete_session(session_id: str) -> Optional[bool]:
    """Delete a specific session by sessionId and blacklist it."""
    db = get_db()
    if db is None:
        return None
    try:
        now = datetime.now(timezone.utc)
        db["deleted_sessions"].update_one(
            {"sessionId": session_id},
            {"$set": {"expires_at": now + timedelta(minutes=10)}},
            upsert=True,
        )
        result = db["detection_results"].delete_one({"sessionId": session_id})
        return result.deleted_count > 0
    except Exception as e:
        logger.error(f"[DB] Delete failed: {e}")
        return None


def delete_all_sessions() -> Optional[int]:
    """Delete all detection results. Returns number of deleted documents."""
    db = get_db()
    if db is None:
        return None
    try:
        now = datetime.now(timezone.utc)
        db["service_control"].update_one(
            {"_id": "ingestion"},
            {"$set": {"blocked_until": now + timedelta(seconds=60)}},
            upsert=True,
        )
        db["deleted_sessions"].delete_many({})
        result = db["detection_results"].delete_many({})
        return result.deleted_count
    except Exception as e:
        logger.error(f"[DB] Delete all failed: {e}")
        return None


def get_summary_stats() -> dict:
    """Get aggregated statistics from the database."""
    db = get_db()
    if db is None:
        return {"total": 0, "humans": 0, "bots": 0, "suspects": 0}
    try:
        pipeline = [
            {
                "$group": {
                    "_id": "$verdict",
                    "count": {"$sum": 1},
                    "avg_probability": {"$avg": "$bot_probability"},
                }
            }
        ]
        results = list(db["detection_results"].aggregate(pipeline))
        stats = {"total": 0, "humans": 0, "bots": 0, "suspects": 0, "by_verdict": {}}
        for r in results:
            verdict = (r["_id"] or "UNKNOWN").upper()
            count = r["count"]
            stats["total"] += count
            stats["by_verdict"][verdict] = {
                "count": count,
                "avg_probability": round(r.get("avg_probability", 0), 4),
            }
            if verdict == "HUMAN":
                stats["humans"] = count
            elif verdict == "BOT":
                stats["bots"] = count
            elif verdict == "SUSPECT":
                stats["suspects"] = count
        return stats
    except Exception as e:
        logger.error(f"[DB] Stats failed: {e}")
        return {"total": 0, "humans": 0, "bots": 0, "suspects": 0}
