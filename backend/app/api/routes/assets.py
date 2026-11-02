import re
from datetime import UTC, datetime, time
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pymongo.errors import DuplicateKeyError

from app.api.routes.auth import (
    Principal,
    get_current_principal,
    require_csrf,
    require_roles,
)
from app.db.client import get_database, get_mongo_client

router = APIRouter(dependencies=[Depends(require_csrf)])
CAN_EDIT_ASSETS = ("owner", "administrator", "engineer")
DAYS = {0, 1, 2, 3, 4, 5, 6}
MACHINE_TYPES = (
    "conveyor",
    "processing_station",
    "cnc_cutting",
    "drilling",
    "assembly",
    "inspection",
    "packaging",
    "buffer_storage",
    "custom",
)
COMPONENT_TYPES = ("motor", "bearing", "gearbox", "belt", "controller", "custom")
MEASUREMENT_TYPES = (
    "temperature",
    "pressure",
    "vibration",
    "speed",
    "current",
    "voltage",
    "power",
    "flow",
    "level",
    "proximity",
    "position",
    "force",
    "humidity",
    "count",
    "custom",
)
MACHINE_STATES = {
    "running": "Machine is processing or performing its configured operation.",
    "idle": "Machine is available but not currently processing.",
    "starved": "Machine is waiting for upstream material or work.",
    "blocked": "Machine cannot release work because downstream capacity is unavailable.",
    "faulted": "Machine has reported a fault and requires investigation.",
    "maintenance": "Machine is intentionally unavailable for maintenance.",
    "offline": "Machine is disconnected or its state is unknown.",
}
MACHINE_TEMPLATES = {
    "conveyor": {
        "label": "Conveyor",
        "suggested_capabilities": ["material_transport"],
    },
    "processing_station": {
        "label": "Generic processing station",
        "suggested_capabilities": ["process_workpiece"],
    },
    "cnc_cutting": {
        "label": "CNC / cutting",
        "suggested_capabilities": ["cut_material"],
    },
    "drilling": {
        "label": "Drilling",
        "suggested_capabilities": ["drill_material"],
    },
    "assembly": {
        "label": "Assembly",
        "suggested_capabilities": ["assemble_components"],
    },
    "inspection": {
        "label": "Inspection",
        "suggested_capabilities": ["inspect_workpiece"],
    },
    "packaging": {
        "label": "Packaging",
        "suggested_capabilities": ["package_product"],
    },
    "buffer_storage": {
        "label": "Buffer / storage",
        "suggested_capabilities": ["buffer_work_in_process"],
    },
}
SENSOR_UNITS = {
    "temperature": {"C", "°C", "F", "°F", "K"},
    "pressure": {"Pa", "kPa", "MPa", "bar", "psi"},
    "vibration": {"mm/s", "m/s²", "g"},
    "speed": {"rpm", "m/s", "ft/min"},
    "current": {"A", "mA"},
    "voltage": {"V", "mV", "kV"},
    "power": {"W", "kW", "MW"},
    "flow": {"L/min", "m³/h", "gal/min"},
    "level": {"%", "mm", "cm", "m"},
    "proximity": {"bool", "mm", "cm", "in"},
    "position": {"mm", "cm", "m", "in", "ft"},
    "force": {"N", "kN", "lbf"},
    "humidity": {"%", "g/m³"},
    "count": {"count", "units/min", "units/h"},
}
UNIT_PREFERENCES = {"system", "temperature"}
CLOCK_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class AssetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ShiftRequest(AssetRequest):
    day: int = Field(ge=0, le=6)
    name: str = Field(min_length=1, max_length=80)
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def validate_clock_time(cls, value: str) -> str:
        if not CLOCK_PATTERN.fullmatch(value):
            raise ValueError("Use 24-hour HH:MM time.")
        return value

    @model_validator(mode="after")
    def require_nonzero_duration(self):
        if self.start == self.end:
            raise ValueError("A shift must have a nonzero duration.")
        return self


class OperatingCalendarRequest(AssetRequest):
    shifts: list[ShiftRequest] = Field(default_factory=list, max_length=70)

    @model_validator(mode="after")
    def reject_overlapping_shifts(self):
        occupied: dict[int, list[tuple[int, int, str]]] = {
            day: [] for day in DAYS
        }
        for shift in self.shifts:
            start = shift.day * 1440 + _minutes(shift.start)
            end = shift.day * 1440 + _minutes(shift.end)
            if end <= start:
                end += 1440
            for segment_start, segment_end in _weekly_segments(start, end):
                for existing_start, existing_end, existing_name in occupied[
                    segment_start // 1440
                ]:
                    if segment_start < existing_end and existing_start < segment_end:
                        raise ValueError(
                            f"Shift '{shift.name}' overlaps with '{existing_name}'."
                        )
                occupied[segment_start // 1440].append(
                    (segment_start, segment_end, shift.name)
                )
        return self


