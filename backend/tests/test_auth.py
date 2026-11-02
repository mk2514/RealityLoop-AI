from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import mongomock
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from app.api.routes import auth
from app.core.config import Settings
from app.core.rate_limit import check_rate_limit
from app.core.security import hash_token
from app.main import app


class TransactionSession:
    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def with_transaction(self, callback):
        return callback(None)


class TransactionClient:
    def start_session(self) -> TransactionSession:
        return TransactionSession()


class MemoryRateLimiter:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def eval(self, _script: str, _key_count: int, key: str, _window: int) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


@pytest.fixture
def auth_environment(monkeypatch):
    database = mongomock.MongoClient().get_database("realityloop")
    database.organizations.create_index("slug", unique=True)
    database.users.create_index("email", unique=True)
    database.organization_memberships.create_index(
        [("organization_id", 1), ("user_id", 1)],
        unique=True,
    )
    database.factories.create_index([("organization_id", 1), ("_id", 1)])
    messages: list[tuple[str, str, str]] = []
    settings = Settings(_env_file=None)
    monkeypatch.setattr(auth, "get_database", lambda: database)
    monkeypatch.setattr(auth, "get_mongo_client", TransactionClient)
    monkeypatch.setattr(auth, "_rate_limit", lambda *_args: None)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(auth, "send_email", lambda *args: messages.append(args))
    from app.api.routes import assets

    monkeypatch.setattr(assets, "get_database", lambda: database)
    monkeypatch.setattr(assets, "get_mongo_client", TransactionClient)
    return database, messages, settings


def csrf_headers(client: TestClient) -> dict[str, str]:
    response = client.get("/api/v1/csrf")
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def register_and_verify(
    client: TestClient,
    messages: list[tuple[str, str, str]],
    *,
    email: str,
    organization: str,
) -> None:
    response = client.post(
        "/api/v1/auth/register",
        headers=csrf_headers(client),
        json={
            "full_name": "Factory Owner",
            "email": email,
            "password": "correct horse battery",
            "organization_name": organization,
        },
    )
    assert response.status_code == 202
    assert len(messages) > 0
    verification_link = urlparse(messages[-1][2].splitlines()[2])
    token = parse_qs(verification_link.query)["token"][0]
    verified = client.post(
        "/api/v1/auth/verify",
        headers=csrf_headers(client),
        json={"token": token},
    )
    assert verified.status_code == 200


def login(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        headers=csrf_headers(client),
        json={"email": email, "password": "correct horse battery"},
    )
    assert response.status_code == 200
    assert response.json()["redirect"] == "/app/dashboard"
    return response.cookies


def test_registration_verification_login_and_session_cookie(auth_environment) -> None:
    database, messages, settings = auth_environment
    client = TestClient(app)
    register_and_verify(
        client,
        messages,
        email="owner@example.com",
        organization="Example Manufacturing",
    )

    assert database.users.count_documents({}) == 1
    assert database.organizations.count_documents({}) == 1
    membership = database.organization_memberships.find_one({})
    assert membership["role"] == "owner"
    assert database.auth_tokens.count_documents({}) == 0

    response = client.post(
        "/api/v1/auth/verify",
        headers=csrf_headers(client),
        json={"token": parse_qs(urlparse(messages[0][2].splitlines()[2]).query)["token"][0]},
    )
    assert response.status_code == 400

    login(client, "owner@example.com")
    session_cookie = client.cookies.get(settings.session_cookie_name)
    assert session_cookie
    stored_session = database.sessions.find_one({})
    assert stored_session["_id"] == hash_token(session_cookie)
    assert stored_session["_id"] != session_cookie
    assert client.get("/api/v1/auth/me").json()["organization"]["name"] == "Example Manufacturing"


def test_csrf_and_protected_route_rejection(auth_environment) -> None:
    _database, _messages, _settings = auth_environment
    client = TestClient(app)

    protected = client.get("/api/v1/dashboard")
    assert protected.status_code == 401
    rejected = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Owner",
            "email": "owner@example.com",
            "password": "correct horse battery",
            "organization_name": "Factory",
        },
    )
    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "http_error"


def test_expired_verification_and_session_tokens_are_rejected(auth_environment) -> None:
    database, messages, settings = auth_environment
    client = TestClient(app)
    registered = client.post(
        "/api/v1/auth/register",
        headers=csrf_headers(client),
        json={
            "full_name": "Owner",
            "email": "owner@example.com",
            "password": "correct horse battery",
            "organization_name": "Factory",
        },
    )
    assert registered.status_code == 202
    token = parse_qs(urlparse(messages[-1][2].splitlines()[2]).query)["token"][0]
    database.auth_tokens.update_one(
        {"_id": hash_token(token)},
        {"$set": {"expires_at": datetime.now(UTC) - timedelta(seconds=1)}},
    )
    expired_verification = client.post(
        "/api/v1/auth/verify",
        headers=csrf_headers(client),
        json={"token": token},
    )
    assert expired_verification.status_code == 400

    database.users.update_one(
        {"email": "owner@example.com"},
        {"$set": {"email_verified_at": datetime.now(UTC)}},
    )
    login(client, "owner@example.com")
    database.sessions.update_one(
        {},
        {"$set": {"expires_at": datetime.now(UTC) - timedelta(seconds=1)}},
    )
    expired_session = client.get("/api/v1/auth/me")
    assert expired_session.status_code == 401


