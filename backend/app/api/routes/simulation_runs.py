from datetime import UTC, datetime
from typing import Any, Literal

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from kombu.exceptions import OperationalError
from pydantic import BaseModel, ConfigDict, Field

from app.api.routes.auth import Principal, get_current_principal, require_csrf, require_roles
from app.db.client import get_database, get_mongo_client
from app.simulation.engine import SimulationValidationError, build_run_snapshot, validate_snapshot

router = APIRouter(dependencies=[Depends(require_csrf)])
CAN_RUN = ("owner", "administrator", "engineer")
CAN_CANCEL = ("owner", "administrator", "engineer")


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: str = Field(min_length=1, max_length=128)
    product_id: str = Field(min_length=1, max_length=128)
    entity_count: int = Field(default=100, ge=1, le=100_000)
    simulated_time_seconds: float = Field(gt=0, le=31_536_000)
    seed: int = Field(default=0, ge=0, le=2_147_483_647)
    assumptions: dict[str, Any] | None = None
    run_idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


def _object_id(value: str, label: str = "Production line") -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=404, detail=f"{label} not found.")
    return ObjectId(value)


def _serialize(document: dict[str, Any] | None) -> dict[str, Any] | None:
    if document is None:
        return None
    return {
        ("id" if key == "_id" else key): (
            str(value) if isinstance(value, ObjectId)
            else value.isoformat() if isinstance(value, datetime)
            else _serialize(value) if isinstance(value, dict)
            else [_serialize(item) if isinstance(item, dict) else item for item in value]
            if isinstance(value, list)
            else value
        )
        for key, value in document.items()
    }