class UnitPreferencesRequest(AssetRequest):
    system: Literal["metric", "imperial"] = "metric"
    temperature: Literal["C", "F"] = "C"


class FactoryCreateRequest(AssetRequest):
    name: str = Field(min_length=1, max_length=160)
    timezone: str = "UTC"
    description: str = Field(default="", max_length=4000)
    unit_preferences: UnitPreferencesRequest = Field(
        default_factory=UnitPreferencesRequest
    )
    operating_calendar: OperatingCalendarRequest = Field(
        default_factory=OperatingCalendarRequest
    )

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Choose a valid IANA timezone.") from error
        return value


class FactoryUpdateRequest(AssetRequest):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    timezone: str | None = None
    description: str | None = Field(default=None, max_length=4000)
    unit_preferences: UnitPreferencesRequest | None = None
    operating_calendar: OperatingCalendarRequest | None = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError as error:
                raise ValueError("Choose a valid IANA timezone.") from error
        return value

    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one factory field to update.")
        return self


class LineCreateRequest(AssetRequest):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)


class LineUpdateRequest(AssetRequest):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one production-line field to update.")
        return self


class MachineCreateRequest(AssetRequest):
    identity: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    machine_type: Literal[
        "conveyor",
        "processing_station",
        "cnc_cutting",
        "drilling",
        "assembly",
        "inspection",
        "packaging",
        "buffer_storage",
        "custom",
    ]
    custom_type_name: str = Field(default="", max_length=120)
    capabilities: list[str] = Field(default_factory=list, max_length=32)
    manufacturer: str = Field(default="", max_length=160)
    model: str = Field(default="", max_length=160)
    nominal_cycle_time_seconds: float = Field(gt=0, le=10_000_000)
    capacity_per_hour: float = Field(gt=0, le=10_000_000)
    operating_state: Literal[
        "running",
        "idle",
        "starved",
        "blocked",
        "faulted",
        "maintenance",
        "offline",
    ] = "offline"

    @field_validator("identity", "name", "custom_type_name", "manufacturer", "model")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, value: list[str]) -> list[str]:
        normalized = [capability.strip() for capability in value]
        if any(not capability for capability in normalized):
            raise ValueError("Capabilities cannot be blank.")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Capabilities must be unique.")
        return normalized

    @model_validator(mode="after")
    def validate_custom_type(self):
        if self.machine_type == "custom" and not self.custom_type_name:
            raise ValueError("Enter a name for the custom station type.")
        if self.machine_type != "custom" and self.custom_type_name:
            raise ValueError("Custom station type name only applies to custom stations.")
        return self


