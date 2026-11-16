"""Policy 41: trajectory signatures shared across sessions (``core_ml.features.trajectory_signature``).

Only a fixed eighth of the signatures is kept (those whose hash starts with 0 or 1), the same eighth
for every session, so a replayed path still meets itself while the collection stays small. Each
document is one (signature, session) pair with the page instance it came from, and expires after
seven days. For a snapshot the API records the new signatures, then reports the most signatures the
whole session shares with any one other session, counting only other pages: a collector that rotates
its session id keeps re-sending the same page, which is not a replay. Failures never fail a request.
"""

import hashlib
import logging
from datetime import datetime, timezone

from pymongo.errors import BulkWriteError, DuplicateKeyError

from core_ml.features.trajectory_signature import signatures

logger = logging.getLogger(__name__)
COLLECTION = "trajectory_signatures"
TTL_SECONDS = 7 * 24 * 3600
SAMPLE_PREFIXES = ("0", "1")
MAX_PER_SNAPSHOT = 400
MAX_PER_SESSION = 3000


def ensure_indexes(db) -> None:
    db[COLLECTION].create_index("h", name="trajectory_signature")
    db[COLLECTION].create_index("s", name="trajectory_session")
    db[COLLECTION].create_index("created_at", expireAfterSeconds=TTL_SECONDS, name="trajectory_signature_ttl")


def sampled_signatures(records) -> list:
    return sorted(h for h in signatures(records) if h.startswith(SAMPLE_PREFIXES))[:MAX_PER_SNAPSHOT]


def _page(payload) -> str:
    collector = payload.get("collector") if isinstance(payload.get("collector"), dict) else {}
    page = collector.get("pageInstanceId")
    return hashlib.sha256(page.encode("utf-8", "replace")).hexdigest()[:12] if isinstance(page, str) and page else ""


def replay_overlap(db, payload, session_id):
    """The most sampled signatures this session shares with one other session's other pages, or None."""
    if db is None or not isinstance(session_id, str) or not session_id:
        return None
    mouse = payload.get("mouse") if isinstance(payload.get("mouse"), dict) else {}
    try:
        own = sampled_signatures(mouse.get("records") or [])
        page = _page(payload)
        collection = db[COLLECTION]
        if own:
            now = datetime.now(timezone.utc)
            try:
                # Signatures already recorded for this session stay as they were (duplicate _id).
                collection.insert_many([{"_id": f"{h}:{session_id}"[:200], "h": h, "s": session_id, "p": page,
                                         "created_at": now} for h in own], ordered=False)
            except (BulkWriteError, DuplicateKeyError):
                pass
        mine = collection.distinct("h", {"s": session_id})[:MAX_PER_SESSION]
        if not mine:
            return 0
        pages = set(collection.distinct("p", {"s": session_id}))
        best = list(collection.aggregate([
            {"$match": {"h": {"$in": mine}, "s": {"$ne": session_id}, "p": {"$nin": list(pages)}}},
            {"$group": {"_id": "$s", "n": {"$sum": 1}}},
            {"$sort": {"n": -1}},
            {"$limit": 1},
        ]))
        return int(best[0]["n"]) if best else 0
    except Exception:
        logger.exception("Trajectory signatures could not be checked")
        return None
