import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.routes.auth import (
    Principal,
    get_current_principal,
    require_csrf,
    require_roles,
)
from app.core.config import get_settings
from app.db.client import get_database, get_mongo_client
from app.telemetry.devices import (
    authenticate_device_token,
    audit_device_event,
    default_credential_expiry,
    new_device_secret,
    sensor_quantity,
)
from app.telemetry.readings import as_utc

router = APIRouter(dependencies=[Depends(require_csrf)])
logger = logging.getLogger(__name__)
DEVICE_ADMIN_ROLES = ("owner", "administrator", "engineer")
MAX_PERMITTED_SENSORS = 100
MAX_PERMITTED_QUANTITIES = 32


class SensorPermissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensor_id: str = Field(min_length=1, max_length=64)
    quantities: list[str] | None = Field(default=None, max_length=MAX_PERMITTED_QUANTITIES)

    @field_validator("quantities")
    @classmethod
    def unique_quantities(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and (not value or len(set(value)) != len(value)):
            raise ValueError("Provide unique permitted quantities or omit the list.")
        return value


class DeviceCredentialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    sensor_permissions: list[SensorPermissionRequest] = Field(
        min_length=1, max_length=MAX_PERMITTED_SENSORS
    )
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def require_aware_expiry(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Credential expiry must include a timezone.")
        return value

    @model_validator(mode="after")
    def unique_sensors(self):
        ids = [permission.sensor_id for permission in self.sensor_permissions]
        if len(set(ids)) != len(ids):
            raise ValueError("Sensor permissions must not contain duplicate sensor IDs.")
        return self


def _object_id(raw_id: str) -> ObjectId:
    try:
        return ObjectId(raw_id)
    except InvalidId as error:
        raise HTTPException(status_code=404, detail="Device credential was not found.") from error


def _validate_expiry(expires_at: datetime | None, now: datetime) -> datetime:
    resolved = expires_at.astimezone(UTC) if expires_at else default_credential_expiry(now)
    if resolved <= now:
        raise HTTPException(status_code=422, detail="Credential expiry must be in the future.")
    if resolved > now + timedelta(days=366):
        raise HTTPException(status_code=422, detail="Credential expiry cannot exceed 366 days.")
    return resolved


def _permissions(database, organization_id: ObjectId, requested) -> list[dict[str, Any]]:
    permissions = []
    for request in requested:
        try:
            sensor_id = ObjectId(request.sensor_id)
        except InvalidId as error:
            raise HTTPException(
                status_code=422,
                detail=f"Sensor ID {request.sensor_id!r} is not valid.",
            ) from error
        sensor = database.sensors.find_one(
            {
                "_id": sensor_id,
                "organization_id": organization_id,
                "archived_at": None,
            }
        )
        if sensor is None:
            raise HTTPException(
                status_code=404,
                detail=f"Sensor {request.sensor_id!r} was not found in this workspace.",
            )
        quantity = sensor_quantity(sensor)
        if request.quantities is not None and any(
            item != quantity for item in request.quantities
        ):
            raise HTTPException(
                status_code=422,
                detail=f"Sensor {request.sensor_id!r} only supports quantity {quantity!r}.",
            )
        permissions.append(
            {
                "sensor_id": sensor_id,
                "quantities": request.quantities,
            }
        )
    return permissions


def _serialize(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "credential_id": str(record["_id"]),
        "key_id": record["key_id"],
        "name": record["name"],
        "sensor_permissions": [
            {
                "sensor_id": str(item["sensor_id"]),
                "quantities": item.get("quantities"),
            }
            for item in record["sensor_permissions"]
        ],
        "expires_at": as_utc(record["expires_at"]).isoformat(),
        "created_at": as_utc(record["created_at"]).isoformat(),
        "last_used_at": (
            as_utc(record["last_used_at"]).isoformat()
            if record.get("last_used_at")
            else None
        ),
        "revoked_at": (
            as_utc(record["revoked_at"]).isoformat()
            if record.get("revoked_at")
            else None
        ),
    }


def _new_record(
    *,
    name: str,
    organization_id: ObjectId,
    actor_user_id: ObjectId,
    sensor_permissions: list[dict[str, Any]],
    expires_at: datetime,
) -> tuple[dict[str, Any], str]:
    key_id, secret, secret_hash = new_device_secret()
    now = datetime.now(UTC)
    record = {
        "_id": ObjectId(),
        "organization_id": organization_id,
        "created_by": actor_user_id,
        "key_id": key_id,
        "secret_hash": secret_hash,
        "name": name,
        "sensor_permissions": sensor_permissions,
        "created_at": now,
        "updated_at": now,
        "expires_at": expires_at,
        "last_used_at": None,
        "revoked_at": None,
        "credential_version": 1,
    }
    return record, secret


def _insert_record(
    database,
    record: dict[str, Any],
    actor_user_id: ObjectId,
    session=None,
) -> None:
    database.device_credentials.insert_one(record, session=session)
    audit_device_event(
        database,
        organization_id=record["organization_id"],
        event="credential_created",
        credential_id=record["_id"],
        actor_user_id=actor_user_id,
        created_at=record["created_at"],
        session=session,
    )


@router.post("/device-credentials", status_code=201)
def create_device_credential(
    payload: DeviceCredentialCreate,
    principal: Principal = Depends(require_roles(*DEVICE_ADMIN_ROLES)),
) -> dict[str, Any]:
    now = datetime.now(UTC)
    expires_at = _validate_expiry(payload.expires_at, now)
    permissions = _permissions(
        get_database(), principal.organization_id, payload.sensor_permissions
    )
    record, secret = _new_record(
        name=payload.name,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        sensor_permissions=permissions,
        expires_at=expires_at,
    )
    with get_mongo_client().start_session() as session:
        session.with_transaction(
            lambda txn: _insert_record(
                get_database(), record, principal.user_id, txn
            )
        )
    return {"credential": _serialize(record), "secret": secret}


@router.get("/device-credentials")
def list_device_credentials(
    sensor_id: str | None = None,
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    query: dict[str, Any] = {"organization_id": principal.organization_id}
    if sensor_id:
        try:
            sensor_object_id = ObjectId(sensor_id)
        except InvalidId as error:
            raise HTTPException(status_code=404, detail="Sensor was not found.") from error
        if get_database().sensors.find_one(
            {"_id": sensor_object_id, "organization_id": principal.organization_id}
        ) is None:
            raise HTTPException(status_code=404, detail="Sensor was not found.")
        query["sensor_permissions.sensor_id"] = sensor_object_id
    records = list(
        get_database().device_credentials.find(query).sort("created_at", -1).limit(100)
    )
    return {"credentials": [_serialize(record) for record in records]}


@router.post("/device-credentials/{credential_id}/rotate")
def rotate_device_credential(
    credential_id: str,
    principal: Principal = Depends(require_roles(*DEVICE_ADMIN_ROLES)),
) -> dict[str, Any]:
    database = get_database()
    record = database.device_credentials.find_one(
        {
            "_id": _object_id(credential_id),
            "organization_id": principal.organization_id,
            "revoked_at": None,
        }
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Active device credential was not found.")
    now = datetime.now(UTC)
    if as_utc(record["expires_at"]) <= now:
        raise HTTPException(status_code=409, detail="Expired credentials cannot be rotated.")
    replacement, secret = _new_record(
        name=record["name"],
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        sensor_permissions=record["sensor_permissions"],
        expires_at=as_utc(record["expires_at"]),
    )

    def rotate_transaction(session) -> None:
        revoked = database.device_credentials.update_one(
            {
                "_id": record["_id"],
                "organization_id": principal.organization_id,
                "revoked_at": None,
            },
            {"$set": {"revoked_at": now, "updated_at": now}},
            session=session,
        )
        if revoked.matched_count != 1:
            raise HTTPException(status_code=409, detail="Credential changed during rotation; retry.")
        _insert_record(database, replacement, principal.user_id, session)
        audit_device_event(
            database,
            organization_id=principal.organization_id,
            event="credential_rotated",
            credential_id=record["_id"],
            actor_user_id=principal.user_id,
            created_at=now,
            session=session,
        )

    with get_mongo_client().start_session() as session:
        session.with_transaction(rotate_transaction)
    return {"credential": _serialize(replacement), "secret": secret}


@router.post("/device-credentials/{credential_id}/revoke")
def revoke_device_credential(
    credential_id: str,
    principal: Principal = Depends(require_roles(*DEVICE_ADMIN_ROLES)),
) -> dict[str, Any]:
    database = get_database()
    now = datetime.now(UTC)
    object_id = _object_id(credential_id)
    record = database.device_credentials.find_one(
        {
            "_id": object_id,
            "organization_id": principal.organization_id,
            "revoked_at": None,
        }
    )
    if record is None:
        existing = database.device_credentials.find_one(
            {
                "_id": _object_id(credential_id),
                "organization_id": principal.organization_id,
            }
        )
        if existing is None:
            raise HTTPException(status_code=404, detail="Device credential was not found.")
        raise HTTPException(status_code=409, detail="Device credential is already revoked.")
    with get_mongo_client().start_session() as session:
        def revoke_transaction(txn) -> None:
            updated = database.device_credentials.update_one(
                {
                    "_id": object_id,
                    "organization_id": principal.organization_id,
                    "revoked_at": None,
                },
                {"$set": {"revoked_at": now, "updated_at": now}},
                session=txn,
            )
            if updated.matched_count != 1:
                raise HTTPException(status_code=409, detail="Credential changed during revocation; retry.")
            audit_device_event(
                database,
                organization_id=principal.organization_id,
                event="credential_revoked",
                credential_id=object_id,
                actor_user_id=principal.user_id,
                created_at=now,
                session=txn,
            )

        session.with_transaction(revoke_transaction)
    record["revoked_at"] = now
    record["updated_at"] = now
    return {"credential": _serialize(record)}


def get_device_credential(request: Request) -> dict[str, Any]:
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="A device bearer credential is required.")
    record = authenticate_device_token(get_database(), authorization[7:])
    if record is None:
        raise HTTPException(status_code=401, detail="The device credential is invalid or expired.")
    return record
