"""Dashboard accounts and signed session cookies.

Accounts live in the ``dashboard_users`` collection with scrypt password
hashes. A session is a stateless HMAC-signed cookie that also carries a
fingerprint of the stored hash, so changing a password revokes older sessions.
Collectors and API clients keep using the static read/admin tokens.

Roles: ``admin`` (everything), ``viewer`` (staff: reads every website) and ``customer`` (reads
only the websites in its ``sites`` list). A ``disabled`` account cannot sign in, and its open
sessions stop at the next request. Accounts an administrator creates or resets carry
``must_change_password`` until their owner picks a password.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import string
import threading
import time
from datetime import datetime, timezone
from typing import Optional

SESSION_COOKIE = "datacat_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "datacat"
# Letters, digits and . _ - @ so an email address can be the username.
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.@-]{3,64}$")
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 256
ROLES = ("admin", "viewer", "customer")

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


def generate_password(length: int = 14) -> str:
    """A random password that passes validate_new_password (shown once to the administrator)."""
    alphabet = string.ascii_letters + string.digits
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(length))
        if validate_new_password(candidate) is None:
            return candidate


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


def create_user(username: str, password: str, role: str = "admin", *, replace: bool = False,
                sites=None, display_name: str = "", must_change_password: bool = False) -> dict:
    if not USERNAME_PATTERN.match(username):
        raise ValueError("Tên đăng nhập gồm 3-64 ký tự chữ, số, '.', '_', '-' hoặc '@'")
    if role not in ROLES:
        raise ValueError("Vai trò không hợp lệ")
    sites = sorted(set(sites or [])) if role == "customer" else []
    if role == "customer" and not sites:
        raise ValueError("Tài khoản khách hàng cần ít nhất một website")
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
        "last_login_at": None, "sites": sites, "display_name": (display_name or "").strip()[:80],
        "disabled": False, "must_change_password": bool(must_change_password),
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


_PUBLIC_FIELDS = {"_id": 0, "username": 1, "role": 1, "sites": 1, "display_name": 1, "disabled": 1,
                  "must_change_password": 1, "created_at": 1, "last_login_at": 1, "password_changed_at": 1}


def _users():
    users = get_users_collection()
    if users is None:
        raise RuntimeError("Database unavailable")
    return users


def list_users() -> list:
    return sorted(_users().find({}, _PUBLIC_FIELDS), key=lambda user: user["username"].lower())


def active_admins(exclude: str = "") -> int:
    query = {"role": "admin", "disabled": {"$ne": True}}
    if exclude:
        query["username_lower"] = {"$ne": exclude.lower()}
    return _users().count_documents(query)


def update_user(username: str, changes: dict) -> dict:
    """Role, websites, display name or disabled flag. Raises KeyError or ValueError."""
    users = _users()
    current = users.find_one({"username_lower": username.lower()})
    if not current:
        raise KeyError(username)
    role = changes.get("role") or current.get("role", "viewer")
    if role not in ROLES:
        raise ValueError("Vai trò không hợp lệ")
    sites = changes["sites"] if changes.get("sites") is not None else current.get("sites") or []
    sites = sorted(set(sites)) if role == "customer" else []
    if role == "customer" and not sites:
        raise ValueError("Tài khoản khách hàng cần ít nhất một website")
    update = {"role": role, "sites": sites}
    if changes.get("display_name") is not None:
        update["display_name"] = changes["display_name"].strip()[:80]
    if changes.get("disabled") is not None:
        update["disabled"] = bool(changes["disabled"])
    users.update_one({"username_lower": username.lower()}, {"$set": update})
    invalidate_user_cache(username)
    return users.find_one({"username_lower": username.lower()}, _PUBLIC_FIELDS)


def reset_password(username: str) -> str:
    """New temporary password; the old one and every open session stop working."""
    password = generate_password()
    result = _users().update_one(
        {"username_lower": username.lower()},
        {"$set": {"password_hash": hash_password(password), "password_changed_at": datetime.now(timezone.utc),
                  "must_change_password": True}})
    if not result.matched_count:
        raise KeyError(username)
    invalidate_user_cache(username)
    return password


def delete_user(username: str) -> bool:
    deleted = _users().delete_one({"username_lower": username.lower()}).deleted_count > 0
    invalidate_user_cache(username)
    return deleted


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
    # A disabled account answers like a wrong password: no hint that it exists.
    return user if (ok and user and not user.get("disabled")) else None


def session_user(token: str) -> Optional[dict]:
    """Resolve a cookie to a live user, rejecting revoked or deleted accounts."""
    claims = read_session(token)
    if not claims:
        return None
    user = find_user(str(claims.get("u", "")))
    if not user or user.get("disabled") or _fingerprint(user["password_hash"]) != claims.get("pf"):
        return None
    role = user.get("role", "viewer")
    return {"username": user["username"], "role": role,
            # None: every website; a list: only these (customer accounts).
            "sites": list(user.get("sites") or []) if role == "customer" else None,
            "display_name": user.get("display_name") or "",
            "must_change_password": bool(user.get("must_change_password"))}
