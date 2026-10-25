"""Dashboard accounts and signed session cookies.

Accounts live in the ``dashboard_users`` collection with scrypt password
hashes. A session is a stateless HMAC-signed cookie that also carries a
fingerprint of the stored hash, so changing a password revokes older sessions.
Collectors and API clients keep using the static read/admin tokens.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Optional

SESSION_COOKIE = "datacat_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "datacat"
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 256
ROLES = ("admin", "viewer")

_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_KEYLEN = 32
_USER_CACHE_SECONDS = 10.0

_session_secret: bytes = b""
_secret_lock = threading.Lock()
_user_cache: dict = {}
_user_cache_lock = threading.Lock()
_failures: dict = {}
_failures_lock = threading.Lock()
LOCKOUT_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60

# Used to spend equal time on unknown usernames.
_DUMMY_HASH = None


def configure_secret(value: str) -> None:
    """Install the signing secret; an empty value yields a per-process secret."""
    global _session_secret
    with _secret_lock:
        _session_secret = value.encode("utf-8") if value else secrets.token_bytes(32)


def _secret() -> bytes:
    if not _session_secret:
        configure_secret("")
    return _session_secret


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
        dklen=_SCRYPT_KEYLEN, maxmem=64 * 1024 * 1024,
    )
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P,
        base64.b64encode(salt).decode("ascii"), base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p),
            dklen=len(expected), maxmem=64 * 1024 * 1024,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def validate_new_password(password: str, username: str = "") -> Optional[str]:
    """Return a human-readable problem, or None when the password is acceptable."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự"
    if len(password) > MAX_PASSWORD_LENGTH:
        return "Mật khẩu quá dài"
    if username and username.lower() in password.lower():
        return "Mật khẩu không được chứa tên đăng nhập"
    if not (any(c.islower() for c in password) and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)):
        return "Mật khẩu cần có chữ hoa, chữ thường và chữ số"
    return None


def _fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_session(username: str, role: str, password_hash: str, ttl_seconds: int) -> str:
    now = int(time.time())
    body = _b64(json.dumps(
        {"u": username, "r": role, "iat": now, "exp": now + ttl_seconds, "pf": _fingerprint(password_hash)},
        separators=(",", ":"),
    ).encode("utf-8"))
    signature = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}"


def read_session(token: str) -> Optional[dict]:
    """Verify signature and expiry; the caller still checks the user record."""
    if not token or "." not in token or len(token) > 1024:
        return None
    body, _, signature = token.partition(".")
    expected = _b64(hmac.new(_secret(), body.encode("ascii", "ignore"), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        claims = json.loads(_unb64(body))
    except (ValueError, TypeError):
        return None
    if not isinstance(claims, dict) or int(claims.get("exp", 0)) < time.time():
        return None
    return claims


def get_users_collection():
    from api_service.database import get_db

    db = get_db()
    return None if db is None else db["dashboard_users"]


def ensure_user_indexes() -> None:
    users = get_users_collection()
    if users is not None:
        users.create_index("username", unique=True)


def find_user(username: str, use_cache: bool = True) -> Optional[dict]:
    key = username.lower()
    now = time.monotonic()
    if use_cache:
        with _user_cache_lock:
            cached = _user_cache.get(key)
            if cached and now - cached[0] < _USER_CACHE_SECONDS:
                return cached[1]
    users = get_users_collection()
    if users is None:
        return None
    user = users.find_one({"username_lower": key}, {"_id": 0})
    with _user_cache_lock:
        _user_cache[key] = (now, user)
    return user


def invalidate_user_cache(username: str = "") -> None:
    with _user_cache_lock:
        if username:
            _user_cache.pop(username.lower(), None)
        else:
            _user_cache.clear()


def create_user(username: str, password: str, role: str = "admin", *, replace: bool = False) -> dict:
    if not USERNAME_PATTERN.match(username):
        raise ValueError("Tên đăng nhập gồm 3-32 ký tự chữ, số, '.', '_' hoặc '-'")
    if role not in ROLES:
        raise ValueError("Vai trò không hợp lệ")
    problem = validate_new_password(password, username)
    if problem:
        raise ValueError(problem)
    users = get_users_collection()
    if users is None:
        raise RuntimeError("Database unavailable")
    ensure_user_indexes()
    now = datetime.now(timezone.utc)
    document = {
        "username": username, "username_lower": username.lower(), "role": role,
        "password_hash": hash_password(password), "created_at": now, "password_changed_at": now,
        "last_login_at": None,
    }
    if replace:
        users.update_one(
            {"username_lower": username.lower()},
            {"$set": {k: v for k, v in document.items() if k != "created_at"},
             "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
    else:
        users.insert_one(document)
    invalidate_user_cache(username)
    return {"username": username, "role": role}


def _failure_key(ip: str, username: str) -> str:
    return f"{ip}|{username.lower()}"


def lockout_remaining(ip: str, username: str) -> int:
    with _failures_lock:
        record = _failures.get(_failure_key(ip, username))
        if not record or record[0] < LOCKOUT_ATTEMPTS:
            return 0
        remaining = int(record[1] + LOCKOUT_SECONDS - time.monotonic())
        if remaining <= 0:
            _failures.pop(_failure_key(ip, username), None)
            return 0
        return remaining


def record_failure(ip: str, username: str) -> None:
    key = _failure_key(ip, username)
    now = time.monotonic()
    with _failures_lock:
        if len(_failures) > 5000:
            for stale in [k for k, v in _failures.items() if now - v[1] > LOCKOUT_SECONDS]:
                del _failures[stale]
        count, _last = _failures.get(key, (0, now))
        _failures[key] = (count + 1, now)


def clear_failures(ip: str, username: str) -> None:
    with _failures_lock:
        _failures.pop(_failure_key(ip, username), None)


def authenticate(username: str, password: str) -> Optional[dict]:
    """Return the user record on success. Always performs one scrypt verification."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("dummy-password-for-timing")
    user = find_user(username, use_cache=False) if USERNAME_PATTERN.match(username or "") else None
    stored = user["password_hash"] if user else _DUMMY_HASH
    ok = verify_password(password or "", stored)
    return user if (ok and user) else None


def session_user(token: str) -> Optional[dict]:
    """Resolve a cookie to a live user, rejecting revoked or deleted accounts."""
    claims = read_session(token)
    if not claims:
        return None
    user = find_user(str(claims.get("u", "")))
    if not user or _fingerprint(user["password_hash"]) != claims.get("pf"):
        return None
    return {"username": user["username"], "role": user.get("role", "viewer")}
