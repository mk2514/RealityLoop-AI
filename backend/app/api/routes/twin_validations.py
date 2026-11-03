from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from kombu.exceptions import OperationalError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.routes.auth import Principal, require_csrf, require_roles
from app.db.client import get_database

router = APIRouter(dependencies=[Depends(require_csrf)])
CAN_VALIDATE = ("owner", "administrator", "engineer")
MAX_RULES = 100


class Window(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def ordered(self):
        for value in (self.start, self.end):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Observation timestamps must include an offset or UTC timezone.")
        if self.end <= self.start:
            raise ValueError("Observation window end must follow start.")
        return self


class SensorMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exit_count_sensor_id: str = Field(min_length=1, max_length=128)


class DataQualityRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    counter_mode: Literal["cumulative", "incremental"] = "cumulative"
    expected_interval_seconds: float | None = Field(default=None, gt=0, le=86_400)
    max_missing_gap_seconds: float = Field(default=300, gt=0, le=86_400)
    minimum_samples: int = Field(default=2, ge=1, le=100_000)
    duplicate_tolerance_seconds: float = Field(default=1, ge=0, le=3600)


class ValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    simulation_run_id: str = Field(min_length=1, max_length=128)
    calibration_window: Window
    observation_window: Window
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    feed_conditions: dict[str, Any] = Field(default_factory=dict, max_length=MAX_RULES)
    sensor_mapping: SensorMapping
    data_quality_rules: DataQualityRules = Field(default_factory=DataQualityRules)
    idempotency_key: str | None = Field(max_length=128, default=None)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        if value == "UTC":
            return value
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Timezone must be a valid IANA timezone or UTC.") from error
        return value

    @model_validator(mode="after")
    def windows_do_not_overlap(self):
        a, b = self.calibration_window, self.observation_window
        if a.start < b.end and b.start < a.end:
            raise ValueError("Calibration and observation windows must be independent and non-overlapping.")
        return self


def _object_id(value: str, label: str) -> ObjectId:
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


def _scoped_validation(validation_id: str, organization_id: ObjectId) -> dict[str, Any]:
    record = get_database().twin_validations.find_one(
        {"organization_id": organization_id, "validation_id": validation_id}
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Twin validation not found.")
    return record


def _live_sensor(database, sensor_id: str, organization_id: ObjectId) -> dict[str, Any] | None:
    if not ObjectId.is_valid(sensor_id):
        return None
    return database.sensors.find_one({
        "_id": ObjectId(sensor_id),
        "organization_id": organization_id,
        "archived_at": None,
    })


@router.post("/lines/{line_id}/versions/{version}/validations")
def create_twin_validation(
    line_id: str,
    version: int,
    payload: ValidationRequest,
    principal: Principal = Depends(require_roles(*CAN_VALIDATE)),
) -> dict[str, Any]:
    database = get_database()
    line_oid = _object_id(line_id, "Production line")
    line = database.production_lines.find_one({
        "_id": line_oid,
        "organization_id": principal.organization_id,
        "archived_at": None,
    })
    if line is None:
        raise HTTPException(status_code=404, detail="Production line not found.")
    line_version = database.production_line_versions.find_one({
        "organization_id": principal.organization_id,
        "line_id": line_oid,
        "version": version,
    })
    if line_version is None:
        raise HTTPException(status_code=404, detail="Production line version not found.")
    run = database.simulation_runs.find_one({
        "organization_id": principal.organization_id,
        "run_id": payload.simulation_run_id,
        "line_id": line_oid,
        "line_version": version,
    })
    if run is None:
        raise HTTPException(status_code=404, detail="Pinned simulation run not found for this saved line version.")
    if run["status"] != "completed" or run.get("snapshot") is None or run.get("metrics") is None:
        raise HTTPException(status_code=409, detail={"code": "SIMULATION_NOT_CONNECTED", "message": "Validation requires a completed simulation run with pinned outputs."})

    if payload.idempotency_key:
        existing = database.twin_validations.find_one({
            "organization_id": principal.organization_id,
            "idempotency_key": payload.idempotency_key,
        })
        if existing is not None:
            return {"validation": _serialize(existing)}

    sensor = _live_sensor(database, payload.sensor_mapping.exit_count_sensor_id, principal.organization_id)
    if sensor is None or sensor.get("measurement_type") != "count":
        raise HTTPException(status_code=422, detail={"code": "GROUND_TRUTH_SENSOR_INVALID", "message": "The exit count sensor must be an active count sensor in this organization."})

    now = datetime.now(UTC)
    validation_id = uuid4().hex
    record = {
        "validation_id": validation_id,
        "organization_id": principal.organization_id,
        "line_id": line_oid,
        "line_version": version,
        "simulation_run_id": payload.simulation_run_id,
        "created_by": principal.user_id,
        "created_at": now,
        "updated_at": now,
        "status": "queued",
        "attempt_count": 0,
        "pinned": {
            "simulation_snapshot": run["snapshot"],
            "simulation_snapshot_hash": run.get("snapshot_hash"),
            "simulation_metrics": run["metrics"],
            "recipe_id": run["snapshot"].get("recipe_id"),
            "product_id": run["snapshot"].get("product_id"),
            "line_version_snapshot": line_version["model"],
            "sensor_mapping": payload.sensor_mapping.model_dump(),
            "timezone": payload.timezone,
            "calibration_window": payload.calibration_window.model_dump(mode="json"),
            "observation_window": payload.observation_window.model_dump(mode="json"),
            "feed_conditions": payload.feed_conditions,
            "data_quality_rules": payload.data_quality_rules.model_dump(),
        },
        "metrics": None,
        "operating_envelope": None,
        "evidence": None,
        "error": None,
    }
    if payload.idempotency_key:
        record["idempotency_key"] = payload.idempotency_key
    database.twin_validations.insert_one(record)
    from app.worker.twin_validations import execute_twin_validation
    try:
        execute_twin_validation.delay(validation_id)
    except OperationalError as error:
        database.twin_validations.update_one(
            {"_id": record["_id"], "status": "queued"},
            {"$set": {
                "status": "failed",
                "error": {"code": "queue_unavailable", "message": "The background worker could not be reached. Create the validation again."},
                "updated_at": datetime.now(UTC),
            }},
        )
        raise HTTPException(status_code=503, detail="The background worker is unavailable. The validation was recorded as failed.") from error
    return {"validation": _serialize(record)}


@router.get("/lines/{line_id}/versions/{version}/validations")
def list_twin_validations(
    line_id: str,
    version: int,
    principal: Principal = Depends(require_roles(*CAN_VALIDATE)),
) -> dict[str, Any]:
    line_oid = _object_id(line_id, "Production line")
    records = list(get_database().twin_validations.find({
        "organization_id": principal.organization_id,
        "line_id": line_oid,
        "line_version": version,
    }).sort("created_at", -1).limit(50))
    return {"validations": [_serialize(record) for record in records]}


@router.get("/twin-validations/{validation_id}")
def get_twin_validation(
    validation_id: str,
    principal: Principal = Depends(require_roles(*CAN_VALIDATE)),
) -> dict[str, Any]:
    return {"validation": _serialize(_scoped_validation(validation_id, principal.organization_id))}


def evaluate_validation(database, record: dict[str, Any]) -> dict[str, Any]:
    pinned = record["pinned"]
    sensor_id = pinned["sensor_mapping"]["exit_count_sensor_id"]
    try:
        raw_start = pinned["observation_window"]["start"]
        raw_end = pinned["observation_window"]["end"]
        start = raw_start if isinstance(raw_start, datetime) else datetime.fromisoformat(str(raw_start).replace("Z", "+00:00"))
        end = raw_end if isinstance(raw_end, datetime) else datetime.fromisoformat(str(raw_end).replace("Z", "+00:00"))
    except (KeyError, AttributeError, ValueError):
        return {
            "status": "insufficient_evidence",
            "metrics": {},
            "operating_envelope": pinned["feed_conditions"],
            "evidence": [{"code": "INVALID_OBSERVATION_WINDOW", "message": "The pinned observation window is missing or invalid.", "source": "measured"}],
        }

    readings = list(database.sensor_readings.find({
        "organization_id": record["organization_id"],
        "sensor_id": ObjectId(sensor_id),
        "event_time_utc": {"$gte": start, "$lt": end},
        "quality": {"$ne": "bad"},
    }).sort("event_time_utc", 1).limit(100_000))

    rules = pinned["data_quality_rules"]
    duplicates = 0
    missing_intervals = 0
    resets = 0
    unit_mismatches = 0
    usable: list[dict[str, Any]] = []
    previous_time = None
    previous_value = None
    duplicate_seconds = rules["duplicate_tolerance_seconds"]
    max_gap = rules["max_missing_gap_seconds"]

    for reading in readings:
        if reading.get("unit") != "count":
            unit_mismatches += 1
            continue
        value = reading.get("value")
        event_time = reading.get("event_time_utc")
        if not isinstance(value, (int, float)):
            continue
        if previous_time is not None and event_time == previous_time:
            duplicates += 1
            continue
        if previous_time is not None and previous_value is not None:
            gap = (event_time - previous_time).total_seconds()
            if gap > max_gap:
                missing_intervals += 1
            if previous_value < 0 or value < previous_value and rules["counter_mode"] == "cumulative":
                resets += 1
        usable.append(reading)
        previous_time = event_time
        previous_value = value

    minimum_samples = rules["minimum_samples"]
    if len(usable) < minimum_samples:
        status = "insufficient_evidence"
        reasons = [{
            "code": "INSUFFICIENT_GROUND_TRUTH",
            "message": f"Found {len(usable)} usable ground-truth readings; at least {minimum_samples} are required.",
            "source": "measured",
        }]
    else:
        status = "validated"
        reasons = []

    if rules["counter_mode"] == "cumulative":
        observed_total = max(
            (float(item["value"]) for item in usable),
            default=0.0,
        ) - min((float(item["value"]) for item in usable), default=0.0)
        if resets:
            observed_total = sum(
                max(0.0, float(item["value"]) - float(usable[index - 1]["value"]))
                for index, item in enumerate(usable)
                if index > 0
            )
    else:
        observed_total = sum(float(item["value"]) for item in usable)

    simulation_metrics = pinned["simulation_metrics"]
    simulated_total = sum(float(value) for value in simulation_metrics.get("cycle_completions", {}).values())
    signed_bias = simulated_total - observed_total
    absolute_error = abs(signed_bias)
    coverage = len(usable) / max(len(readings), 1)

    metrics = {
        "conveyor_exit_count": {
            "status": status if unit_mismatches == 0 and duplicates == 0 and missing_intervals == 0 else "connected_with_warnings",
            "sample_size": len(usable),
            "coverage": coverage,
            "observed_total": observed_total,
            "simulated_total": simulated_total,
            "signed_bias": signed_bias,
            "absolute_error": absolute_error,
            "unit": "count",
            "sources": {"observed": "measured", "simulated": "simulated"},
            "signed_bias_definition": "simulated_total - observed_total",
        }
    }
    return {
        "status": "insufficient_evidence" if len(usable) < minimum_samples else "completed",
        "metrics": metrics,
        "operating_envelope": pinned["feed_conditions"],
        "evidence": reasons + [{
            "code": "DATA_QUALITY_SUMMARY",
            "message": f"counter resets={resets}; missing intervals={missing_intervals}; duplicate events={duplicates}; unit mismatches={unit_mismatches}",
            "source": "measured",
        }],
    }