class MachineUpdateRequest(AssetRequest):
    identity: str | None = Field(default=None, min_length=1, max_length=120)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    machine_type: Literal[
        "conveyor",
        "processing_station",
        "cnc_cutting",
        "drilling",
        "assembly",
        "inspection",
        "packaging",
        "buffer_storage",
        "custom",
    ] | None = None
    custom_type_name: str | None = Field(default=None, max_length=120)
    capabilities: list[str] | None = Field(default=None, max_length=32)
    manufacturer: str | None = Field(default=None, max_length=160)
    model: str | None = Field(default=None, max_length=160)
    nominal_cycle_time_seconds: float | None = Field(default=None, gt=0, le=10_000_000)
    capacity_per_hour: float | None = Field(default=None, gt=0, le=10_000_000)
    operating_state: Literal[
        "running",
        "idle",
        "starved",
        "blocked",
        "faulted",
        "maintenance",
        "offline",
    ] | None = None

    @model_validator(mode="after")
    def require_changes_and_valid_custom_type(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one machine field to update.")
        if self.machine_type == "custom" and not self.custom_type_name:
            raise ValueError("Include a name for the custom station type.")
        if self.machine_type not in (None, "custom") and self.custom_type_name:
            raise ValueError("Custom station type name only applies to custom stations.")
        return self


class ComponentCreateRequest(AssetRequest):
    identity: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    component_type: Literal["motor", "bearing", "gearbox", "belt", "controller", "custom"]
    manufacturer: str = Field(default="", max_length=160)
    model: str = Field(default="", max_length=160)


class ComponentUpdateRequest(AssetRequest):
    identity: str | None = Field(default=None, min_length=1, max_length=120)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    component_type: Literal[
        "motor", "bearing", "gearbox", "belt", "controller", "custom"
    ] | None = None
    manufacturer: str | None = Field(default=None, max_length=160)
    model: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one component field to update.")
        return self


class ThresholdsRequest(AssetRequest):
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.minimum is not None and self.maximum is not None:
            if self.minimum >= self.maximum:
                raise ValueError("Minimum threshold must be lower than maximum.")
        return self


class CalibrationRequest(AssetRequest):
    last_calibrated_at: datetime | None = None
    calibration_due_at: datetime | None = None
    offset: float | None = None
    scale: float | None = Field(default=None, gt=0)
    notes: str = Field(default="", max_length=1000)

    @field_validator("last_calibrated_at", "calibration_due_at")
    @classmethod
    def require_timezone_on_dates(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Calibration timestamps must include a timezone.")
        return value

    @model_validator(mode="after")
    def validate_calibration_dates(self):
        if (
            self.last_calibrated_at is not None
            and self.calibration_due_at is not None
            and self.calibration_due_at <= self.last_calibrated_at
        ):
            raise ValueError("Calibration due date must follow the last calibration date.")
        return self


class SensorCreateRequest(AssetRequest):
    identity: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    measurement_type: Literal[
        "temperature",
        "pressure",
        "vibration",
        "speed",
        "current",
        "voltage",
        "power",
        "flow",
        "level",
        "proximity",
        "position",
        "force",
        "humidity",
        "count",
        "custom",
    ]
    unit: str = Field(min_length=1, max_length=32)
    expected_reporting_interval_seconds: float = Field(gt=0, le=31_536_000)
    thresholds: ThresholdsRequest = Field(default_factory=ThresholdsRequest)
    calibration: CalibrationRequest = Field(default_factory=CalibrationRequest)

    @model_validator(mode="after")
    def validate_unit_for_measurement(self):
        _validate_unit(self.measurement_type, self.unit)
        return self


class SensorUpdateRequest(AssetRequest):
    identity: str | None = Field(default=None, min_length=1, max_length=120)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    measurement_type: Literal[
        "temperature",
        "pressure",
        "vibration",
        "speed",
        "current",
        "voltage",
        "power",
        "flow",
        "level",
        "proximity",
        "position",
        "force",
        "humidity",
        "count",
        "custom",
    ] | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    expected_reporting_interval_seconds: float | None = Field(
        default=None, gt=0, le=31_536_000
    )
    thresholds: ThresholdsRequest | None = None
    calibration: CalibrationRequest | None = None

    @model_validator(mode="after")
    def require_changes_and_valid_unit(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one sensor field to update.")
        if self.measurement_type is not None and self.unit is not None:
            _validate_unit(self.measurement_type, self.unit)
        return self


def _minutes(clock: str) -> int:
    parsed = time.fromisoformat(clock)
    return parsed.hour * 60 + parsed.minute


def _weekly_segments(start: int, end: int) -> list[tuple[int, int]]:
    week_minutes = 7 * 1440
    if end - start >= week_minutes:
        raise ValueError("A shift cannot span an entire week.")
    normalized_start = start % week_minutes
    normalized_end = normalized_start + (end - start)
    if normalized_end <= week_minutes:
        return [(normalized_start, normalized_end)]
    return [
        (normalized_start, week_minutes),
        (0, normalized_end - week_minutes),
    ]


def _validate_unit(measurement_type: str, unit: str) -> None:
    if measurement_type == "custom":
        if not unit.strip():
            raise ValueError("A custom measurement requires a unit label.")
        return
    valid_units = SENSOR_UNITS.get(measurement_type)
    if valid_units is None or unit not in valid_units:
        raise ValueError(
            f"Unit '{unit}' is not valid for measurement type '{measurement_type}'."
        )


def _id(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=404, detail="Asset not found.")
    return ObjectId(value)


def _transaction(callback):
    with get_mongo_client().start_session() as session:
        return session.with_transaction(callback)


def _options(session) -> dict[str, Any]:
    return {"session": session}


def _serialize(document: dict[str, Any]) -> dict[str, Any]:
    serialized = {}
    for key, value in document.items():
        target_key = "id" if key == "_id" else key
        if isinstance(value, ObjectId):
            serialized[target_key] = str(value)
        elif isinstance(value, list):
            serialized[target_key] = [
                _serialize(item) if isinstance(item, dict) else item
                for item in value
            ]
        elif isinstance(value, dict):
            serialized[target_key] = _serialize(value)
        else:
            serialized[target_key] = value
    return serialized


def _get_scoped(
    collection_name: str,
    document_id: ObjectId,
    organization_id: ObjectId,
    *,
    include_archived: bool = False,
) -> dict[str, Any]:
    query: dict[str, Any] = {
        "_id": document_id,
        "organization_id": organization_id,
    }
    if not include_archived:
        query["archived_at"] = None
    document = get_database()[collection_name].find_one(query)
    if document is None:
        raise HTTPException(status_code=404, detail="Asset not found.")
    return document


def _audit(
    session,
    principal: Principal,
    *,
    entity_type: str,
    entity_id: ObjectId,
    action: str,
    changes: dict[str, Any] | None = None,
) -> None:
    get_database().asset_audit_logs.insert_one(
        {
            "organization_id": principal.organization_id,
            "actor_user_id": principal.user_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "changes": changes or {},
            "created_at": datetime.now(UTC),
        },
        **_options(session),
    )


def _insert_asset(
    collection_name: str,
    document: dict[str, Any],
    principal: Principal,
    *,
    entity_type: str,
) -> ObjectId:
    now = datetime.now(UTC)
    document.update(
        {
            "organization_id": principal.organization_id,
            "created_at": now,
            "updated_at": now,
            "archived_at": None,
            "archive_parent_id": None,
        }
    )

    def operation(session):
        result = get_database()[collection_name].insert_one(
            document,
            **_options(session),
        )
        _audit(
            session,
            principal,
            entity_type=entity_type,
            entity_id=result.inserted_id,
            action="created",
            changes={key: value for key, value in document.items() if key != "organization_id"},
        )
        return result.inserted_id

    try:
        return _transaction(operation)
    except DuplicateKeyError as error:
        raise HTTPException(
            status_code=409,
            detail="An asset with this identity already exists in the organization.",
        ) from error


def _update_asset(
    collection_name: str,
    document_id: ObjectId,
    changes: dict[str, Any],
    principal: Principal,
    *,
    entity_type: str,
) -> dict[str, Any]:
    current = _get_scoped(collection_name, document_id, principal.organization_id)
    if any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="Asset fields cannot be cleared.")
    changes.pop("archived_at", None)
    changes.pop("archive_parent_id", None)
    now = datetime.now(UTC)
    audit_changes = {
        key: {"from": current.get(key), "to": value}
        for key, value in changes.items()
        if current.get(key) != value
    }
    if not audit_changes:
        return current

    def operation(session):
        result = get_database()[collection_name].update_one(
            {
                "_id": document_id,
                "organization_id": principal.organization_id,
                "archived_at": None,
            },
            {"$set": {**changes, "updated_at": now}},
            **_options(session),
        )
        if result.modified_count != 1:
            raise HTTPException(status_code=404, detail="Asset not found.")
        _audit(
            session,
            principal,
            entity_type=entity_type,
            entity_id=document_id,
            action="updated",
            changes=audit_changes,
        )
        return get_database()[collection_name].find_one(
            {"_id": document_id, "organization_id": principal.organization_id},
            **_options(session),
        )

    try:
        return _transaction(operation)
    except DuplicateKeyError as error:
        raise HTTPException(
            status_code=409,
            detail="An asset with this identity already exists in the organization.",
        ) from error


def _active_children(
    collection_name: str,
    principal: Principal,
    query: dict[str, Any],
    session,
) -> list[dict[str, Any]]:
    return list(
        get_database()[collection_name].find(
            {
                **query,
                "organization_id": principal.organization_id,
                "archived_at": None,
            },
            **_options(session),
        )
    )


def _descendant_collections(
    entity_type: str,
    document: dict[str, Any],
    principal: Principal,
    session,
) -> list[tuple[str, str, list[dict[str, Any]]]]:
    descendants: list[tuple[str, str, list[dict[str, Any]]]] = []
    if entity_type == "factory":
        lines = _active_children(
            "production_lines",
            principal,
            {"factory_id": document["_id"]},
            session,
        )
        descendants.append(("production_lines", "line", lines))
        line_ids = [line["_id"] for line in lines]
        machines = (
            _active_children(
                "machines",
                principal,
                {"line_id": {"$in": line_ids}},
                session,
            )
            if line_ids
            else []
        )
    elif entity_type == "line":
        lines = []
        machines = _active_children(
            "machines",
            principal,
            {"line_id": document["_id"]},
            session,
        )
    elif entity_type == "machine":
        lines = []
        machines = []
    else:
        lines = []
        machines = []

    if machines:
        descendants.append(("machines", "machine", machines))
    machine_ids = [machine["_id"] for machine in machines]
    if machine_ids:
        components = _active_children(
            "components",
            principal,
            {"machine_id": {"$in": machine_ids}},
            session,
        )
    elif entity_type == "machine":
        components = _active_children(
            "components",
            principal,
            {"machine_id": document["_id"]},
            session,
        )
    else:
        components = []
    if components:
        descendants.append(("components", "component", components))
    component_ids = [component["_id"] for component in components]
    if component_ids:
        sensors = _active_children(
            "sensors",
            principal,
            {"component_id": {"$in": component_ids}},
            session,
        )
    elif entity_type == "component":
        sensors = _active_children(
            "sensors",
            principal,
            {"component_id": document["_id"]},
            session,
        )
    else:
        sensors = []
    if sensors:
        descendants.append(("sensors", "sensor", sensors))

    return descendants


def _archive_descendants(
    session,
    entity_type: str,
    document: dict[str, Any],
    principal: Principal,
    *,
    archived_at: datetime,
) -> None:
    parent_id = document["_id"]
    for collection_name, child_type, children in _descendant_collections(
        entity_type,
        document,
        principal,
        session,
    ):
        for child in children:
            get_database()[collection_name].update_one(
                {
                    "_id": child["_id"],
                    "organization_id": principal.organization_id,
                    "archived_at": None,
                },
                {
                    "$set": {
                        "archived_at": archived_at,
                        "archive_parent_id": parent_id,
                        "updated_at": archived_at,
                    }
                },
                **_options(session),
            )
            _audit(
                session,
                principal,
                entity_type=child_type,
                entity_id=child["_id"],
                action="archived",
                changes={"archive_parent_id": str(parent_id)},
            )


def _archive_asset(
    collection_name: str,
    entity_type: str,
    document_id: ObjectId,
    principal: Principal,
) -> dict[str, Any]:
    current = _get_scoped(collection_name, document_id, principal.organization_id)
    now = datetime.now(UTC)

    def operation(session):
        result = get_database()[collection_name].update_one(
            {
                "_id": document_id,
                "organization_id": principal.organization_id,
                "archived_at": None,
            },
            {"$set": {"archived_at": now, "updated_at": now}},
            **_options(session),
        )
        if result.modified_count != 1:
            raise HTTPException(status_code=404, detail="Asset not found.")
        _audit(
            session,
            principal,
            entity_type=entity_type,
            entity_id=document_id,
            action="archived",
            changes={},
        )
        _archive_descendants(
            session,
            entity_type,
            current,
            principal,
            archived_at=now,
        )
        return get_database()[collection_name].find_one(
            {"_id": document_id, "organization_id": principal.organization_id},
            **_options(session),
        )

    return _transaction(operation)


def _reopen_asset(
    collection_name: str,
    entity_type: str,
    document_id: ObjectId,
    principal: Principal,
) -> dict[str, Any]:
    current = _get_scoped(
        collection_name,
        document_id,
        principal.organization_id,
        include_archived=True,
    )
    if current.get("archived_at") is None:
        return current
    parent_lookup = {
        "line": ("factories", "factory_id"),
        "machine": ("production_lines", "line_id"),
        "component": ("machines", "machine_id"),
        "sensor": ("components", "component_id"),
    }.get(entity_type)
    now = datetime.now(UTC)

    def operation(session):
        if parent_lookup is not None:
            parent_collection, parent_field = parent_lookup
            parent = get_database()[parent_collection].find_one(
                {
                    "_id": current[parent_field],
                    "organization_id": principal.organization_id,
                    "archived_at": None,
                },
                **_options(session),
            )
            if parent is None:
                raise HTTPException(
                    status_code=409,
                    detail="Reopen the archived parent asset before reopening this record.",
                )
        result = get_database()[collection_name].update_one(
            {
                "_id": document_id,
                "organization_id": principal.organization_id,
                "archived_at": {"$ne": None},
            },
            {
                "$set": {"archived_at": None, "updated_at": now},
                "$unset": {"archive_parent_id": ""},
            },
            **_options(session),
        )
        if result.modified_count != 1:
            raise HTTPException(status_code=404, detail="Asset not found.")
        _audit(
            session,
            principal,
            entity_type=entity_type,
            entity_id=document_id,
            action="reopened",
        )
        child_collections = (
            ("production_lines", "line"),
            ("machines", "machine"),
            ("components", "component"),
            ("sensors", "sensor"),
        )
        for child_collection, child_type in child_collections:
            children = list(
                get_database()[child_collection].find(
                    {
                        "organization_id": principal.organization_id,
                        "archive_parent_id": document_id,
                        "archived_at": {"$ne": None},
                    },
                    **_options(session),
                )
            )
            for child in children:
                get_database()[child_collection].update_one(
                    {
                        "_id": child["_id"],
                        "organization_id": principal.organization_id,
                    },
                    {
                        "$set": {"archived_at": None, "updated_at": now},
                        "$unset": {"archive_parent_id": ""},
                    },
                    **_options(session),
                )
                _audit(
                    session,
                    principal,
                    entity_type=child_type,
                    entity_id=child["_id"],
                    action="reopened",
                )
        return get_database()[collection_name].find_one(
            {"_id": document_id, "organization_id": principal.organization_id},
            **_options(session),
        )

    return _transaction(operation)


def _list_children(
    collection_name: str,
    query: dict[str, Any],
    principal: Principal,
    *,
    include_archived: bool,
) -> list[dict[str, Any]]:
    selector = {"organization_id": principal.organization_id, **query}
    if not include_archived:
        selector["archived_at"] = None
    return [
        _serialize(document)
        for document in get_database()[collection_name].find(selector).sort(
            "created_at", 1
        )
    ]


@router.get("/asset-templates")
def get_asset_templates() -> dict[str, Any]:
    return {
        "templates": [
            {"key": key, **value, "physics_model": None, "model_validation_status": "not_validated"}
            for key, value in MACHINE_TEMPLATES.items()
        ],
        "custom_type_available": True,
        "note": "Templates provide editable metadata suggestions only; no physics model is validated.",
    }


@router.get("/machine-states")
def get_machine_states() -> dict[str, str]:
    return MACHINE_STATES


@router.get("/sensor-units")
def get_sensor_units() -> dict[str, Any]:
    return {measurement: sorted(units) for measurement, units in SENSOR_UNITS.items()}


@router.get("/factories")
def list_factories(
    include_archived: bool = Query(default=False),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    query: dict[str, Any] = {"organization_id": principal.organization_id}
    if not include_archived:
        query["archived_at"] = None
    factories = get_database().factories.find(query).sort("created_at", 1)
    return {"factories": [_serialize(factory) for factory in factories]}


@router.post("/factories", status_code=201)
def create_factory(
    payload: FactoryCreateRequest,
    principal: Principal = Depends(require_roles(*CAN_EDIT_ASSETS)),
) -> dict[str, Any]:
    document = payload.model_dump(mode="python")
    document["unit_preferences"] = payload.unit_preferences.model_dump()
    document["operating_calendar"] = {
        "shifts": [shift.model_dump() for shift in payload.operating_calendar.shifts]
    }
    document.pop("organization_id", None)
    result_id = _insert_asset("factories", document, principal, entity_type="factory")
    return _serialize(
        get_database().factories.find_one(
            {"_id": result_id, "organization_id": principal.organization_id}
        )
    )


@router.get("/factories/{factory_id}")
def get_factory(
    factory_id: str,
    include_archived: bool = Query(default=False),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    return _serialize(
        _get_scoped(
            "factories",
            _id(factory_id),
            principal.organization_id,
            include_archived=include_archived,
        )
    )


@router.patch("/factories/{factory_id}")
def update_factory(
    factory_id: str,
    payload: FactoryUpdateRequest,
    principal: Principal = Depends(require_roles(*CAN_EDIT_ASSETS)),
) -> dict[str, Any]:
    changes = payload.model_dump(exclude_unset=True, mode="python")
    if isinstance(changes.get("unit_preferences"), UnitPreferencesRequest):
        changes["unit_preferences"] = changes["unit_preferences"].model_dump()
    if isinstance(changes.get("operating_calendar"), OperatingCalendarRequest):
        changes["operating_calendar"] = {
            "shifts": [
                shift.model_dump()
                for shift in changes["operating_calendar"].shifts
            ]
        }
    return _serialize(
        _update_asset(
            "factories",
            _id(factory_id),
            changes,
            principal,
            entity_type="factory",
        )
    )


@router.delete("/factories/{factory_id}")
def archive_factory(
    factory_id: str,
    principal: Principal = Depends(require_roles(*CAN_EDIT_ASSETS)),
) -> dict[str, Any]:
    return _serialize(
        _archive_asset("factories", "factory", _id(factory_id), principal)
    )


@router.post("/factories/{factory_id}/reopen")
def reopen_factory(
    factory_id: str,
    principal: Principal = Depends(require_roles(*CAN_EDIT_ASSETS)),
) -> dict[str, Any]:
    return _serialize(
        _reopen_asset("factories", "factory", _id(factory_id), principal)
    )


@router.get("/factories/{factory_id}/lines")
def list_lines(
    factory_id: str,
    include_archived: bool = Query(default=False),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    factory_id_value = _id(factory_id)
    _get_scoped("factories", factory_id_value, principal.organization_id, include_archived=include_archived)
    return {
        "lines": _list_children(
            "production_lines",
            {"factory_id": factory_id_value},
            principal,
            include_archived=include_archived,
        )
    }


@router.post("/factories/{factory_id}/lines", status_code=201)
def create_line(
    factory_id: str,
    payload: LineCreateRequest,
    principal: Principal = Depends(require_roles(*CAN_EDIT_ASSETS)),
) -> dict[str, Any]:
    factory_id_value = _id(factory_id)
    _get_scoped("factories", factory_id_value, principal.organization_id)
    line_id = _insert_asset(
        "production_lines",
        {
            **payload.model_dump(),
            "factory_id": factory_id_value,
        },
        principal,
        entity_type="line",
    )
    return _serialize(_get_scoped("production_lines", line_id, principal.organization_id))


@router.get("/lines/{line_id}")
def get_line(
    line_id: str,
    include_archived: bool = Query(default=False),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    return _serialize(
        _get_scoped(
            "production_lines",
            _id(line_id),
            principal.organization_id,
            include_archived=include_archived,
        )
    )


@router.patch("/lines/{line_id}")
def update_line(
    line_id: str,
    payload: LineUpdateRequest,
    principal: Principal = Depends(require_roles(*CAN_EDIT_ASSETS)),
) -> dict[str, Any]:
    return _serialize(
        _update_asset(
            "production_lines",
            _id(line_id),
            payload.model_dump(exclude_unset=True),
            principal,
            entity_type="line",
        )
    )


@router.delete("/lines/{line_id}")
def archive_line(
    line_id: str,
    principal: Principal = Depends(require_roles(*CAN_EDIT_ASSETS)),
) -> dict[str, Any]:
    return _serialize(_archive_asset("production_lines", "line", _id(line_id), principal))


@router.post("/lines/{line_id}/reopen")
def reopen_line(
    line_id: str,
    principal: Principal = Depends(require_roles(*CAN_EDIT_ASSETS)),
) -> dict[str, Any]:
    return _serialize(_reopen_asset("production_lines", "line", _id(line_id), principal))


@router.get("/lines/{line_id}/machines")
def list_machines(
    line_id: str,
    include_archived: bool = Query(default=False),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    line = _get_scoped(
        "production_lines",
        _id(line_id),
        principal.organization_id,
        include_archived=include_archived,
    )
    return {
        "machines": _list_children(
            "machines",
            {"factory_id": line["factory_id"], "line_id": line["_id"]},
            principal,
            include_archived=include_archived,
        )
    }


@router.post("/lines/{line_id}/machines", status_code=201)
def create_machine(
    line_id: str,
    payload: MachineCreateRequest,
    principal: Principal = Depends(require_roles(*CAN_EDIT_ASSETS)),
) -> dict[str, Any]:
    line = _get_scoped("production_lines", _id(line_id), principal.organization_id)
    machine_id = _insert_asset(
        "machines",
        {
            **payload.model_dump(),
            "factory_id": line["factory_id"],
            "line_id": line["_id"],
            "model_validation_status": "not_validated",
        },
        principal,
        entity_type="machine",
    )
    return _serialize(_get_scoped("machines", machine_id, principal.organization_id))


@router.get("/machines/{machine_id}")
def get_machine(
    machine_id: str,
    include_archived: bool = Query(default=False),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    return _serialize(
        _get_scoped(
            "machines",
            _id(machine_id),
            principal.organization_id,
            include_archived=include_archived,
        )
    )


@router.patch("/machines/{machine_id}")
def update_machine(
    machine_id: str,
    payload: MachineUpdateRequest,
    principal: Principal = Depends(require_roles(*CAN_EDIT_ASSETS)),
) -> dict[str, Any]:
    return _serialize(
        _update_asset(
            "machines",
            _id(machine_id),
            payload.model_dump(exclude_unset=True),
            principal,
            entity_type="machine",
        )
    )


@router.delete("/machines/{machine_id}")
def archive_machine(
    machine_id: str,
    principal: Principal = Depends(require_roles(*CAN_EDIT_ASSETS)),
) -> dict[str, Any]:
    return _serialize(_archive_asset("machines", "machine", _id(machine_id), principal))


@router.post("/machines/{machine_id}/reopen")
def reopen_machine(
    machine_id: str,
    principal: Principal = Depends(require_roles(*CAN_EDIT_ASSETS)),
) -> dict[str, Any]:
    return _serialize(_reopen_asset("machines", "machine", _id(machine_id), principal))


@router.get("/machines/{machine_id}/components")
def list_components(
    machine_id: str,
    include_archived: bool = Query(default=False),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    machine = _get_scoped(
        "machines",
        _id(machine_id),
        principal.organization_id,
        include_archived=include_archived,
    )
    return {
        "components": _list_children(
            "components",
            {
                "factory_id": machine["factory_id"],
                "line_id": machine["line_id"],
                "machine_id": machine["_id"],
            },
            principal,
            include_archived=include_archived,
        )
    }


@router.post("/machines/{machine_id}/components", status_code=201)
def create_component(
    machine_id: str,
    payload: ComponentCreateRequest,
    principal: Principal = Depends(require_roles(*CAN_EDIT_ASSETS)),
) -> dict[str, Any]:
    machine = _get_scoped("machines", _id(machine_id), principal.organization_id)
    component_id = _insert_asset(
        "components",
        {
            **payload.model_dump(),
            "factory_id": machine["factory_id"],
            "line_id": machine["line_id"],
            "machine_id": machine["_id"],
        },
        principal,
        entity_type="component",
    )
    return _serialize(_get_scoped("components", component_id, principal.organization_id))


@router.get("/components/{component_id}")
def get_component(
    component_id: str,
    include_archived: bool = Query(default=False),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    return _serialize(
        _get_scoped(
            "components",
            _id(component_id),
            principal.organization_id,
            include_archived=include_archived,
        )
    )


@router.patch("/components/{component_id}")
def update_component(
    component_id: str,
    payload: ComponentUpdateRequest,
    principal: Principal = Depends(require_roles(*CAN_EDIT_ASSETS)),
) -> dict[str, Any]:
    return _serialize(
        _update_asset(
            "components",
            _id(component_id),
            payload.model_dump(exclude_unset=True),
            principal,
            entity_type="component",
        )
    )


@router.delete("/components/{component_id}")
def archive_component(
    component_id: str,
    principal: Principal = Depends(require_roles(*CAN_EDIT_ASSETS)),
) -> dict[str, Any]:
    return _serialize(
        _archive_asset("components", "component", _id(component_id), principal)
    )


@router.post("/components/{component_id}/reopen")
def reopen_component(
    component_id: str,
    principal: Principal = Depends(require_roles(*CAN_EDIT_ASSETS)),
) -> dict[str, Any]:
    return _serialize(
        _reopen_asset("components", "component", _id(component_id), principal)
    )


@router.get("/components/{component_id}/sensors")
def list_sensors(
    component_id: str,
    include_archived: bool = Query(default=False),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    component = _get_scoped(
        "components",
        _id(component_id),
        principal.organization_id,
        include_archived=include_archived,
    )
    return {
        "sensors": _list_children(
            "sensors",
            {
                "factory_id": component["factory_id"],
                "line_id": component["line_id"],
                "machine_id": component["machine_id"],
                "component_id": component["_id"],
            },
            principal,
            include_archived=include_archived,
        )
    }


@router.post("/components/{component_id}/sensors", status_code=201)
def create_sensor(
    component_id: str,
    payload: SensorCreateRequest,
    principal: Principal = Depends(require_roles(*CAN_EDIT_ASSETS)),
) -> dict[str, Any]:
    component = _get_scoped("components", _id(component_id), principal.organization_id)
    sensor_id = _insert_asset(
        "sensors",
        {
            **payload.model_dump(),
            "thresholds": payload.thresholds.model_dump(),
            "calibration": payload.calibration.model_dump(mode="python"),
            "factory_id": component["factory_id"],
            "line_id": component["line_id"],
            "machine_id": component["machine_id"],
            "component_id": component["_id"],
        },
        principal,
        entity_type="sensor",
    )
    return _serialize(_get_scoped("sensors", sensor_id, principal.organization_id))


@router.get("/sensors/{sensor_id}")
def get_sensor(
    sensor_id: str,
    include_archived: bool = Query(default=False),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    return _serialize(
        _get_scoped(
            "sensors",
            _id(sensor_id),
            principal.organization_id,
            include_archived=include_archived,
        )
    )


@router.patch("/sensors/{sensor_id}")
def update_sensor(
    sensor_id: str,
    payload: SensorUpdateRequest,
    principal: Principal = Depends(require_roles(*CAN_EDIT_ASSETS)),
) -> dict[str, Any]:
    changes = payload.model_dump(exclude_unset=True, mode="python")
    if isinstance(changes.get("thresholds"), ThresholdsRequest):
        changes["thresholds"] = changes["thresholds"].model_dump()
    if isinstance(changes.get("calibration"), CalibrationRequest):
        changes["calibration"] = changes["calibration"].model_dump(mode="python")
    current = _get_scoped("sensors", _id(sensor_id), principal.organization_id)
    measurement_type = changes.get("measurement_type", current["measurement_type"])
    unit = changes.get("unit", current["unit"])
    _validate_unit(measurement_type, unit)
    return _serialize(
        _update_asset(
            "sensors",
            _id(sensor_id),
            changes,
            principal,
            entity_type="sensor",
        )
    )


@router.delete("/sensors/{sensor_id}")
def archive_sensor(
    sensor_id: str,
    principal: Principal = Depends(require_roles(*CAN_EDIT_ASSETS)),
) -> dict[str, Any]:
    return _serialize(_archive_asset("sensors", "sensor", _id(sensor_id), principal))


@router.post("/sensors/{sensor_id}/reopen")
def reopen_sensor(
    sensor_id: str,
    principal: Principal = Depends(require_roles(*CAN_EDIT_ASSETS)),
) -> dict[str, Any]:
    return _serialize(_reopen_asset("sensors", "sensor", _id(sensor_id), principal))


@router.get("/asset-audit")
def list_asset_audit(
    entity_type: Literal["factory", "line", "machine", "component", "sensor"] | None = None,
    entity_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(require_roles(*CAN_EDIT_ASSETS)),
) -> dict[str, Any]:
    query: dict[str, Any] = {"organization_id": principal.organization_id}
    if entity_type is not None:
        query["entity_type"] = entity_type
    if entity_id is not None:
        query["entity_id"] = _id(entity_id)
    records = get_database().asset_audit_logs.find(query).sort("created_at", -1).limit(limit)
    return {"events": [_serialize(record) for record in records]}
