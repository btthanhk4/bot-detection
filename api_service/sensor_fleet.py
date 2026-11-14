"""Policy 35: one phone, or one emulator template, behind many claimed models.

A phone lying still reports a mean gravity magnitude and tilt set by its accelerometer's
calibration offsets, which differ from one physical device to the next (SensorID, IEEE S&P
2019). ``shared_signature_models`` counts the different Client Hints models that reported the
same values (gravity within 0.01 m/s^2, tilt within 0.1 degree) over the last 24 hours, this
session included. ``core_ml.features.server_context`` turns three or more into
``SHARED_SENSOR_SIGNATURE``.

The count only reads stored detections; it never gates detection: any failure returns None.
"""

import threading
import time
from datetime import datetime, timedelta, timezone

from core_ml.features.presence import sensor_signature, still_signature

WINDOW_HOURS = 24
GRAVITY_TOLERANCE = 0.011
TILT_TOLERANCE = 0.11
SCAN_LIMIT = 500
_MOTION = "breakdown.presence.motion"
_MODEL = "breakdown.presence.client_hints.model"


class _Memo:
    """Per-session memo: heartbeats re-score a session every few seconds."""

    def __init__(self, ttl_seconds: float = 120.0, capacity: int = 20000):
        self.ttl = ttl_seconds
        self.capacity = capacity
        self.values = {}
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            hit = self.values.get(key)
            return hit[1] if hit and hit[0] > time.monotonic() else None

    def put(self, key, value):
        with self.lock:
            if len(self.values) >= self.capacity:
                now = time.monotonic()
                self.values = {k: v for k, v in self.values.items() if v[0] > now}
                if len(self.values) >= self.capacity:
                    self.values.clear()
            self.values[key] = (time.monotonic() + self.ttl, value)


_memo = _Memo()


def shared_signature_models(db, payload: dict, session_id: str, now=None):
    """Different claimed models sharing this still phone's calibration (24 h), or None."""
    signature = sensor_signature(payload)
    if db is None or signature is None:
        return None
    gravity, tilt, model = signature
    key = (str(session_id), gravity, tilt, model)
    cached = _memo.get(key)
    if cached is not None:
        return cached
    since = (now or datetime.now(timezone.utc)) - timedelta(hours=WINDOW_HOURS)
    try:
        rows = db["detection_results"].find(
            {f"{_MOTION}.gravity": {"$gte": gravity - GRAVITY_TOLERANCE, "$lte": gravity + GRAVITY_TOLERANCE},
             f"{_MOTION}.tilt_deg": {"$gte": tilt - TILT_TOLERANCE, "$lte": tilt + TILT_TOLERANCE},
             "created_at": {"$gte": since}, "sessionId": {"$ne": str(session_id)}},
            {_MOTION: 1, _MODEL: 1},
        ).limit(SCAN_LIMIT)
        models = {model}
        for row in rows:
            presence = (row.get("breakdown") or {}).get("presence") or {}
            other = str((presence.get("client_hints") or {}).get("model") or "").strip()
            if other and still_signature(presence.get("motion") or {}) is not None:
                models.add(other)
    except Exception:
        return None
    _memo.put(key, len(models))
    return len(models)


def ensure_indexes(db) -> bool:
    try:
        db["detection_results"].create_index(
            [(f"{_MOTION}.gravity", 1), (f"{_MOTION}.tilt_deg", 1), ("created_at", -1)], name="sensor_signature",
            partialFilterExpression={f"{_MOTION}.gravity": {"$type": "number"}})
        return True
    except Exception:
        return False