def test_password_recovery_is_generic_single_use_and_revokes_sessions(auth_environment) -> None:
    database, messages, _settings = auth_environment
    client = TestClient(app)
    register_and_verify(
        client,
        messages,
        email="owner@example.com",
        organization="Example Manufacturing",
    )
    login(client, "owner@example.com")

    existing = client.post(
        "/api/v1/auth/password-reset/request",
        headers=csrf_headers(client),
        json={"email": "owner@example.com"},
    )
    missing = client.post(
        "/api/v1/auth/password-reset/request",
        headers=csrf_headers(client),
        json={"email": "missing@example.com"},
    )
    assert existing.status_code == missing.status_code == 202
    assert existing.json() == missing.json()
    token = parse_qs(urlparse(messages[-1][2].splitlines()[2]).query)["token"][0]

    reset = client.post(
        "/api/v1/auth/password-reset/confirm",
        headers=csrf_headers(client),
        json={"token": token, "password": "another correct horse"},
    )
    assert reset.status_code == 200
    assert database.sessions.count_documents({}) == 0
    reused = client.post(
        "/api/v1/auth/password-reset/confirm",
        headers=csrf_headers(client),
        json={"token": token, "password": "yet another correct horse"},
    )
    assert reused.status_code == 400
    assert client.get("/api/v1/auth/me").status_code == 401


def test_expired_password_reset_token_is_rejected(auth_environment) -> None:
    database, messages, _settings = auth_environment
    client = TestClient(app)
    register_and_verify(
        client,
        messages,
        email="owner@example.com",
        organization="Example Manufacturing",
    )
    response = client.post(
        "/api/v1/auth/password-reset/request",
        headers=csrf_headers(client),
        json={"email": "owner@example.com"},
    )
    assert response.status_code == 202
    token = parse_qs(urlparse(messages[-1][2].splitlines()[2]).query)["token"][0]
    database.auth_tokens.update_one(
        {"_id": hash_token(token)},
        {"$set": {"expires_at": datetime.now(UTC) - timedelta(seconds=1)}},
    )

    expired = client.post(
        "/api/v1/auth/password-reset/confirm",
        headers=csrf_headers(client),
        json={"token": token, "password": "another correct horse"},
    )
    assert expired.status_code == 400


def test_logout_revokes_the_server_managed_session(auth_environment) -> None:
    database, messages, _settings = auth_environment
    client = TestClient(app)
    register_and_verify(
        client,
        messages,
        email="owner@example.com",
        organization="Example Manufacturing",
    )
    login(client, "owner@example.com")
    assert client.get("/api/v1/auth/me").status_code == 200

    response = client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    assert response.status_code == 200
    assert database.sessions.count_documents({}) == 0
    assert client.get("/api/v1/auth/me").status_code == 401


def test_factories_are_isolated_between_independent_organizations(auth_environment) -> None:
    database, messages, _settings = auth_environment
    owner_client = TestClient(app)
    register_and_verify(
        owner_client,
        messages,
        email="owner-one@example.com",
        organization="Factory One",
    )
    owner_client.post(
        "/api/v1/auth/login",
        headers=csrf_headers(owner_client),
        json={"email": "owner-one@example.com", "password": "correct horse battery"},
    )
    created = owner_client.post(
        "/api/v1/factories",
        headers=csrf_headers(owner_client),
        json={"name": "North Plant"},
    )
    assert created.status_code == 201

    other_client = TestClient(app)
    register_and_verify(
        other_client,
        messages,
        email="owner-two@example.com",
        organization="Factory Two",
    )
    login(other_client, "owner-two@example.com")
    second_user = database.users.find_one({"email": "owner-two@example.com"})
    database.organization_memberships.update_one(
        {"user_id": second_user["_id"]},
        {"$set": {"role": "viewer"}},
    )

    denied = other_client.get(f"/api/v1/factories/{created.json()['id']}")
    assert denied.status_code == 404
    assert other_client.get("/api/v1/factories").json()["factories"] == []
    assert other_client.get("/api/v1/dashboard").json()["factory_count"] == 0
    role_denied = other_client.post(
        "/api/v1/factories",
        headers=csrf_headers(other_client),
        json={"name": "Unauthorized Factory"},
    )
    assert role_denied.status_code == 403


def test_rate_limiter_throttles_and_fails_closed() -> None:
    limiter = MemoryRateLimiter()
    check_rate_limit(
        limiter,
        action="login",
        identity="user@example.com",
        ip_address="127.0.0.1",
        limit=1,
        window_seconds=60,
    )
    with pytest.raises(HTTPException) as limited:
        check_rate_limit(
            limiter,
            action="login",
            identity="user@example.com",
            ip_address="127.0.0.1",
            limit=1,
            window_seconds=60,
        )
    assert limited.value.status_code == 429

    class UnavailableRateLimiter:
        def eval(self, *_args):
            raise RedisConnectionError("redis unavailable")

    with pytest.raises(HTTPException) as unavailable:
        check_rate_limit(
            UnavailableRateLimiter(),
            action="login",
            identity="user@example.com",
            ip_address="127.0.0.1",
            limit=1,
            window_seconds=60,
        )
    assert unavailable.value.status_code == 503


def test_login_endpoint_applies_authentication_rate_limits(
    auth_environment,
    monkeypatch,
) -> None:
    _database, _messages, settings = auth_environment
    settings.auth_login_limit = 1
    limiter = MemoryRateLimiter()

    def apply_limit(request, action, identity, limit):
        check_rate_limit(
            limiter,
            action=action,
            identity=identity,
            ip_address=request.client.host,
            limit=limit,
            window_seconds=60,
        )

    monkeypatch.setattr(auth, "_rate_limit", apply_limit)
    client = TestClient(app)
    headers = csrf_headers(client)
    payload = {"email": "missing@example.com", "password": "unrecognized password"}

    first = client.post("/api/v1/auth/login", headers=headers, json=payload)
    second = client.post("/api/v1/auth/login", headers=headers, json=payload)

    assert first.status_code == 401
    assert second.status_code == 429
