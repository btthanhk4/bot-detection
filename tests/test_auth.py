"""Dashboard accounts, session cookies and access control."""

import pytest
from fastapi.testclient import TestClient

from api_service import auth, main
from api_service.config import settings

CSRF = {"X-Requested-With": "datacat"}
GOOD_PASSWORD = "Str0ngPassphrase"


class FakeUsers:
    def __init__(self):
        self.docs = {}

    def create_index(self, *args, **kwargs):
        return None

    def find_one(self, query, projection=None):
        doc = self.docs.get(query["username_lower"])
        return dict(doc) if doc else None

    def insert_one(self, doc):
        if doc["username_lower"] in self.docs:
            raise ValueError("duplicate")
        self.docs[doc["username_lower"]] = dict(doc)

    def update_one(self, query, update, upsert=False):
        key = query["username_lower"]
        doc = self.docs.get(key)
        if doc is None and upsert:
            doc = dict(update.get("$setOnInsert", {}))
            self.docs[key] = doc
        if doc is not None:
            doc.update(update.get("$set", {}))

    def find(self, *args, **kwargs):
        return [dict(doc) for doc in self.docs.values()]


@pytest.fixture
def users(monkeypatch):
    fake = FakeUsers()
    monkeypatch.setattr(auth, "get_users_collection", lambda: fake)
    auth.invalidate_user_cache()
    auth._failures.clear()
    main._rate_limit_records.clear()
    auth.configure_secret("unit-test-secret")
    auth.create_user("admin", GOOD_PASSWORD, "admin")
    return fake


@pytest.fixture
def client(users, monkeypatch):
    monkeypatch.setattr(settings, "READ_TOKEN", "read-token")
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "admin-token")
    return TestClient(main.app)


def login(client, username="admin", password=GOOD_PASSWORD):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def test_password_hash_roundtrip_and_rejects_wrong_password():
    stored = auth.hash_password(GOOD_PASSWORD)
    assert stored.startswith("scrypt$")
    assert auth.verify_password(GOOD_PASSWORD, stored)
    assert not auth.verify_password("wrong", stored)
    assert not auth.verify_password(GOOD_PASSWORD, "not-a-hash")


@pytest.mark.parametrize(
    "password",
    ["short1A", "alllowercase123", "ALLUPPERCASE123", "NoDigitsHereAtAll", "xAdmin1Passwordx"],
)
def test_weak_passwords_are_rejected(password):
    assert auth.validate_new_password(password, "admin") is not None


def test_login_sets_httponly_strict_cookie(client):
    res = login(client)
    assert res.status_code == 200
    assert res.json() == {"username": "admin", "role": "admin", "must_change_password": False}
    cookie = res.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "datacat_session=" in cookie
    assert "password_hash" not in res.text and "scrypt$" not in res.text and GOOD_PASSWORD not in res.text


def test_login_failure_is_generic_and_does_not_reveal_accounts(client):
    unknown = login(client, "nobody", GOOD_PASSWORD)
    wrong = login(client, "admin", "WrongPassword1")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    assert "set-cookie" not in unknown.headers


def test_repeated_failures_lock_the_account_for_that_client(client):
    for _ in range(auth.LOCKOUT_ATTEMPTS):
        assert login(client, "admin", "WrongPassword1").status_code == 401
    locked = login(client, "admin", GOOD_PASSWORD)
    assert locked.status_code == 429
    assert int(locked.headers["retry-after"]) > 0


def test_dashboard_redirects_until_signed_in(client):
    res = client.get("/dashboard", follow_redirects=False)
    assert res.status_code == 302 and res.headers["location"] == "/login"
    login_page = client.get("/login")
    assert login_page.status_code == 200
    # The admin pages may not be framed by another site.
    assert login_page.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in login_page.headers["content-security-policy"]
    login(client)
    assert client.get("/dashboard", follow_redirects=False).status_code == 200
    assert client.get("/login", follow_redirects=False).headers["location"] == "/dashboard"