def _scoped_run(run_id: str, organization_id: ObjectId) -> dict[str, Any]:
    run = get_database().simulation_runs.find_one(
        {"organization_id": organization_id, "run_id": run_id},
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Simulation run not found.")
    return run


@router.post("/lines/{line_id}/versions/{version}/runs")
def create_simulation_run(
    line_id: str,
    version: int,
    payload: RunRequest,
    principal: Principal = Depends(require_roles(*CAN_RUN)),
) -> dict[str, Any]:
    database = get_database()
    line_object_id = _object_id(line_id)
    line = database.production_lines.find_one(
        {"_id": line_object_id, "organization_id": principal.organization_id, "archived_at": None},
    )
    if line is None:
        raise HTTPException(status_code=404, detail="Production line not found.")
    line_version = database.production_line_versions.find_one(
        {
            "organization_id": principal.organization_id,
            "line_id": line_object_id,
            "version": version,
        },
    )
    if line_version is None:
        raise HTTPException(status_code=404, detail="Production line version not found.")
    machine_ids = {
        node["machine_id"]
        for node in line_version["model"].get("layout", {}).get("nodes", [])
        if node.get("type") == "machine" and node.get("machine_id")
    }
    machine_documents = list(database.machines.find({
        "_id": {"$in": [ObjectId(machine_id) for machine_id in machine_ids if ObjectId.is_valid(machine_id)]},
        "organization_id": principal.organization_id,
        "archived_at": None,
    })) if machine_ids else []
    factory = database.factories.find_one({
        "_id": line.get("factory_id"),
        "organization_id": principal.organization_id,
        "archived_at": None,
    })
    snapshot = build_run_snapshot(
        line_version={"model": line_version["model"]},
        line_id=line_id,
        version=version,
        machines=machine_documents,
        factory=factory,
        recipe_id=payload.recipe_id,
        product_id=payload.product_id,
        seed=payload.seed,
        entity_count=payload.entity_count,
        simulated_time_seconds=payload.simulated_time_seconds,
        assumptions=payload.assumptions,
    )
    errors = validate_snapshot(snapshot)
    if errors:
        raise HTTPException(
            status_code=422,
            detail={"code": "SIMULATION_VALIDATION_FAILED", "errors": errors},
        )

    existing = None
    if payload.run_idempotency_key:
        existing = database.simulation_runs.find_one({
            "organization_id": principal.organization_id,
            "run_idempotency_key": payload.run_idempotency_key,
        })
    if existing is not None:
        return {"run": _serialize(existing)}

    from uuid import uuid4
    run_id = uuid4().hex
    now = datetime.now(UTC)
    record = {
        "run_id": run_id,
        "organization_id": principal.organization_id,
        "line_id": line_object_id,
        "line_version": version,
        "created_by": principal.user_id,
        "created_at": now,
        "updated_at": now,
        "status": "queued",
        "attempt_count": 0,
        "seed": payload.seed,
        "snapshot": snapshot,
        "snapshot_hash": None,
        "metrics": None,
        "event_log_hash": None,
        "error": None,
        "cancel_requested": False,
        "event_count": 0,
        "data_kind": "simulated",
    }
    if payload.run_idempotency_key:
        record["run_idempotency_key"] = payload.run_idempotency_key
    database.simulation_runs.insert_one(record)
    _dispatch_run(database, record["_id"], run_id, principal.organization_id)
    return {"run": _serialize(record)}


def _dispatch_run(database: Any, object_id: Any, run_id: str, organization_id: Any) -> None:
    """Enqueue a run; if the broker is down, mark it failed instead of leaving it queued."""
    from app.worker.simulation_runs import execute_simulation_run

    try:
        execute_simulation_run.delay(run_id)
    except OperationalError as error:
        database.simulation_runs.update_one(
            {"_id": object_id, "organization_id": organization_id, "status": "queued"},
            {"$set": {
                "status": "failed",
                "error": {"code": "queue_unavailable", "message": "The background worker could not be reached. Retry this run.", "details": []},
                "updated_at": datetime.now(UTC),
            }},
        )
        raise HTTPException(status_code=503, detail="The background worker is unavailable. The run was recorded as failed; retry it.") from error


@router.get("/simulation/runs")
def list_simulation_runs(
    line_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    query: dict[str, Any] = {"organization_id": principal.organization_id}
    if line_id:
        query["line_id"] = _object_id(line_id)
    runs = list(get_database().simulation_runs.find(query).sort("created_at", -1).limit(limit))
    return {"runs": [_serialize(run) for run in runs]}


@router.get("/simulation/runs/{run_id}")
def get_simulation_run(
    run_id: str,
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    return {"run": _serialize(_scoped_run(run_id, principal.organization_id))}


@router.get("/simulation/runs/{run_id}/events")
def get_simulation_events(
    run_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2_000),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    _scoped_run(run_id, principal.organization_id)
    cursor = get_database().simulation_events.find(
        {"organization_id": principal.organization_id, "run_id": run_id},
    ).sort([("sequence", 1)]).skip(offset).limit(limit)
    events = list(cursor)
    return {"events": [_serialize(event) for event in events], "offset": offset, "limit": limit}


@router.post("/simulation/runs/{run_id}/cancel")
def cancel_simulation_run(
    run_id: str,
    principal: Principal = Depends(require_roles(*CAN_CANCEL)),
) -> dict[str, Any]:
    database = get_database()
    run = _scoped_run(run_id, principal.organization_id)
    if run["status"] in {"completed", "failed", "cancelled"}:
        return {"run": _serialize(run)}
    database.simulation_runs.update_one(
        {"_id": run["_id"], "organization_id": principal.organization_id},
        {"$set": {"cancel_requested": True, "status": "cancelled", "updated_at": datetime.now(UTC)}},
    )
    return {"run": _serialize(database.simulation_runs.find_one({"_id": run["_id"], "organization_id": principal.organization_id}))}


@router.post("/simulation/runs/{run_id}/retry")
def retry_simulation_run(
    run_id: str,
    principal: Principal = Depends(require_roles(*CAN_RUN)),
) -> dict[str, Any]:
    database = get_database()
    run = _scoped_run(run_id, principal.organization_id)
    if run["status"] == "completed":
        raise HTTPException(status_code=409, detail="A completed run cannot be recomputed. Clone it as a new run instead.")
    now = datetime.now(UTC)
    database.simulation_runs.update_one(
        {"_id": run["_id"], "organization_id": principal.organization_id},
        {"$set": {"status": "queued", "cancel_requested": False, "error": None, "updated_at": now}},
    )
    run = database.simulation_runs.find_one({"_id": run["_id"], "organization_id": principal.organization_id})
    _dispatch_run(database, run["_id"], run_id, principal.organization_id)
    return {"run": _serialize(run)}
