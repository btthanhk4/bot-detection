"""Page-view tokens: proof that telemetry comes from a browser that loaded a registered page.

The collector cannot keep a secret (anyone can read it in the page), so the token is issued
by the API for each session: ``GET /api/v1/visit?sid=...`` from a registered page returns an
HMAC-signed token bound to the website and the session, valid for 24 hours. Telemetry carries
it in ``collector.pageToken``. A script that copies the tag must ask for a token for every
session it fakes, and each address gets at most ``QUOTA_PER_WINDOW`` tokens per website per
ten minutes (mobile carriers put many people behind one address, so the quota is generous).

Telemetry without a valid token is not refused: it is judged like a page the gateway did not
serve (``UNVERIFIED_PAGE_LOAD``, policy 24), which withholds a HUMAN verdict. Collectors before
1.13 have no token; they are given until ``settings.PAGE_TOKEN_REQUIRED_FROM`` to update.
"""

import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

TOKEN_TTL_SECONDS = 24 * 3600
QUOTA_PER_WINDOW = 60
QUOTA_WINDOW_SECONDS = 600
TOKEN_SDK_VERSION = (1, 13, 0)
_SECRET_ID = "page_token_secret"
_secret_lock = threading.Lock()
_secret: Optional[bytes] = None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def secret(db) -> bytes:
    """A random key kept in the database (service_control), created on first use."""
    global _secret
    with _secret_lock:
        if _secret is None:
            control = db["service_control"]
            control.update_one({"_id": _SECRET_ID}, {"$setOnInsert": {"value": secrets.token_hex(32)}}, upsert=True)
            _secret = bytes.fromhex(control.find_one({"_id": _SECRET_ID})["value"])
        return _secret


def reset_secret_cache() -> None:
    global _secret
    with _secret_lock:
        _secret = None


def _sign(key: bytes, body: bytes) -> str:
    return _b64(hmac.new(key, body, hashlib.sha256).digest()[:18])


def issue(db, site_id: str, session_id: str, now: Optional[float] = None) -> str:
    body = f"{site_id}|{session_id}|{int(now if now is not None else time.time())}".encode("utf-8")
    return _b64(body) + "." + _sign(secret(db), body)


def verify(db, token, site_id: Optional[str], session_id: Optional[str], now: Optional[float] = None) -> bool:
    """Signed by this server, for this website and session, and not expired."""
    if not isinstance(token, str) or "." not in token or len(token) > 512 or not site_id or not session_id:
        return False
    encoded, signature = token.rsplit(".", 1)
    try:
        body = _unb64(encoded)
        token_site, token_session, issued = body.decode("utf-8").split("|")
        issued = int(issued)
    except (ValueError, UnicodeDecodeError):
        return False
    if not hmac.compare_digest(_sign(secret(db), body), signature):
        return False
    age = (now if now is not None else time.time()) - issued
    return token_site == site_id and token_session == session_id and -300 <= age <= TOKEN_TTL_SECONDS


def _version(text) -> tuple:
    try:
        return tuple(int(part) for part in str(text or "").split(".")[:3])
    except ValueError:
        return ()


def page_state(db, data: dict, site_id: Optional[str], required_from: Optional[datetime] = None,
               now: Optional[datetime] = None) -> Optional[str]:
    """``verified`` | ``unknown`` (a token that does not check out) | ``missing`` for telemetry of a
    registered website; None when it cannot be judged (no website, or an old collector in the
    grace period)."""
    if not site_id:
        return None
    collector = data.get("collector") if isinstance(data.get("collector"), dict) else {}
    token = collector.get("pageToken")
    if token:
        return "verified" if verify(db, token, site_id, data.get("sessionId")) else "unknown"
    now = now or datetime.now(timezone.utc)
    if _version(collector.get("sdkVersion")) >= TOKEN_SDK_VERSION or (required_from and now >= required_from):
        return "missing"
    return None


class Quota:
    """Tokens handed to one address for one website in a sliding window (one API process)."""

    def __init__(self, limit: int = QUOTA_PER_WINDOW, window: float = QUOTA_WINDOW_SECONDS, capacity: int = 50000):
        self.limit, self.window, self.capacity = limit, window, capacity
        self._lock = threading.Lock()
        self._seen = {}

    def allow(self, ip: str, site_id: str, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        key = (str(ip), str(site_id))
        with self._lock:
            if len(self._seen) >= self.capacity:
                self._seen = {k: q for k, q in self._seen.items() if q and now - q[-1] < self.window}
            times = self._seen.setdefault(key, deque())
            while times and now - times[0] >= self.window:
                times.popleft()
            if len(times) >= self.limit:
                return False
            times.append(now)
            return True


quota = Quota()
