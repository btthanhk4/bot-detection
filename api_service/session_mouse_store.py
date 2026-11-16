"""Policy 40: per-session store of mouse-model scores (see ``core_ml.features.session_mouse``).

One document per session, ``{_id: sessionId, chunks: {key: p}, windows: {key: p}, updated_at}``.
Keys are frame-global (collector 1.17) or time-based (older collectors), so a resent, retried or
out-of-order snapshot writes the same paths again; concurrent snapshots each ``$set`` their own paths
and lose nothing. Documents expire two days after the session's last write. Storage failures never fail
a telemetry request: the snapshot is then judged on its own export, as under policy 39.
"""

import logging
import re
from datetime import datetime, timezone

from core_ml.features.session_mouse import (
    MAX_KEY_LENGTH,
    MAX_SESSION_CHUNKS,
    MAX_SESSION_WINDOWS,
)

logger = logging.getLogger(__name__)
COLLECTION = "session_mouse"
TTL_SECONDS = 2 * 24 * 3600
_KEY = re.compile(r"^[A-Za-z0-9:]+$")


def ensure_indexes(db) -> None:
    db[COLLECTION].create_index("updated_at", expireAfterSeconds=TTL_SECONDS, name="session_mouse_ttl")


def has_mouse_moves(data: dict) -> bool:
    """Only sessions with mouse movement need the store (phones are judged on touches)."""
    mouse = data.get("mouse") if isinstance(data.get("mouse"), dict) else {}
    records = mouse.get("records")
    return isinstance(records, list) and any(
        isinstance(record, dict) and record.get("type") == "move" and record.get("source") != "touch"
        for record in records)


def load(db, session_id):
    """The session's stored scores, or None when there are none or the store is unavailable."""
    if db is None or not isinstance(session_id, str) or not session_id:
        return None
    try:
        doc = db[COLLECTION].find_one({"_id": session_id}, {"chunks": 1, "windows": 1})
    except Exception:
        logger.exception("Session mouse evidence could not be read")
        return None
    if not doc:
        return None
    return {"chunks": doc.get("chunks") or {}, "windows": doc.get("windows") or {}}


def save(db, session_id, new) -> bool:
    """Add a snapshot's new scores to its session; idempotent, bounded, never raises."""
    if db is None or not isinstance(session_id, str) or not session_id or not isinstance(new, dict):
        return False
    fields = {}
    for group, limit in (("chunks", MAX_SESSION_CHUNKS), ("windows", MAX_SESSION_WINDOWS)):
        scores = new.get(group) if isinstance(new.get(group), dict) else {}
        for key, value in list(scores.items())[:limit]:
            if (isinstance(key, str) and len(key) <= MAX_KEY_LENGTH and _KEY.match(key)
                    and isinstance(value, float) and 0.0 <= value <= 1.0):
                fields[f"{group}.{key}"] = round(value, 6)
    if not fields:
        return False
    try:
        db[COLLECTION].update_one(
            {"_id": session_id},
            {"$set": {**fields, "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        return True
    except Exception:
        logger.exception("Session mouse evidence could not be written")
        return False
