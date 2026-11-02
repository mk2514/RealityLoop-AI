from datetime import UTC, datetime, timedelta
from math import floor, ceil
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.routes.auth import Principal, get_current_principal, require_csrf, require_roles
from app.core.config import get_settings
from app.db.client import get_database
from app.telemetry.devices import sensor_state_payload, sensor_quantity
from app.telemetry.readings import as_utc, UNIT_CONVERSIONS

router = APIRouter(dependencies=[Depends(require_csrf)])
CAN_EDIT = ("owner", "administrator", "engineer")


class LayoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    scope_key: str = Field(min_length=1, max_length=128)
    panels: list[dict[str, Any]] = Field(max_length=50)

    @field_validator("panels")
    @classmethod
    def validate_panels(cls, panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for panel in panels:
            if set(("sensor_id", "view_mode")).isdisjoint(panel):
                raise ValueError("Each panel requires sensor_id and view_mode.")
            if panel.get("view_mode") not in {"raw", "aggregated"}:
                raise ValueError("view_mode must be raw or aggregated.")
        return panels


class ThresholdRuleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sensor_id: str = Field(min_length=1, max_length=128)
    quantity: str = Field(min_length=1, max_length=128)
    operator: Literal["gt", "gte", "lt", "lte", "eq"]
    value: float
    duration_seconds: int = Field(default=0, ge=0, le=31_536_000)
    severity: Literal["info", "warning", "critical"] = "warning"


class StationSensorMappingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_id: str = Field(min_length=1, max_length=128)
    line_version: int = Field(ge=1)
    station_id: str = Field(min_length=1, max_length=128)
    sensor_id: str = Field(min_length=1, max_length=128)
    quantity: str = Field(min_length=1, max_length=128)
    unit: str = Field(min_length=1, max_length=32)
    time_basis: Literal["event_time_utc"] = "event_time_utc"


def _object_id(value: str, label: str = "Sensor") -> ObjectId:
    try:
        return ObjectId(value)
    except InvalidId as error:
        raise HTTPException(status_code=404, detail=f"{label} was not found.") from error


def _sensor(sensor_id: str, organization_id: ObjectId) -> dict[str, Any]:
    sensor = get_database().sensors.find_one(
        {"_id": _object_id(sensor_id), "organization_id": organization_id, "archived_at": None}
    )
    if sensor is None:
        raise HTTPException(status_code=404, detail="Sensor was not found in this workspace.")
    return sensor


def _convert_for_display(value: float, measurement_type: str, source_unit: str, display_unit: str) -> float:
    if source_unit == display_unit:
        return value
    if measurement_type == "custom":
        if source_unit != display_unit:
            raise ValueError("Custom units cannot be converted.")
        return value
    quantity_options = {
        key: details
        for key, details in UNIT_CONVERSIONS.items()
        if key[0] == measurement_type
    }
    source = quantity_options.get((measurement_type, source_unit))
    target = quantity_options.get((measurement_type, display_unit))
    if source is None or target is None or source[:2] != target[:2]:
        raise ValueError(
            f"Display unit {display_unit!r} is not compatible with canonical unit {source_unit!r}."
        )
    canonical = value * source[2] + source[3]
    return (canonical - target[3]) / target[2]


def aggregate_samples(
    samples: list[tuple[datetime, float]],
    start_utc: datetime,
    bucket_seconds: int,
) -> list[dict[str, Any]]:
    buckets_count = max(1, ceil((samples[-1][0] - start_utc).total_seconds() / bucket_seconds) + 1) if samples else 1
    bucket_values: dict[int, list[float]] = {}
    for event_time, value in samples:
        index = floor((event_time - start_utc).total_seconds() / bucket_seconds)
        bucket_values.setdefault(index, []).append(value)
    buckets: list[dict[str, Any]] = []
    for index in range(buckets_count):
        values = bucket_values.get(index)
        bucket_start = start_utc + timedelta(seconds=index * bucket_seconds)
        buckets.append({
            "bucket_start_utc": bucket_start.isoformat(),
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "avg": sum(values) / len(values) if values else None,
            "count": len(values) if values else 0,
            "first": values[0] if values else None,
            "last": values[-1] if values else None,
            "kind": "observed",
        })
    return buckets


def _serialize(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {("id" if key == "_id" else key): _serialize(item) for key, item in value.items()}
    return value


@router.get("/dashboard/hierarchy")
def hierarchy(principal: Principal = Depends(get_current_principal)) -> dict[str, Any]:
    database = get_database()
    factories = list(database.factories.find(
        {"organization_id": principal.organization_id, "archived_at": None}
    ).sort("created_at", 1))
    nodes: list[dict[str, Any]] = []
    for factory in factories:
        lines = list(database.production_lines.find({
            "organization_id": principal.organization_id,
            "factory_id": factory["_id"],
            "archived_at": None,
        }).sort("created_at", 1))
        line_nodes: list[dict[str, Any]] = []
        for line in lines:
            machines = list(database.machines.find({
                "organization_id": principal.organization_id,
                "line_id": line["_id"],
                "archived_at": None,
            }).sort("created_at", 1))
            machine_nodes = []
            for machine in machines:
                components = list(database.components.find({
                    "organization_id": principal.organization_id,
                    "machine_id": machine["_id"],
                    "archived_at": None,
                }).sort("created_at", 1))
                component_nodes = []
                for component in components:
                    sensors = list(database.sensors.find({
                        "organization_id": principal.organization_id,
                        "component_id": component["_id"],
                        "archived_at": None,
                    }).sort("created_at", 1))
                    component_nodes.append({
                        "id": str(component["_id"]),
                        "name": component["name"],
                        "kind": "component",
                        "sensors": [{"id": str(sensor["_id"]), "name": sensor["name"], "kind": "sensor"} for sensor in sensors],
                    })
                machine_nodes.append({
                    "id": str(machine["_id"]),
                    "name": machine["name"],
                    "kind": "machine",
                    "components": component_nodes,
                })
            line_nodes.append({"id": str(line["_id"]), "name": line["name"], "kind": "line", "machines": machine_nodes})
        nodes.append({"id": str(factory["_id"]), "name": factory["name"], "kind": "factory", "lines": line_nodes})
    return {"kind": "observed", "hierarchy": nodes}


@router.get("/sensors/{sensor_id}/readings")
def get_readings(
    sensor_id: str,
    start: datetime = Query(...),
    end: datetime = Query(...),
    view: Literal["raw", "aggregated"] = Query("aggregated"),
    timezone_name: str = Query("UTC", alias="timezone"),
    display_unit: str | None = Query(default=None),
    bucket_seconds: int | None = Query(default=None, ge=1, le=31_536_000),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    sensor = _sensor(sensor_id, principal.organization_id)
    settings = get_settings()
    start_utc = as_utc(start)
    end_utc = as_utc(end)
    if end_utc <= start_utc:
        raise HTTPException(status_code=422, detail="end must be later than start.")
    if (end_utc - start_utc).total_seconds() > settings.dashboard_max_range_seconds:
        raise HTTPException(
            status_code=422,
            detail=f"Window exceeds the configured {settings.dashboard_max_range_seconds}-second maximum.",
        )
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise HTTPException(status_code=422, detail="Choose a valid IANA timezone.") from error

    target_unit = display_unit or sensor["unit"]
    query = {
        "organization_id": principal.organization_id,
        "sensor_id": sensor["_id"],
        "event_time_utc": {"$gte": start_utc, "$lte": end_utc},
    }
    cursor = get_database().sensor_readings.find(query).sort("event_time_utc", 1)
    records = list(cursor)
    if view == "raw" and len(records) > settings.dashboard_raw_max_rows:
        raise HTTPException(
            status_code=413,
            detail=f"Raw view exceeds the {settings.dashboard_raw_max_rows}-row cap. Use the aggregated view.",
        )
    window_seconds = (end_utc - start_utc).total_seconds()
    if bucket_seconds is None:
        bucket_seconds = max(1, ceil(window_seconds / settings.dashboard_max_buckets))
    bucket_seconds = min(bucket_seconds, settings.dashboard_max_buckets * 3600)
    bucket_count = max(1, ceil(window_seconds / bucket_seconds))
    if bucket_count > settings.dashboard_max_buckets:
        raise HTTPException(
            status_code=422,
            detail=f"Bucket count exceeds the configured {settings.dashboard_max_buckets}-bucket cap.",
        )

    buckets: list[dict[str, Any]] = []
    converted: list[dict[str, Any]] = []
    for record in records:
        try:
            value = _convert_for_display(
                float(record["value"]), sensor["measurement_type"], record["unit"], target_unit
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        converted.append({**record, "display_value": value, "event_time": as_utc(record["event_time_utc"])})

    if view == "raw":
        samples = [
            {
                "event_time_utc": record["event_time"].isoformat(),
                "value": record["display_value"],
                "quality": record.get("quality"),
                "source": record["source"],
                "source_ref": record["source_ref"],
                "received_at_utc": record["received_at_utc"].isoformat() if isinstance(record["received_at_utc"], datetime) else as_utc(record["received_at_utc"]).isoformat(),
                "event_key": record["event_key"],
                "kind": "observed",
            }
            for record in converted
        ]
    else:
        bucket_values: dict[int, list[float]] = {}
        for record in converted:
            index = floor((record["event_time"] - start_utc).total_seconds() / bucket_seconds)
            bucket_values.setdefault(index, []).append(record["display_value"])
        for index in range(bucket_count):
            values = bucket_values.get(index)
            bucket_start = start_utc + timedelta(seconds=index * bucket_seconds)
            buckets.append({
                "bucket_start_utc": bucket_start.isoformat(),
                "min": min(values) if values else None,
                "max": max(values) if values else None,
                "avg": sum(values) / len(values) if values else None,
                "count": len(values) if values else 0,
                "first": values[0] if values else None,
                "last": values[-1] if values else None,
                "kind": "observed",
            })
        samples = buckets

    return {
        "kind": "observed",
        "sensor_id": sensor_id,
        "quantity": sensor.get("measurement_type"),
        "unit": target_unit,
        "timezone": timezone_name,
        "window": {"start": start_utc.isoformat(), "end": end_utc.isoformat()},
        "view": view,
        "bucket_size_seconds": bucket_seconds if view == "aggregated" else None,
        "row_count": len(records),
        "bucket_count": len(buckets),
        "quality_summary": {
            "good": sum(record.get("quality") == "good" for record in records),
            "uncertain": sum(record.get("quality") == "uncertain" for record in records),
            "bad": sum(record.get("quality") == "bad" for record in records),
            "missing_quality": sum(record.get("quality") is None for record in records),
        },
        "freshness": sensor_state_payload(get_database(), organization_id=principal.organization_id, sensor=sensor),
        "samples": samples,
    }


@router.get("/sensors/{sensor_id}/readings/{event_key}/provenance")
def get_provenance(
    sensor_id: str,
    event_key: str,
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    sensor = _sensor(sensor_id, principal.organization_id)
    record = get_database().sensor_readings.find_one({
        "organization_id": principal.organization_id,
        "sensor_id": sensor["_id"],
        "event_key": event_key,
    })
    if record is None:
        raise HTTPException(status_code=404, detail="Reading provenance was not found.")
    return {"kind": "observed", "source": {
        "source": record["source"],
        "source_ref": record["source_ref"],
        "event_time_utc": as_utc(record["event_time_utc"]).isoformat(),
        "received_at_utc": as_utc(record["received_at_utc"]).isoformat(),
        "event_key": record["event_key"],
        "quality": record.get("quality"),
    }}


@router.get("/sensors/{sensor_id}/readings-export")
def export_readings(
    sensor_id: str,
    start: datetime = Query(...),
    end: datetime = Query(...),
    view: Literal["raw", "aggregated"] = Query("aggregated"),
    timezone_name: str = Query("UTC", alias="timezone"),
    display_unit: str | None = Query(default=None),
    bucket_seconds: int | None = Query(default=None, ge=1, le=31_536_000),
    principal: Principal = Depends(get_current_principal),
) -> Response:
    data = get_readings(
        sensor_id=sensor_id,
        start=start,
        end=end,
        view=view,
        timezone_name=timezone_name,
        display_unit=display_unit,
        bucket_seconds=bucket_seconds,
        principal=principal,
    )
    count = len(data["samples"])
    if count > get_settings().dashboard_export_max_rows:
        raise HTTPException(
            status_code=413,
            detail=f"Export exceeds the {get_settings().dashboard_export_max_rows}-row cap.",
        )
    lines = [
        "# kind=observed",
        f"# window_start={data['window']['start']}",
        f"# window_end={data['window']['end']}",
        f"# timezone={data['timezone']}",
        f"# unit={data['unit']}",
        f"# view={data['view']}",
        f"# bucket_size_seconds={data['bucket_size_seconds'] or ''}",
        f"# generated_at={datetime.now(UTC).isoformat()}",
        "# row_count=" + str(data["row_count"]),
        "bucket_start_utc,value,min,max,avg,count,first,last,event_time_utc,quality,source,source_ref,event_key",
    ]
    for sample in data["samples"]:
        if view == "aggregated":
            lines.append(",".join([
                sample["bucket_start_utc"],
                "", str(sample["min"] if sample["min"] is not None else ""), str(sample["max"] if sample["max"] is not None else ""),
                str(sample["avg"] if sample["avg"] is not None else ""), str(sample["count"]), str(sample["first"] if sample["first"] is not None else ""),
                str(sample["last"] if sample["last"] is not None else ""), "", "", "", "", "",
            ]))
        else:
            lines.append(",".join([
                "", str(sample["value"]), "", "", "", "", "", "", sample["event_time_utc"],
                sample["quality"] or "", sample["source"], sample["source_ref"], sample["event_key"],
            ]))
    return Response(
        content="\n".join(lines) + "\n",
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="sensor-{sensor_id}-{view}.csv"'},
    )


@router.get("/dashboard/layouts/{scope_key}")
def get_layout(
    scope_key: str,
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    layout = get_database().dashboard_layouts.find_one({
        "organization_id": principal.organization_id,
        "user_id": principal.user_id,
        "scope_key": scope_key,
    })
    if layout is None:
        return {"layout": {"schema_version": 1, "scope_key": scope_key, "panels": []}}
    return {"layout": _serialize(layout)}


@router.put("/dashboard/layouts/{scope_key}")
def save_layout(
    scope_key: str,
    payload: LayoutRequest,
    principal: Principal = Depends(require_roles(*CAN_EDIT)),
) -> dict[str, Any]:
    if payload.scope_key != scope_key:
        raise HTTPException(status_code=422, detail="Layout scope_key must match the route.")
    now = datetime.now(UTC)
    result = get_database().dashboard_layouts.find_one_and_update(
        {"organization_id": principal.organization_id, "user_id": principal.user_id, "scope_key": scope_key},
        {"$set": {
            "schema_version": payload.schema_version,
            "panels": payload.panels,
            "updated_at": now,
        }, "$setOnInsert": {
            "organization_id": principal.organization_id,
            "user_id": principal.user_id,
            "scope_key": scope_key,
            "created_at": now,
        }},
        upsert=True,
        return_document=True,
    )
    return {"layout": _serialize(result)}


@router.post("/dashboard/threshold-rules", status_code=201)
def create_threshold_rule(
    payload: ThresholdRuleRequest,
    principal: Principal = Depends(require_roles(*CAN_EDIT)),
) -> dict[str, Any]:
    sensor = _sensor(payload.sensor_id, principal.organization_id)
    quantity = sensor_quantity(sensor)
    if payload.quantity != quantity:
        raise HTTPException(
            status_code=422,
            detail=f"Rule quantity {payload.quantity!r} does not match sensor quantity {quantity!r}.",
        )
    database = get_database()
    current = list(database.dashboard_threshold_rules.find({
        "organization_id": principal.organization_id,
        "sensor_id": sensor["_id"],
        "quantity": quantity,
    }).sort("version", -1).limit(1))
    version = int(current[0]["version"]) + 1 if current else 1
    now = datetime.now(UTC)
    record = {
        "organization_id": principal.organization_id,
        "created_by": principal.user_id,
        "sensor_id": sensor["_id"],
        "quantity": quantity,
        "operator": payload.operator,
        "value": payload.value,
        "duration_seconds": payload.duration_seconds,
        "severity": payload.severity,
        "version": version,
        "status": "active",
        "created_at": now,
        "schema_version": 1,
    }
    rule_id = str(ObjectId())
    record["rule_id"] = rule_id
    database.dashboard_threshold_rules.insert_one(record)
    return {"rule": _serialize(record)}


@router.get("/dashboard/threshold-rules")
def list_threshold_rules(
    sensor_id: str | None = Query(default=None),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    query: dict[str, Any] = {"organization_id": principal.organization_id}
    if sensor_id:
        query["sensor_id"] = _object_id(sensor_id)
    rules = list(get_database().dashboard_threshold_rules.find(query).sort("created_at", -1).limit(500))
    return {"rules": [_serialize(rule) for rule in rules]}


@router.post("/dashboard/station-sensor-mappings", status_code=201)
def save_station_sensor_mapping(
    payload: StationSensorMappingRequest,
    principal: Principal = Depends(require_roles(*CAN_EDIT)),
) -> dict[str, Any]:
    database = get_database()
    line_id = _object_id(payload.line_id, "Production line")
    sensor = _sensor(payload.sensor_id, principal.organization_id)
    line = database.production_lines.find_one({
        "_id": line_id,
        "organization_id": principal.organization_id,
        "archived_at": None,
    })
    if line is None:
        raise HTTPException(status_code=404, detail="Production line was not found in this workspace.")
    version = database.production_line_versions.find_one({
        "organization_id": principal.organization_id,
        "line_id": line_id,
        "version": payload.line_version,
    })
    if version is None:
        raise HTTPException(status_code=404, detail="Production line version was not found.")
    station_ids = {
        node["id"]
        for node in version["model"].get("layout", {}).get("nodes", [])
        if node.get("id")
    }
    if payload.station_id not in station_ids:
        raise HTTPException(
            status_code=422,
            detail=f"Station {payload.station_id!r} is not present in pinned line version {payload.line_version}.",
        )
    quantity = sensor_quantity(sensor)
    if payload.quantity != quantity:
        raise HTTPException(
            status_code=422,
            detail=f"Mapping quantity {payload.quantity!r} does not match observed sensor quantity {quantity!r}.",
        )
    now = datetime.now(UTC)
    result = database.dashboard_station_sensor_mappings.find_one_and_update(
        {
            "organization_id": principal.organization_id,
            "line_id": line_id,
            "line_version": payload.line_version,
            "station_id": payload.station_id,
        },
        {"$set": {
            "sensor_id": sensor["_id"],
            "quantity": quantity,
            "unit": payload.unit,
            "time_basis": payload.time_basis,
            "updated_at": now,
        }, "$setOnInsert": {
            "organization_id": principal.organization_id,
            "line_id": line_id,
            "line_version": payload.line_version,
            "station_id": payload.station_id,
            "created_at": now,
        }},
        upsert=True,
        return_document=True,
    )
    return {"mapping": _serialize(result)}


@router.get("/dashboard/simulation-overlay")
def check_simulation_overlay(
    run_id: str = Query(..., min_length=1, max_length=128),
    sensor_id: str = Query(..., min_length=1, max_length=128),
    display_unit: str = Query(..., min_length=1, max_length=32),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    database = get_database()
    sensor = _sensor(sensor_id, principal.organization_id)
    run = database.simulation_runs.find_one({
        "organization_id": principal.organization_id,
        "run_id": run_id,
    })
    if run is None:
        raise HTTPException(status_code=404, detail="Simulation run was not found in this workspace.")
    mapping = database.dashboard_station_sensor_mappings.find_one({
        "organization_id": principal.organization_id,
        "line_id": run["line_id"],
        "line_version": run["line_version"],
        "sensor_id": sensor["_id"],
    })
    if mapping is None:
        return {
            "allowed": False,
            "reason": "No pinned station-to-sensor mapping exists for this run and sensor.",
            "kind": "simulated",
        }
    try:
        _convert_for_display(
            1.0,
            sensor["measurement_type"],
            sensor["unit"],
            display_unit,
        )
        _convert_for_display(
            1.0,
            sensor["measurement_type"],
            sensor["unit"],
            mapping["unit"],
        )
    except ValueError as error:
        return {"allowed": False, "reason": str(error), "kind": "simulated"}
    if mapping["time_basis"] != "event_time_utc":
        return {
            "allowed": False,
            "reason": "The simulation overlay time basis differs from observed UTC event time.",
            "kind": "simulated",
        }
    return {
        "allowed": True,
        "reason": None,
        "kind": "simulated",
        "run_id": run_id,
        "line_version": run["line_version"],
        "station_id": mapping["station_id"],
        "time_basis": "event_time_utc",
        "unit": display_unit,
    }
