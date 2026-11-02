import json
import logging
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api.routes.auth import (
    Principal,
    get_current_principal,
    require_csrf,
    require_roles,
)
from app.api.routes.device_credentials import get_device_credential
from app.core.config import get_settings
from app.db.client import get_database
from app.telemetry.devices import audit_device_event, sensor_state_payload
from app.telemetry.ingestion import DeviceReading, ingest_readings

session_router = APIRouter(dependencies=[Depends(require_csrf)])
device_router = APIRouter()
logger = logging.getLogger(__name__)
TELEMETRY_ADMIN_ROLES = ("owner", "administrator", "engineer")


class ReadingBatchEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    readings: list[Any] = Field(min_length=1)


class StaleThresholdRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stale_after_seconds: int = Field(ge=1, le=31_536_000)


def _sensor(sensor_id: str, organization_id: ObjectId) -> dict[str, Any]:
    try:
        object_id = ObjectId(sensor_id)
    except InvalidId as error:
        raise HTTPException(status_code=404, detail="Sensor was not found.") from error
    sensor = get_database().sensors.find_one(
        {
            "_id": object_id,
            "organization_id": organization_id,
            "archived_at": None,
        }
    )
    if sensor is None:
        raise HTTPException(status_code=404, detail="Sensor was not found in this workspace.")
    return sensor


@session_router.get("/sensors/{sensor_id}/telemetry-state")
def get_sensor_telemetry_state(
    sensor_id: str,
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    sensor = _sensor(sensor_id, principal.organization_id)
    return {
        "state": sensor_state_payload(
            get_database(),
            organization_id=principal.organization_id,
            sensor=sensor,
        )
    }


@session_router.put("/sensors/{sensor_id}/telemetry-state")
def set_sensor_stale_threshold(
    sensor_id: str,
    payload: StaleThresholdRequest,
    principal: Principal = Depends(require_roles(*TELEMETRY_ADMIN_ROLES)),
) -> dict[str, Any]:
    sensor = _sensor(sensor_id, principal.organization_id)
    now = datetime.now(UTC)
    state = get_database().sensor_states.find_one_and_update(
        {"organization_id": principal.organization_id, "sensor_id": sensor["_id"]},
        {
            "$setOnInsert": {
                "organization_id": principal.organization_id,
                "sensor_id": sensor["_id"],
                "created_at": now,
            },
            "$set": {
                "stale_after_seconds": payload.stale_after_seconds,
                "updated_at": now,
            },
        },
        upsert=True,
        return_document=True,
    )
    audit_device_event(
        get_database(),
        organization_id=principal.organization_id,
        event="sensor_stale_threshold_changed",
        credential_id=None,
        actor_user_id=principal.user_id,
        created_at=now,
        counts={"stale_after_seconds": payload.stale_after_seconds},
    )
    return {
        "state": sensor_state_payload(
            get_database(),
            organization_id=principal.organization_id,
            sensor=sensor,
            now=now,
        )
    }


async def _read_limited_json(request: Request) -> Any:
    settings = get_settings()
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(status_code=415, detail="Send a JSON readings batch.")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > settings.device_batch_max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Batch exceeds the {settings.device_batch_max_bytes}-byte limit.",
                )
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header.") from error
    chunks = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > settings.device_batch_max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Batch exceeds the {settings.device_batch_max_bytes}-byte limit.",
            )
        chunks.append(chunk)
    try:
        return json.loads(b"".join(chunks))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail="Batch body must be valid UTF-8 JSON.") from error


@device_router.post("/telemetry/readings")
async def ingest_device_batch(
    request: Request,
    credential: dict[str, Any] = Depends(get_device_credential),
) -> dict[str, Any]:
    settings = get_settings()
    body = await _read_limited_json(request)
    try:
        envelope = ReadingBatchEnvelope.model_validate(body)
    except ValidationError as error:
        raise HTTPException(
            status_code=422,
            detail="Provide an object containing a non-empty readings array.",
        ) from error
    if len(envelope.readings) > settings.device_batch_max_readings:
        raise HTTPException(
            status_code=413,
            detail=f"Batch exceeds the {settings.device_batch_max_readings}-reading limit.",
        )
    parsed: list[DeviceReading] = []
    responses: list[dict[str, Any] | None] = [None] * len(envelope.readings)
    for index, item in enumerate(envelope.readings):
        try:
            parsed.append(DeviceReading.model_validate(item))
        except ValidationError:
            parsed.append(None)
            responses[index] = {
                "index": index,
                "status": "rejected",
                "code": "INVALID_ITEM",
                "message": "Provide sensor_id, a finite numeric value, unit, and offset-aware event_time_utc.",
            }
    valid_items = [item for item in parsed if item is not None]
    valid_responses = ingest_readings(
        database=get_database(),
        credential=credential,
        items=valid_items,
        source="rest",
    )
    valid_index = 0
    for index, response in enumerate(responses):
        if response is None:
            valid_response = valid_responses[valid_index]
            valid_response["index"] = index
            responses[index] = valid_response
            valid_index += 1
    final = [response for response in responses if response is not None]
    counts = {
        "accepted": sum(item["status"] == "accepted" for item in final),
        "duplicates": sum(item["status"] == "duplicate" for item in final),
        "rejected": sum(item["status"] == "rejected" for item in final),
    }
    audit_device_event(
        get_database(),
        organization_id=credential["organization_id"],
        event="readings_ingested",
        credential_id=credential["_id"],
        actor_user_id=None,
        counts=counts,
    )
    return {"results": final, "counts": counts, "source": "measured"}