def test_cookie_grants_read_access_but_tokens_still_work(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"X-Read-Token": "read-token"}).status_code == 200
    login(client)
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["username"] == "admin"


def test_cookie_writes_require_csrf_header(client, monkeypatch):
    login(client)
    monkeypatch.setattr("api_service.database.delete_session", lambda sid: True)
    monkeypatch.setattr(main, "delete_research_data", lambda session_id=None: None)
    assert client.delete("/api/v1/sessions/abc").status_code == 403
    assert client.delete("/api/v1/sessions/abc", headers=CSRF).status_code == 200


def test_viewer_cannot_use_admin_endpoints(client, users):
    auth.create_user("viewer", GOOD_PASSWORD, "viewer")
    login(client, "viewer")
    assert client.get("/api/v1/auth/me").json()["role"] == "viewer"
    assert client.delete("/api/v1/sessions/abc", headers=CSRF).status_code == 401


def test_forged_or_expired_sessions_are_rejected(client, users):
    user = users.docs["admin"]
    good = auth.issue_session("admin", "admin", user["password_hash"], 60)
    expired = auth.issue_session("admin", "admin", user["password_hash"], -5)
    tampered = good[:-3] + ("AAA" if not good.endswith("AAA") else "BBB")
    for token in (expired, tampered, "garbage", good.split(".")[0] + ".x"):
        client.cookies.set(auth.SESSION_COOKIE, token)
        assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.set(auth.SESSION_COOKIE, good)
    assert client.get("/api/v1/auth/me").status_code == 200


def test_changing_password_revokes_other_sessions(client, users):
    login(client)
    old_cookie = client.cookies.get(auth.SESSION_COOKIE)
    res = client.post("/api/v1/auth/password", headers=CSRF, json={
        "current_password": GOOD_PASSWORD, "new_password": "BrandNewPassw0rd"})
    assert res.status_code == 200
    # The caller gets a fresh cookie; the old one no longer works.
    assert client.get("/api/v1/auth/me").status_code == 200
    other = TestClient(main.app)
    other.cookies.set(auth.SESSION_COOKIE, old_cookie)
    auth.invalidate_user_cache()
    assert other.get("/api/v1/auth/me").status_code == 401
    assert login(TestClient(main.app), password="BrandNewPassw0rd").status_code == 200


def test_password_change_validates_current_and_new_password(client):
    login(client)
    wrong = client.post("/api/v1/auth/password", headers=CSRF, json={
        "current_password": "Nope", "new_password": "BrandNewPassw0rd"})
    weak = client.post("/api/v1/auth/password", headers=CSRF, json={
        "current_password": GOOD_PASSWORD, "new_password": "weak"})
    assert wrong.status_code == 403 and weak.status_code == 422


def test_logout_clears_cookie(client):
    login(client)
    res = client.post("/api/v1/auth/logout", headers=CSRF)
    assert res.status_code == 200
    header = res.headers["set-cookie"].lower()
    assert 'datacat_session=""' in header or "max-age=0" in header


def test_public_assets_are_whitelisted(client):
    assert client.get("/assets/datacat-logo.png").status_code == 200
    assert client.get("/assets/..%2Fmain.py").status_code == 404
    assert client.get("/assets/secret.txt").status_code == 404


def test_manage_cli_creates_and_resets_account(users, capsys):
    from api_service import manage

    assert manage.main(["create-admin", "--username", "owner"]) == 0
    printed = capsys.readouterr().out
    password = printed.split(": ")[-1].strip()
    assert auth.authenticate("owner", password)
    assert manage.main(["create-admin", "--username", "owner"]) == 1
    assert manage.main(["reset-password", "--username", "owner", "--password", "AnotherPassw0rd1"]) == 0
    assert not auth.authenticate("owner", password)
    assert auth.authenticate("owner", "AnotherPassw0rd1")
