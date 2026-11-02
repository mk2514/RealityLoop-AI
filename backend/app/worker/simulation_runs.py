from datetime import UTC, datetime
from typing import Any

from app.core.config import get_settings
from app.db.client import get_database
from app.simulation.engine import SimulationValidationError, simulate
from app.worker.celery_app import celery_app


@celery_app.task(
    name="realityloop.simulation.run",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def execute_simulation_run(self, run_id: str) -> dict[str, Any]:
    database = get_database()
    candidates = list(database.simulation_runs.find({"run_id": run_id}))
    if len(candidates) != 1:
        if not candidates:
            return {"status": "failed", "reason": "run_not_found", "run_id": run_id}
        raise RuntimeError("Simulation run lookup is ambiguous.")
    run = candidates[0]
    if run["status"] == "completed":
        return {"status": "completed", "run_id": run_id, "idempotent": True}
    if run.get("cancel_requested"):
        database.simulation_runs.update_one(
            {"_id": run["_id"]},
            {"$set": {"status": "cancelled", "updated_at": datetime.now(UTC)}},
        )
        return {"status": "cancelled", "run_id": run_id}

    database.simulation_runs.update_one(
        {"_id": run["_id"]},
        {"$set": {"status": "running", "attempt_count": run.get("attempt_count", 0) + 1, "updated_at": datetime.now(UTC)}},
    )
    try:
        result = simulate(run["snapshot"], get_settings())
    except SimulationValidationError as error:
        database.simulation_runs.update_one(
            {"_id": run["_id"]},
            {"$set": {
                "status": "failed",
                "error": {"code": "snapshot_validation_failed", "message": str(error), "details": error.errors},
                "updated_at": datetime.now(UTC),
            }},
        )
        return {"status": "failed", "run_id": run_id}
    except RuntimeError as error:
        message = str(error)
        status = "limit_exceeded" if message.startswith("SIMULATION_") else "failed"
        database.simulation_runs.update_one(
            {"_id": run["_id"]},
            {"$set": {
                "status": status,
                "error": {"code": status.upper(), "message": message, "details": []},
                "updated_at": datetime.now(UTC),
            }},
        )
        return {"status": status, "run_id": run_id}

    if database.simulation_runs.find_one({"_id": run["_id"], "cancel_requested": True}):
        database.simulation_runs.update_one(
            {"_id": run["_id"]},
            {"$set": {"status": "cancelled", "updated_at": datetime.now(UTC)}},
        )
        return {"status": "cancelled", "run_id": run_id}

    database.simulation_events.delete_many({"organization_id": run["organization_id"], "run_id": run_id})
    if result["events"]:
        database.simulation_events.insert_many([
            {**event, "organization_id": run["organization_id"], "run_id": run_id}
            for event in result["events"]
        ])
    database.simulation_runs.update_one(
        {"_id": run["_id"]},
        {"$set": {
            "status": "completed",
            "snapshot_hash": result["snapshot_hash"],
            "event_log_hash": result["event_log_hash"],
            "metrics": result["metrics"],
            "event_count": len(result["events"]),
            "updated_at": datetime.now(UTC),
        }},
    )
    return {"status": "completed", "run_id": run_id, "event_count": len(result["events"])}
