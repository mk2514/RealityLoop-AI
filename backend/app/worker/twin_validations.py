from datetime import UTC, datetime
from typing import Any

from app.db.client import get_database
from app.worker.celery_app import celery_app


@celery_app.task(
    name="realityloop.twin_validation.run",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def execute_twin_validation(self, validation_id: str) -> dict[str, Any]:
    database = get_database()
    candidates = list(database.twin_validations.find({"validation_id": validation_id}))
    if len(candidates) != 1:
        return {"status": "failed", "reason": "validation_not_found", "validation_id": validation_id}
    record = candidates[0]
    if record["status"] != "queued":
        return {"status": record["status"], "validation_id": validation_id, "idempotent": True}

    database.twin_validations.update_one(
        {"_id": record["_id"]},
        {"$set": {"status": "running", "attempt_count": record.get("attempt_count", 0) + 1, "updated_at": datetime.now(UTC)}},
    )

    from app.api.routes.twin_validations import evaluate_validation

    result = evaluate_validation(database, record)
    database.twin_validations.update_one(
        {"_id": record["_id"]},
        {"$set": {
            "status": result["status"],
            "metrics": result["metrics"],
            "operating_envelope": result["operating_envelope"],
            "evidence": result["evidence"],
            "updated_at": datetime.now(UTC),
        }},
    )
    return {"status": result["status"], "validation_id": validation_id}
