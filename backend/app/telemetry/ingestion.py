import math
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from bson import ObjectId
from bson.errors import InvalidId
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, field_validator

from app.core.config import get_settings
from app.telemetry.devices import sensor_quantity, update_sensor_receipt
from app.telemetry.readings import (
    NormalizedReadingV1,
    canonicalize_value,
    make_event_key,
    parse_event_time,
)
from app.telemetry.repository import bulk_upsert_readings


class DeviceReading(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sensor_id: str = Field(min_length=1, max_length=64)
    value: StrictFloat | StrictInt
    unit: str = Field(min_length=1, max_length=32)
    event_time_utc: str = Field(min_length=1, max_length=64)
    sequence: int | None = Field(default=None, ge=0, le=9_223_372_036_854_775_807)
    source_event_id: str | None = Field(default=None, max_length=128)
    quality: Literal["good", "uncertain", "bad"] | None = None

    @field_validator("value")
    @classmethod
    def finite_numeric_value(cls, value: float | int) -> float:
        if not math.isfinite(float(value)):
            raise ValueError("NON_FINITE_VALUE: Reading value must be finite.")
        return float(value)

    @field_validator("source_event_id", mode="before")
    @classmethod
    def normalize_empty_event_id(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value


def _rejection(index: int, code: str, message: str) -> dict[str, Any]:
    return {"index": index, "status": "rejected", "code": code, "message": message}


def ingest_readings(
    *,
    database,
    credential: dict[str, Any],
    items: list[DeviceReading],
    source: Literal["rest", "mqtt", "opcua"],
    received_at: datetime | None = None,
) -> list[dict[str, Any]]:
    received_at_utc = (received_at or datetime.now(UTC)).astimezone(UTC)
    settings = get_settings()
    permissions = {
        permission["sensor_id"]: permission.get("quantities")
        for permission in credential["sensor_permissions"]
    }
    responses: list[dict[str, Any] | None] = [None] * len(items)
    readings: list[dict[str, Any]] = []
    reading_indexes: dict[str, list[int]] = {}
    sensors_by_id: dict[ObjectId, dict[str, Any]] = {}

    for index, item in enumerate(items):
        try:
            sensor_object_id = ObjectId(item.sensor_id)
        except InvalidId:
            responses[index] = _rejection(index, "UNKNOWN_SENSOR", "No registered sensor has this ID.")
            continue
        allowed_quantities = permissions.get(sensor_object_id)
        if sensor_object_id not in permissions:
            responses[index] = _rejection(
                index,
                "SENSOR_NOT_PERMITTED",
                "This device credential is not permitted to write to the sensor.",
            )
            continue
        sensor = database.sensors.find_one(
            {
                "_id": sensor_object_id,
                "organization_id": credential["organization_id"],
                "archived_at": None,
            }
        )
        if sensor is None:
            responses[index] = _rejection(
                index,
                "SENSOR_NOT_PERMITTED",
                "The sensor is not active in this organization.",
            )
            continue
        try:
            event_time = parse_event_time(item.event_time_utc, None)
            if event_time > received_at_utc + timedelta(
                seconds=settings.device_future_tolerance_seconds
            ):
                responses[index] = _rejection(
                    index,
                    "FUTURE_TIMESTAMP",
                    "Device event time exceeds the configured future-time tolerance.",
                )
                continue
            quantity, unit, value = canonicalize_value(
                sensor["measurement_type"],
                item.unit,
                item.value,
                registered_unit=sensor["unit"],
                calibration_scale=sensor.get("calibration", {}).get("scale"),
                calibration_offset=sensor.get("calibration", {}).get("offset"),
            )
        except ValueError as error:
            reason = str(error)
            responses[index] = _rejection(
                index,
                reason.split(":", 1)[0] if ":" in reason else "BAD_TIMESTAMP",
                reason,
            )
            continue
        if allowed_quantities is not None and quantity not in allowed_quantities:
            responses[index] = _rejection(
                index,
                "QUANTITY_NOT_PERMITTED",
                "This credential is not permitted to send this measurement quantity.",
            )
            continue
        if quantity != sensor_quantity(sensor):
            responses[index] = _rejection(
                index,
                "INCOMPATIBLE_UNIT",
                "Input unit does not match the sensor's registered measurement quantity.",
            )
            continue
        machine = database.machines.find_one(
            {
                "_id": sensor["machine_id"],
                "organization_id": credential["organization_id"],
                "archived_at": None,
            }
        )
        if machine is None:
            responses[index] = _rejection(
                index,
                "SENSOR_NOT_PERMITTED",
                "The sensor's machine is archived or unavailable.",
            )
            continue
        event_key = make_event_key(
            str(credential["organization_id"]),
            str(sensor_object_id),
            quantity,
            event_time,
            source_event_id=item.source_event_id,
            sequence=item.sequence,
        )
        normalized = NormalizedReadingV1(
            organization_id=str(credential["organization_id"]),
            sensor_id=str(sensor_object_id),
            machine_id=str(machine["_id"]),
            quantity=quantity,
            unit=unit,
            value=value,
            event_time_utc=event_time,
            received_at_utc=received_at_utc,
            source=source,
            source_ref=credential["key_id"],
            quality=item.quality,
            event_key=event_key,
        )
        document = normalized.model_dump(mode="python")
        document["organization_id"] = credential["organization_id"]
        document["sensor_id"] = sensor_object_id
        document["machine_id"] = machine["_id"]
        readings.append(document)
        reading_indexes.setdefault(event_key, []).append(index)
        sensors_by_id[sensor_object_id] = sensor

    duplicate_in_batch: set[str] = set()
    first_index: dict[str, int] = {}
    unique_readings: list[dict[str, Any]] = []
    for reading in readings:
        key = reading["event_key"]
        index = reading_indexes[key].pop(0)
        if key in first_index:
            duplicate_in_batch.add(key)
            responses[index] = {
                "index": index,
                "status": "duplicate",
                "code": "DUPLICATE_IN_BATCH",
            }
        else:
            first_index[key] = index
            unique_readings.append(reading)

    statuses = bulk_upsert_readings(database, unique_readings)
    for reading in unique_readings:
        key = reading["event_key"]
        index = first_index[key]
        status = statuses[key]
        _is_accepted = status == "inserted"
        _response: dict[str, Any] = {
            "index": index,
            "status": "accepted" if _is_accepted else "duplicate",
            "code": "ACCEPTED" if _is_accepted else "DUPLICATE_EXISTING",
        }
        if _is_accepted:
            _response["_live"] = {
                "organization_id": str(reading["organization_id"]),
                "sensor_id": str(reading["sensor_id"]),
                "machine_id": str(reading["machine_id"]),
                "quantity": reading["quantity"],
                "unit": reading["unit"],
                "value": reading["value"],
                "event_time_utc": reading["event_time_utc"].isoformat()
                    if hasattr(reading["event_time_utc"], "isoformat")
                    else str(reading["event_time_utc"]),
                "received_at_utc": reading["received_at_utc"].isoformat()
                    if hasattr(reading["received_at_utc"], "isoformat")
                    else str(reading["received_at_utc"]),
                "source": reading["source"],
            }
        responses[index] = _response
        for item_index in reading_indexes.get(key, []):
            responses[item_index] = {
                "index": item_index,
                "status": "duplicate",
                "code": "DUPLICATE_IN_BATCH",
            }
        if status in {"inserted", "duplicate"}:
            update_sensor_receipt(
                database,
                organization_id=credential["organization_id"],
                sensor=sensors_by_id[reading["sensor_id"]],
                event_time_utc=reading["event_time_utc"],
                received_at_utc=received_at_utc,
            )

    return [response for response in responses if response is not None]
