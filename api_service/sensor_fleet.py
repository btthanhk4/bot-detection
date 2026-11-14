"""Policy 35: one phone, or one emulator template, behind many claimed models.

A phone lying still reports a mean gravity magnitude and tilt set by its accelerometer's
calibration offsets, which differ from one physical device to the next (SensorID, IEEE S&P
2019). ``shared_signature_models`` counts the different Client Hints models that reported the
same values (gravity within 0.01 m/s^2, tilt within 0.1 degree) over the last 24 hours, this
session included. ``core_ml.features.server_context`` turns three or more into
``SHARED_SENSOR_SIGNATURE``.

Policy 36: ``audio_hash_sessions`` counts the other sessions of the last 24 hours that reported this
Android Chrome page's audio fingerprint (``AUDIO_NOVEL`` when none did).

The counts only read stored detections; they never gate detection: any failure returns None.
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


# ---- Policy 36: an Android Chrome audio fingerprint nobody else reported ----
# Judged only once the store holds enough recent fingerprints for "never seen" to mean something.
AUDIO_WARM_SESSIONS = 300
_AUDIO = "fingerprint.audioHash"
_warm = {"until": 0.0, "value": False}
_warm_lock = threading.Lock()


def audio_judged(payload: dict) -> bool:
    """Android Chrome itself: not a WebView, in-app browser, Samsung Internet, Firefox, Opera or Edge."""
    fingerprint = payload.get("fingerprint") if isinstance(payload.get("fingerprint"), dict) else {}
    ua = str(fingerprint.get("userAgent") or "")
    return bool("Android" in ua and "Chrome/" in ua and "; wv)" not in ua
                and not any(token in ua for token in ("SamsungBrowser", "Firefox", "OPR/", "EdgA/", "FBAN", "FBAV",
                                                      "Instagram", "musical_ly", "Bytedance", "TikTok", "Zalo", "Line/"))
                and isinstance(fingerprint.get("audioHash"), (str, int, float))
                and not isinstance(fingerprint.get("audioHash"), bool) and str(fingerprint.get("audioHash")))


def _store_warm(db, since) -> bool:
    now = time.monotonic()
    with _warm_lock:
        if _warm["until"] > now:
            return _warm["value"]
    value = db["detection_results"].count_documents(
        {"created_at": {"$gte": since}, _AUDIO: {"$exists": True}}, limit=AUDIO_WARM_SESSIONS) >= AUDIO_WARM_SESSIONS
    with _warm_lock:
        _warm.update(until=now + 600, value=value)
    return value


def audio_hash_sessions(db, payload: dict, session_id: str, now=None):
    """Other sessions (24 h) that reported this page's audio fingerprint, or None when not judged."""
    if db is None or not isinstance(payload, dict) or not audio_judged(payload):
        return None
    value = payload["fingerprint"]["audioHash"]
    key = ("audio", str(session_id), str(value))
    cached = _memo.get(key)
    if cached is not None:
        return cached
    since = (now or datetime.now(timezone.utc)) - timedelta(hours=WINDOW_HOURS)
    try:
        if not _store_warm(db, since):
            return None
        count = db["detection_results"].count_documents(
            {_AUDIO: value, "created_at": {"$gte": since}, "sessionId": {"$ne": str(session_id)}}, limit=5)
    except Exception:
        return None
    _memo.put(key, count)
    return count


def ensure_indexes(db) -> bool:
    try:
        db["detection_results"].create_index(
            [(f"{_MOTION}.gravity", 1), (f"{_MOTION}.tilt_deg", 1), ("created_at", -1)], name="sensor_signature",
            partialFilterExpression={f"{_MOTION}.gravity": {"$type": "number"}})
        db["detection_results"].create_index([(_AUDIO, 1), ("created_at", -1)], name="audio_hash_created_at",
                                             sparse=True)
        return True
    except Exception:
        return False
