"""Regression tests for deployment/connectivity defects found in the technical review."""
import re
from datetime import UTC, datetime
from pathlib import Path

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException
from kombu.exceptions import OperationalError

from app.api.routes import simulation_runs
from app.core.config import Settings
from app.worker.celery_app import celery_redis_url

ROOT = Path(__file__).resolve().parents[2]


def test_rediss_url_gets_celery_required_tls_parameter() -> None:
    assert celery_redis_url("rediss://u:p@h:6379/0") == "rediss://u:p@h:6379/0?ssl_cert_reqs=CERT_REQUIRED"
    assert celery_redis_url("rediss://h/0?x=1") == "rediss://h/0?x=1&ssl_cert_reqs=CERT_REQUIRED"
    assert celery_redis_url("rediss://h/0?ssl_cert_reqs=CERT_REQUIRED") == "rediss://h/0?ssl_cert_reqs=CERT_REQUIRED"
    assert celery_redis_url("redis://localhost:6379/0") == "redis://localhost:6379/0"


def test_default_gemini_model_is_not_a_retired_gemini_2_0_id() -> None:
    assert not Settings().gemini_model.startswith("gemini-2.0")


def test_simulation_queue_failure_marks_run_failed_and_returns_503(monkeypatch) -> None:
    database = mongomock.MongoClient().get_database("realityloop")
    org_id = ObjectId()
    object_id = database.simulation_runs.insert_one(
        {"run_id": "r1", "organization_id": org_id, "status": "queued", "updated_at": datetime.now(UTC)}
    ).inserted_id

    from app.worker import simulation_runs as worker_module

    def broker_down(_run_id: str) -> None:
        raise OperationalError("broker unreachable")

    monkeypatch.setattr(worker_module.execute_simulation_run, "delay", broker_down)
    with pytest.raises(HTTPException) as caught:
        simulation_runs._dispatch_run(database, object_id, "r1", org_id)
    assert caught.value.status_code == 503
    stored = database.simulation_runs.find_one({"_id": object_id})
    assert stored["status"] == "failed"
    assert stored["error"]["code"] == "queue_unavailable"


def _blueprint() -> str:
    return (ROOT / "render.yaml").read_text()


def test_blueprint_has_no_worker_or_dashboard_env_group() -> None:
    text = _blueprint()
    assert "fromGroup" not in text
    assert "type: worker" not in text


def test_gemini_key_is_declared_on_the_api_service() -> None:
    blueprint = _blueprint()
    assert "GEMINI_API_KEY" in blueprint
    assert "sync: false" in blueprint


def test_pyproject_dependencies_match_requirements_txt() -> None:
    def names(lines):
        return {re.split(r"[\[=<>]", line.strip().strip('",'), 1)[0].lower() for line in lines if line.strip() and not line.startswith("#")}

    required = names((ROOT / "backend" / "requirements.txt").read_text().splitlines())
    block = (ROOT / "backend" / "pyproject.toml").read_text().split("dependencies = [", 1)[1].split("\n]", 1)[0]
    declared = names(block.splitlines())
    assert required <= declared, f"pyproject.toml is missing: {sorted(required - declared)}"
