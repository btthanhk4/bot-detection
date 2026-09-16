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
import math
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
_indexes_ready = False
_connect_lock = threading.Lock()
_retry_after = 0.0

BSON_INT64_MIN = -(2**63)
BSON_INT64_MAX = 2**63 - 1
EVENT_SEQUENCE_LIMIT = 999_999
EVENT_ORDER_SCALE = EVENT_SEQUENCE_LIMIT + 1


class DatabasePersistenceError(RuntimeError):
    """Raised when a database write fails rather than being intentionally rejected."""


def _sanitize_bson_value(value, depth: int = 0):
    """Bound untrusted nested values to a BSON-safe, dashboard-safe subset."""
    if depth > 4:
        return None
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return max(BSON_INT64_MIN, min(BSON_INT64_MAX, value))
    if isinstance(value, float):
        return max(-1e12, min(1e12, value)) if math.isfinite(value) else 0.0
    if isinstance(value, str):
        return value[:4096]
    if isinstance(value, dict):
        sanitized = {}
        for raw_key, item in list(value.items())[:100]:
            key = str(raw_key)[:128].replace(".", "_")
            if key.startswith("$"):
                key = "_" + key[1:]
            sanitized[key] = _sanitize_bson_value(item, depth + 1)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [_sanitize_bson_value(item, depth + 1) for item in value[:100]]
    return str(value)[:4096]


