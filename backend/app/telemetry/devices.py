import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from bson import ObjectId

from app.core.config import get_settings
from app.telemetry.readings import as_utc, canonicalize_value


def new_device_secret() -> tuple[str, str, str]:
    key_id = f"dev_{secrets.token_hex(12)}"
    secret = secrets.token_urlsafe(32)
    secret_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    return key_id, secret, secret_hash


def verify_device_secret(candidate: str, stored_hash: str) -> bool:
    candidate_hash = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    return hmac.compare_digest(candidate_hash, stored_hash)


def authenticate_device_token(database, token: str) -> dict[str, Any] | None:
    if len(token) > 256:
        return None
    key_id, separator, secret = token.partition(".")
    if not separator or not key_id or not secret:
        return None
    now = datetime.now(UTC)
    record = database.device_credentials.find_one(
        {
            "key_id": key_id,
            "revoked_at": None,
            "expires_at": {"$gt": now},
        }
    )
    if record is None or not verify_device_secret(secret, record["secret_hash"]):
        return None
    updated = database.device_credentials.update_one(
        {
            "_id": record["_id"],
            "organization_id": record["organization_id"],
            "revoked_at": None,
        },
        {"$set": {"last_used_at": now, "updated_at": now}},
    )
    if updated.matched_count != 1:
        return None
    return record


def sensor_quantity(sensor: dict[str, Any]) -> str:
    quantity, _, _ = canonicalize_value(
        sensor["measurement_type"],
        sensor["unit"],
        1,
        registered_unit=sensor["unit"],
    )
    return quantity


def update_sensor_receipt(
    database,
    *,
    organization_id: ObjectId,
    sensor: dict[str, Any],
    event_time_utc: datetime,
    received_at_utc: datetime,
) -> None:
    stale_after_seconds = sensor.get("stale_after_seconds")
    if stale_after_seconds is None:
        stale_after_seconds = max(
            1,
            int(
                sensor["expected_reporting_interval_seconds"]
                * get_settings().sensor_stale_multiplier
            ),
        )
    database.sensor_states.update_one(
        {
            "organization_id": organization_id,
            "sensor_id": sensor["_id"],
        },
        {
            "$setOnInsert": {
                "organization_id": organization_id,
                "sensor_id": sensor["_id"],
                "stale_after_seconds": stale_after_seconds,
                "created_at": received_at_utc,
            },
            "$max": {
                "last_seen_at": received_at_utc,
                "last_event_time": event_time_utc,
            },
            "$set": {"updated_at": received_at_utc},
        },
        upsert=True,
    )


def sensor_state_payload(
    database,
    *,
    organization_id: ObjectId,
    sensor: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    now_utc = (now or datetime.now(UTC)).astimezone(UTC)
    stale_after = sensor.get("stale_after_seconds")
    if stale_after is None:
        stale_after = max(
            1,
            int(
                sensor["expected_reporting_interval_seconds"]
                * get_settings().sensor_stale_multiplier
            ),
        )
    state = database.sensor_states.find_one(
        {"organization_id": organization_id, "sensor_id": sensor["_id"]}
    )
    if state is None:
        return {
            "sensor_id": str(sensor["_id"]),
            "connection_state": "never_seen",
            "stale": None,
            "last_seen_at": None,
            "last_event_time": None,
            "stale_after_seconds": stale_after,
            "source": "measured",
        }
    stale_after = state.get("stale_after_seconds", stale_after)
    last_seen = as_utc(state["last_seen_at"]) if state.get("last_seen_at") else None
    last_event_time = (
        as_utc(state["last_event_time"])
        if state.get("last_event_time")
        else None
    )
    if last_seen is None:
        connection_state = "never_seen"
        stale = None
    else:
        connection_state = (
            "stale"
            if (now_utc - last_seen).total_seconds() > state["stale_after_seconds"]
            else "fresh"
        )
        stale = connection_state == "stale"
    return {
        "sensor_id": str(sensor["_id"]),
        "connection_state": connection_state,
        "stale": stale,
        "last_seen_at": last_seen.isoformat() if last_seen else None,
        "last_event_time": (
            last_event_time.isoformat() if last_event_time else None
        ),
        "stale_after_seconds": state["stale_after_seconds"],
        "source": "measured",
    }


def audit_device_event(
    database,
    *,
    organization_id: ObjectId,
    event: str,
    credential_id: ObjectId | None,
    actor_user_id: ObjectId | None,
    created_at: datetime | None = None,
    counts: dict[str, int] | None = None,
    session=None,
) -> None:
    record: dict[str, Any] = {
        "organization_id": organization_id,
        "event": event,
        "created_at": created_at or datetime.now(UTC),
    }
    if credential_id is not None:
        record["credential_id"] = credential_id
    if actor_user_id is not None:
        record["actor_user_id"] = actor_user_id
    if counts is not None:
        record["counts"] = counts
    database.device_audit_events.insert_one(record, session=session)


def default_credential_expiry(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) + timedelta(days=90)
