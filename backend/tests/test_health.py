import pytest
from fastapi.testclient import TestClient

from app.api.routes import health
from app.core.config import Settings
from app.main import app

client = TestClient(app)


def test_liveness_returns_request_id() -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "alive"
    assert response.headers["X-Request-ID"] == response.json()["request_id"]


def test_valid_request_id_is_propagated() -> None:
    request_id = "0c6e1d3b-92cf-4e8d-a103-8c76ee2886cd"

    response = client.get("/api/v1/health/live", headers={"X-Request-ID": request_id})

    assert response.headers["X-Request-ID"] == request_id
    assert response.json()["request_id"] == request_id


def test_readiness_reports_each_dependency(monkeypatch) -> None:
    monkeypatch.setattr(health, "check_database_detail", lambda: (True, None, None))
    monkeypatch.setattr(health, "check_redis", lambda: True)
    monkeypatch.setattr(health, "check_object_storage", lambda: True)
    monkeypatch.setattr(health, "check_smtp", lambda: True)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["dependencies"] == {
        "mongodb": "ready",
        "redis": "ready",
        "object_storage": "ready",
        "smtp": "ready",
    }


def test_readiness_is_unavailable_when_a_dependency_is_down(monkeypatch) -> None:
    monkeypatch.setattr(health, "check_database_detail", lambda: (True, None, None))
    monkeypatch.setattr(health, "check_redis", lambda: False)
    monkeypatch.setattr(health, "check_object_storage", lambda: True)
    monkeypatch.setattr(health, "check_smtp", lambda: True)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["dependencies"]["redis"] == "unavailable"


def test_readiness_is_unavailable_when_smtp_is_down(monkeypatch) -> None:
    monkeypatch.setattr(health, "check_database_detail", lambda: (True, None, None))
    monkeypatch.setattr(health, "check_redis", lambda: True)
    monkeypatch.setattr(health, "check_object_storage", lambda: True)
    monkeypatch.setattr(health, "check_smtp", lambda: False)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["dependencies"]["smtp"] == "unavailable"


def test_readiness_reports_safe_mongodb_error_details(monkeypatch) -> None:
    monkeypatch.setattr(
        health,
        "check_database_detail",
        lambda: (False, "OperationFailure", 18),
    )
    monkeypatch.setattr(health, "check_smtp", lambda: True)
    monkeypatch.setattr(
        health,
        "get_settings",
        lambda: Settings(_env_file=None, mongo_only_infra=True),
    )

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["mongodb_error"] == {
        "type": "OperationFailure",
        "code": 18,
    }


def test_object_storage_readiness_checks_configured_bucket(monkeypatch) -> None:
    calls = []

    class StorageClient:
        def head_bucket(self, *, Bucket: str) -> None:
            calls.append(Bucket)

    monkeypatch.setattr(
        health,
        "get_settings",
        lambda: Settings(_env_file=None, s3_bucket="models"),
    )
    monkeypatch.setattr(health.boto3, "client", lambda *_args, **_kwargs: StorageClient())

    assert health.check_object_storage() is True
    assert calls == ["models"]


def test_object_storage_readiness_fails_without_a_bucket(monkeypatch) -> None:
    monkeypatch.setattr(
        health,
        "get_settings",
        lambda: Settings(_env_file=None, s3_bucket=""),
    )
    monkeypatch.setattr(
        health.boto3,
        "client",
        lambda *_args, **_kwargs: pytest.fail("No client should be created without a bucket"),
    )

    assert health.check_object_storage() is False


def test_http_errors_use_structured_request_aware_shape() -> None:
    request_id = "1b543c95-26bd-4857-b19a-4812f1e47b22"

    response = client.get("/api/v1/not-found", headers={"X-Request-ID": request_id})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_error"
    assert response.json()["error"]["request_id"] == request_id
    assert response.headers["X-Request-ID"] == request_id