def _safe_probability(value, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        numeric = default
    if not math.isfinite(numeric):
        numeric = default
    return round(max(0.0, min(1.0, numeric)), 4)

def get_db():
    """Lazy-initialize MongoDB connection with retry logic."""
    global _client, _db, _indexes_ready, _retry_after
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
            _indexes_ready = _ensure_indexes(_db)
            logger.info(f"[DB] Connected to MongoDB database: {MONGO_DB}")
            return _db
        except Exception as e:
            logger.error(f"[DB] MongoDB connection failed: {e}")
            if _client is not None:
                _client.close()
            _client = None
            _db = None
            _indexes_ready = False
            _retry_after = time.monotonic() + 10.0
            return None


def is_database_ready() -> bool:
    """Ping MongoDB so readiness detects a stale or disconnected client."""
    global _client, _db, _indexes_ready, _retry_after
    db = get_db()
    client = _client
    if db is None or client is None:
        return False
    try:
        client.admin.command("ping")
        if not _indexes_ready:
            with _connect_lock:
                if _db is db:
                    _indexes_ready = _ensure_indexes(db)
        return _indexes_ready
    except Exception as exc:
        logger.warning(f"[DB] MongoDB readiness ping failed: {exc}")
        with _connect_lock:
            # A concurrent reconnect may already have installed a healthy client.
            if _client is client:
                _client = None
                _db = None
                _indexes_ready = False
                _retry_after = time.monotonic() + 1.0
                try:
                    client.close()
                except Exception:
                    pass
        return False


def _ensure_indexes(db):
    """Create indexes for efficient queries."""
    all_ready = True
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
            managed_defaults = {
                "unique": False,
                "sparse": False,
                "expireAfterSeconds": None,
                "partialFilterExpression": None,
            }
            options_match = bool(existing) and all(
                existing.get(key, default) == options.get(key, default)
                for key, default in managed_defaults.items()
            )

            if existing and (existing_keys != keys or not options_match):
                logger.info(f"[DB] Rebuilding index {name} with updated options")
                previous_options = {
                    key: existing[key]
                    for key in ("unique", "sparse", "expireAfterSeconds", "partialFilterExpression")
                    if key in existing
                }
                collection.drop_index(name)
                try:
                    collection.create_index(keys, name=name, **options)
                except Exception:
                    # Preserve the old protection if the migration cannot be
                    # applied (for example, duplicate values block uniqueness).
                    try:
                        collection.create_index(existing_keys, name=name, **previous_options)
                    except Exception as restore_error:
                        logger.error(f"[DB] Failed to restore index {name}: {restore_error}")
                    raise
                existing = collection.index_information().get(name)

            if not existing:
                collection.create_index(keys, name=name, **options)
        except Exception as e:
            all_ready = False
            logger.warning(f"[DB] Index creation warning for {name}: {e}")
    return all_ready


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
    Returns the inserted/updated document ID, or None when the write is
    intentionally rejected. Raises DatabasePersistenceError when persistence
    is unavailable or an attempted write fails.
    """
    db = get_db()
    if db is None:
        raise DatabasePersistenceError("Database is unavailable")
    # Real connections must not accept writes until required uniqueness/TTL
    # guarantees are installed. Test doubles are intentionally unaffected.
    if db is _db and not _indexes_ready:
        raise DatabasePersistenceError("Required database indexes are unavailable")

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
        normalized_event_timestamp = None
        try:
            sequence = max(0, min(int(raw_sequence or 0), EVENT_SEQUENCE_LIMIT))
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
                normalized_event_timestamp = timestamp
                event_order = timestamp * EVENT_ORDER_SCALE + sequence
            else:
                # Backward compatibility for callers that only provide sequence.
                event_order = max(0, min(int(raw_sequence), 9007199254740991))
        except (TypeError, ValueError, OverflowError):
            normalized_event_timestamp = int(now.timestamp() * 1000)
            event_order = normalized_event_timestamp * EVENT_ORDER_SCALE + sequence

        verdict = str(analysis.get("verdict") or "UNKNOWN")[:32].upper()
        if verdict not in {"HUMAN", "BOT", "SUSPECT"}:
            verdict = "UNKNOWN"
        doc = {
            "sessionId": session_id,
            "visitorId": telemetry.get("visitorId"),
            "client_ip": telemetry.get("client_ip"),
            "pageUrl": telemetry.get("pageUrl"),
            "referrer": telemetry.get("referrer"),
            "verdict": verdict,
            "bot_probability": _safe_probability(analysis.get("bot_probability")),
            "is_bot": verdict == "BOT",
            "confidence": _safe_probability(analysis.get("confidence")),
            "breakdown": _sanitize_bson_value(analysis.get("breakdown", {})),
            "reasons": _sanitize_bson_value(analysis.get("reasons", [])),
            "mouse_points_captured": captured_count,
            # Preserve detail data without allowing malformed nested values to
            # make the whole BSON write fail.
            "fingerprint": _sanitize_bson_value(telemetry.get("fingerprint") or {}),
            "botd": _sanitize_bson_value(telemetry.get("botd") or {}),
            "mouse_stats": mouse_stats,
            "mouse_trajectory": sanitized_records[-200:],
            "event_order": event_order,
            "event_timestamp": normalized_event_timestamp,
            "event_sequence": sequence,
            "updated_at": now,
        }

        visitor_id = telemetry.get("visitorId")
        if normalized_event_timestamp is None:
            event_order_filter = {
                "$or": [{"event_order": {"$lte": event_order}}, {"event_order": {"$exists": False}}]
            }
        else:
            # Compare timestamp and sequence independently so changing the packed
            # event_order scale remains compatible with documents from older releases.
            event_order_filter = {
                "$or": [
                    {"event_timestamp": {"$lt": normalized_event_timestamp}},
                    {
                        "event_timestamp": normalized_event_timestamp,
                        "event_sequence": {"$lte": sequence},
                    },
                    {
                        # MongoDB's null match also covers documents where this
                        # field is absent, preserving sequence-only legacy rows.
                        "event_timestamp": None,
                        "event_order": {"$lte": event_order},
                    },
                ]
            }
        update_filter = {
            "sessionId": session_id,
            "$and": [
                event_order_filter,
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
        raise DatabasePersistenceError("Failed to persist detection result") from e


def get_graph_seed_events(limit: int = 10000) -> Optional[List[dict]]:
    """Load recent persisted telemetry in chronological order for graph recovery."""
    db = get_db()
    if db is None:
        return None
    try:
        cursor = db["detection_results"].find(
            {},
            {
                "_id": 0,
                "sessionId": 1,
                "visitorId": 1,
                "client_ip": 1,
                "pageUrl": 1,
                "fingerprint": 1,
                "botd": 1,
                "mouse_trajectory": 1,
                "updated_at": 1,
            },
        ).sort("updated_at", -1).limit(max(1, min(int(limit), 10000)))
        documents = list(cursor)
        return [
            {
                "sessionId": doc.get("sessionId"),
                "visitorId": doc.get("visitorId"),
                "client_ip": doc.get("client_ip"),
                "pageUrl": doc.get("pageUrl"),
                "fingerprint": doc.get("fingerprint") or {},
                "botd": doc.get("botd") or {},
                "mouse": {"records": doc.get("mouse_trajectory") or []},
            }
            for doc in reversed(documents)
        ]
    except Exception as exc:
        logger.error(f"[DB] Graph seed query failed: {exc}")
        return None


def get_recent_results(limit: int = 50) -> Optional[List[dict]]:
    """Get most recent detection results, sorted by created_at descending."""
    db = get_db()
    if db is None:
        return None

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
            created_at = doc.get("created_at")
            updated_at = doc.get("updated_at")
            effective_time = updated_at or created_at
            if effective_time and hasattr(effective_time, "timestamp"):
                doc["received_at"] = int(effective_time.timestamp() * 1000)
            if created_at and hasattr(created_at, "timestamp"):
                doc["created_at"] = int(created_at.timestamp() * 1000)
            if updated_at and hasattr(updated_at, "timestamp"):
                doc["updated_at"] = int(updated_at.timestamp() * 1000)
            results.append(_sanitize_bson_value(doc))
        return results
    except Exception as e:
        logger.error(f"[DB] Query failed: {e}")
        return None


def get_total_count() -> Optional[int]:
    """Get total number of detection results."""
    db = get_db()
    if db is None:
        return None
    try:
        return db["detection_results"].count_documents({})
    except Exception as e:
        logger.error(f"[DB] Count failed: {e}")
        return None


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
            # Fail closed for up to one hour if this process dies mid-delete.
            {"$set": {"blocked_until": now + timedelta(hours=1)}},
            upsert=True,
        )
        db["deleted_sessions"].delete_many({})
        result = db["detection_results"].delete_many({})
        db["service_control"].update_one(
            {"_id": "ingestion"},
            # Give the API process time to clear its in-memory graph and replay
            # buffer before accepting new writes.
            {"$set": {"blocked_until": datetime.now(timezone.utc) + timedelta(seconds=5)}},
            upsert=True,
        )
        return result.deleted_count
    except Exception as e:
        logger.error(f"[DB] Delete all failed: {e}")
        return None


def get_summary_stats() -> Optional[dict]:
    """Get aggregated statistics from the database."""
    db = get_db()
    if db is None:
        return None
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
                "avg_probability": _safe_probability(r.get("avg_probability")),
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
        return None
