import csv
import hashlib
import io
import logging
import math
import tempfile
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from bson import ObjectId
from botocore.exceptions import BotoCoreError, ClientError
from pymongo.errors import BulkWriteError
from bson.errors import InvalidId

from app.core.config import get_settings
from app.db.client import get_database, get_mongo_client
from app.telemetry.readings import (
    NormalizedReadingV1,
    canonicalize_value,
    make_event_key,
    parse_event_time,
)
from app.telemetry.csv_format import detect_csv_dialect
from app.telemetry.repository import bulk_upsert_readings
from app.telemetry.storage import get_storage_client
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)
LEASE_SECONDS = 15 * 60


class _PrefixedStream(io.RawIOBase):
    def __init__(self, prefix: bytes, stream) -> None:
        self._prefix = io.BytesIO(prefix)
        self._stream = stream

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        prefix = self._prefix.read(len(buffer))
        if prefix:
            buffer[: len(prefix)] = prefix
            return len(prefix)
        chunk = self._stream.read(len(buffer))
        if not chunk:
            return 0
        buffer[: len(chunk)] = chunk
        return len(chunk)


def _failure_code(message: str) -> str:
    return message.split(":", 1)[0] if ":" in message else "INVALID_ROW"


def _cell(row: list[str], headers: list[str], column: str | None) -> str | None:
    if column is None:
        return None
    return row[headers.index(column)].strip()


def _sensor_for_row(database, organization_id: ObjectId, identity: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        object_id = ObjectId(identity)
    except InvalidId:
        object_id = None
    alternatives: list[dict[str, Any]] = [{"identity": identity}]
    if object_id is not None:
        alternatives.append({"_id": object_id})
    query = {"organization_id": organization_id, "$or": alternatives}
    sensor = database.sensors.find_one({**query, "archived_at": None})
    if sensor is not None:
        return sensor, None
    if database.sensors.find_one(query) is not None:
        return None, "SENSOR_NOT_PERMITTED: The referenced sensor is archived."
    return None, "UNKNOWN_SENSOR: No sensor with this ID is available in this organization."


def _process_row(
    *,
    row: list[str],
    row_number: int,
    headers: list[str],
    mapping: dict[str, Any],
    import_record: dict[str, Any],
    database,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if len(row) != len(headers):
        return {
            "row_number": row_number,
            "code": "MALFORMED_ROW",
            "message": "Column count does not match the CSV header.",
        }, None

    try:
        timestamp_value = _cell(row, headers, mapping["timestamp_column"])
        timezone_name = mapping["timestamp_timezone"]
        event_time = parse_event_time(
            timestamp_value or "",
            None if timezone_name == "value" else timezone_name,
        )
    except ValueError as error:
        return {"row_number": row_number, "code": _failure_code(str(error)), "message": str(error)}, None

    value_raw = _cell(row, headers, mapping["value_column"])
    try:
        value = float(value_raw or "")
    except ValueError:
        return {
            "row_number": row_number,
            "code": "NON_NUMERIC_VALUE",
            "message": "Value must be a number.",
        }, None
    if not math.isfinite(value):
        return {
            "row_number": row_number,
            "code": "NON_FINITE_VALUE",
            "message": "Value must be finite.",
        }, None

    sensor_id_raw = mapping.get("fixed_sensor_id") or _cell(
        row, headers, mapping.get("sensor_column")
    )
    if not sensor_id_raw:
        return {
            "row_number": row_number,
            "code": "UNKNOWN_SENSOR",
            "message": "Sensor ID is blank.",
        }, None
    sensor, sensor_error = _sensor_for_row(
        database, import_record["organization_id"], sensor_id_raw
    )
    if sensor_error:
        return {
            "row_number": row_number,
            "code": _failure_code(sensor_error),
            "message": sensor_error,
        }, None
    machine = database.machines.find_one(
        {
            "_id": sensor["machine_id"],
            "organization_id": import_record["organization_id"],
            "archived_at": None,
        }
    )
    if machine is None:
        return {
            "row_number": row_number,
            "code": "SENSOR_NOT_PERMITTED",
            "message": "The sensor's machine is archived or unavailable.",
        }, None

    unit = mapping.get("fixed_unit") or _cell(row, headers, mapping.get("unit_column"))
    if not unit:
        return {
            "row_number": row_number,
            "code": "INCOMPATIBLE_UNIT",
            "message": "Unit is blank; provide a unit column value or fixed unit.",
        }, None
    calibration = sensor.get("calibration", {})
    try:
        quantity, canonical_unit, normalized_value = canonicalize_value(
            sensor["measurement_type"],
            unit,
            value,
            registered_unit=sensor["unit"],
            calibration_scale=calibration.get("scale"),
            calibration_offset=calibration.get("offset"),
        )
    except ValueError as error:
        return {
            "row_number": row_number,
            "code": _failure_code(str(error)),
            "message": str(error),
        }, None

    source_event_id = _cell(
        row, headers, mapping.get("source_event_id_column")
    ) or None
    event_key = make_event_key(
        str(import_record["organization_id"]),
        str(sensor["_id"]),
        quantity,
        event_time,
        source_event_id=source_event_id,
    )
    received_at = datetime.now(UTC)
    reading = NormalizedReadingV1(
        organization_id=str(import_record["organization_id"]),
        sensor_id=str(sensor["_id"]),
        machine_id=str(machine["_id"]),
        quantity=quantity,
        unit=canonical_unit,
        value=normalized_value,
        event_time_utc=event_time,
        received_at_utc=received_at,
        source="csv_import",
        source_ref=str(import_record["_id"]),
        quality="good",
        event_key=event_key,
    )
    reading_document = reading.model_dump(mode="python")
    reading_document["organization_id"] = import_record["organization_id"]
    reading_document["sensor_id"] = sensor["_id"]
    reading_document["machine_id"] = machine["_id"]
    return (
        {"row_number": row_number, "code": "PENDING", "message": "", "event_key": event_key},
        reading_document,
    )


def _read_counts(database, import_record: dict[str, Any]) -> tuple[dict[str, int], dict[str, int]]:
    statuses = list(
        database.sensor_import_rows.aggregate(
            [
                {
                    "$match": {
                        "organization_id": import_record["organization_id"],
                        "import_id": import_record["_id"],
                    }
                },
                {"$group": {"_id": "$code", "count": {"$sum": 1}}},
            ]
        )
    )
    code_counts = {item["_id"]: item["count"] for item in statuses}
    inserted = code_counts.get("INSERTED", 0)
    duplicates = code_counts.get("DUPLICATE_IN_FILE", 0) + code_counts.get(
        "DUPLICATE_EXISTING", 0
    )
    rejected = sum(
        count
        for code, count in code_counts.items()
        if code not in {"INSERTED", "DUPLICATE_IN_FILE", "DUPLICATE_EXISTING"}
    )
    counts = {
        "total": sum(code_counts.values()),
        "inserted": inserted,
        "duplicates": duplicates,
        "rejected": rejected,
    }
    rejected_codes = {
        code: count
        for code, count in code_counts.items()
        if code not in {"INSERTED", "DUPLICATE_IN_FILE", "DUPLICATE_EXISTING"}
    }
    return counts, rejected_codes


def _save_batch(
    database,
    import_record: dict[str, Any],
    pending: list[tuple[dict[str, Any], dict[str, Any] | None, list[str]]],
    session,
) -> None:
    outcomes: list[dict[str, Any]] = []
    readings = [reading for _, reading, _ in pending if reading]
    reading_statuses = bulk_upsert_readings(database, readings, session=session)
    for outcome, reading, _raw_row in pending:
        if reading is None:
            outcomes.append(outcome)
        elif reading_statuses[reading["event_key"]] == "duplicate":
            outcomes.append(
                {
                    "row_number": outcome["row_number"],
                    "code": "DUPLICATE_EXISTING",
                    "message": "An identical event key already exists; the first stored reading is retained.",
                    "event_key": reading["event_key"],
                }
            )
        else:
            outcomes.append(
                {
                    "row_number": outcome["row_number"],
                    "code": "INSERTED",
                    "message": "",
                    "event_key": outcome["event_key"],
                }
            )
    if outcomes:
        for item in outcomes:
            item.update(
                {
                    "organization_id": import_record["organization_id"],
                    "import_id": import_record["_id"],
                    "created_at": datetime.now(UTC),
                }
            )
        database.sensor_import_rows.insert_many(outcomes, ordered=True, session=session)


@celery_app.task(
    bind=True,
    name="realityloop.sensor_imports.process",
    acks_late=True,
    reject_on_worker_lost=True,
)
def process_sensor_import(self, import_id: str) -> dict[str, Any]:
    try:
        object_id = ObjectId(import_id)
    except InvalidId as error:
        raise ValueError("Invalid sensor import ID.") from error
    database = get_database()
    now = datetime.now(UTC)
    import_record = database.sensor_imports.find_one_and_update(
        {
            "_id": object_id,
            "$or": [
                {"status": "queued"},
                {
                    "status": "processing",
                    "lease_until": {"$lt": now},
                },
                {"status": "processing", "lease_until": {"$exists": False}},
            ],
        },
        {
            "$set": {
                "status": "processing",
                "updated_at": now,
                "lease_until": now + timedelta(seconds=LEASE_SECONDS),
            },
            "$inc": {"worker_attempt_count": 1},
        },
        return_document=True,
    )
    if import_record is None:
        existing = database.sensor_imports.find_one({"_id": object_id})
        if existing is None:
            raise ValueError("Sensor import record was not found.")
        return {"status": existing["status"], "import_id": import_id}

    settings = get_settings()
    error_buffer = tempfile.SpooledTemporaryFile(mode="w+", encoding="utf-8", newline="")
    source_body = None
    source_buffer = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
    try:
        storage, bucket = get_storage_client()
        response = storage.get_object(
            Bucket=bucket, Key=import_record["source_object_key"]
        )
        source = response["Body"]
        source_body = source
        source_digest = hashlib.sha256()
        source_size = 0
        while chunk := source.read(64 * 1024):
            source_size += len(chunk)
            if source_size > settings.sensor_import_max_file_bytes:
                raise ValueError(
                    f"Stored source exceeds the configured {settings.sensor_import_max_file_bytes}-byte limit."
                )
            source_digest.update(chunk)
            source_buffer.write(chunk)
        if source_digest.hexdigest() != import_record["source_checksum"]:
            raise ValueError(
                "SOURCE_CHECKSUM_MISMATCH: Stored source file does not match the recorded SHA-256 checksum."
            )
        source_buffer.seek(0)
        sample = source_buffer.read(8192)
        dialect = detect_csv_dialect(sample.decode("utf-8-sig"))
        raw_stream = io.BufferedReader(_PrefixedStream(sample, source_buffer))
        text_stream = io.TextIOWrapper(raw_stream, encoding="utf-8-sig", newline="")
        reader = csv.reader(text_stream, dialect)
        try:
            headers = [header.strip() for header in next(reader)]
        except (csv.Error, StopIteration) as error:
            raise ValueError("CSV must contain a header row.") from error
        if not headers or any(not header for header in headers) or len(set(headers)) != len(headers):
            raise ValueError("CSV headers must be non-empty and unique.")
        mapping = import_record["mapping"]
        candidate_columns = [
            mapping.get("timestamp_column"),
            mapping.get("value_column"),
            mapping.get("unit_column"),
            mapping.get("sensor_column"),
            mapping.get("source_event_id_column"),
        ]
        if any(column and column not in headers for column in candidate_columns):
            raise ValueError("Confirmed mapping refers to a column missing from the source file.")
        if (mapping.get("fixed_unit") is None) == (mapping.get("unit_column") is None):
            raise ValueError("Confirmed mapping must choose exactly one unit source.")
        if (mapping.get("fixed_sensor_id") is None) == (mapping.get("sensor_column") is None):
            raise ValueError("Confirmed mapping must choose exactly one sensor source.")
        if mapping.get("timestamp_timezone") != "value":
            ZoneInfo(mapping["timestamp_timezone"])

        error_writer = csv.writer(error_buffer)
        error_writer.writerow(["row_number", "code", "message", *headers])
        error_file_count = 0
        cancellation_observed = False
        seen_event_keys: set[str] = set()
        pending: list[tuple[dict[str, Any], dict[str, Any] | None, list[str]]] = []
        total_rows = 0
        client = get_mongo_client()
        with client.start_session() as session:
            for row_number, row in enumerate(reader, start=2):
                total_rows += 1
                if total_rows > settings.sensor_import_max_rows:
                    raise ValueError(
                        f"CSV exceeds configured maximum of {settings.sensor_import_max_rows} data rows."
                    )
                previous = database.sensor_import_rows.find_one(
                    {
                        "organization_id": import_record["organization_id"],
                        "import_id": object_id,
                        "row_number": row_number,
                    }
                )
                if previous:
                    if previous.get("event_key"):
                        seen_event_keys.add(previous["event_key"])
                    if previous["code"] not in {
                        "INSERTED",
                        "DUPLICATE_IN_FILE",
                        "DUPLICATE_EXISTING",
                    }:
                        error_writer.writerow(
                            [row_number, previous["code"], previous["message"], *row]
                        )
                        error_file_count += 1
                    continue

                outcome, reading = _process_row(
                    row=row,
                    row_number=row_number,
                    headers=headers,
                    mapping=mapping,
                    import_record=import_record,
                    database=database,
                )
                if reading and reading["event_key"] in seen_event_keys:
                    outcome = {
                        "row_number": row_number,
                        "code": "DUPLICATE_IN_FILE",
                        "message": "This event key already appeared earlier in the same file.",
                        "event_key": reading["event_key"],
                    }
                    reading = None
                elif reading:
                    seen_event_keys.add(reading["event_key"])
                if outcome["code"] not in {"PENDING", "INSERTED", "DUPLICATE_IN_FILE", "DUPLICATE_EXISTING"}:
                    error_writer.writerow(
                        [row_number, outcome["code"], outcome["message"], *row]
                    )
                    error_file_count += 1
                pending.append((outcome, reading, row))
                if len(pending) >= settings.sensor_import_batch_size:
                    if database.sensor_imports.find_one(
                        {"_id": object_id, "cancel_requested": True}
                    ):
                        cancellation_observed = True
                        break
                    session.with_transaction(
                        lambda txn: _save_batch(
                            database, import_record, pending, txn
                        )
                    )
                    pending.clear()
                    counts, rejected_codes = _read_counts(database, import_record)
                    database.sensor_imports.update_one(
                        {"_id": object_id, "organization_id": import_record["organization_id"]},
                        {
                            "$set": {
                                "counts": counts,
                                "rejected_by_code": rejected_codes,
                                "progress_rows": counts["total"],
                                "updated_at": datetime.now(UTC),
                                "lease_until": datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS),
                            }
                        },
                    )
            if pending:
                session.with_transaction(
                    lambda txn: _save_batch(database, import_record, pending, txn)
                )

        cancelled = cancellation_observed or database.sensor_imports.find_one(
            {"_id": object_id, "cancel_requested": True}
        )
        counts, rejected_codes = _read_counts(database, import_record)
        error_object_key = None
        if error_file_count:
            error_buffer.seek(0)
            error_object_key = f"sensor-imports/{import_record['organization_id']}/{object_id}/errors.csv"
            storage.put_object(
                Bucket=bucket,
                Key=error_object_key,
                Body=error_buffer.read().encode("utf-8"),
                ContentType="text/csv; charset=utf-8",
                ServerSideEncryption="AES256",
                Metadata={"import-id": str(object_id)},
            )
        terminal_status = (
            "cancelled"
            if cancelled
            else "completed_with_errors"
            if counts["rejected"]
            else "completed"
        )
        database.sensor_imports.update_one(
            {"_id": object_id, "organization_id": import_record["organization_id"]},
            {
                "$set": {
                    "status": terminal_status,
                    "counts": counts,
                    "rejected_by_code": rejected_codes,
                    "progress_rows": counts["total"],
                    "error_object_key": error_object_key,
                    "error_summary": (
                        f"{counts['rejected']} row(s) were rejected; download the private errors CSV."
                        if counts["rejected"]
                        else None
                    ),
                    "updated_at": datetime.now(UTC),
                    "lease_until": None,
                }
            },
        )
        return {"status": terminal_status, "import_id": import_id, "counts": counts}
    except (BotoCoreError, ClientError, UnicodeDecodeError, csv.Error, BulkWriteError, ValueError) as error:
        counts, rejected_codes = _read_counts(database, import_record)
        database.sensor_imports.update_one(
            {"_id": object_id, "organization_id": import_record["organization_id"]},
            {
                "$set": {
                    "status": "failed",
                    "error_summary": str(error)[:500],
                    "counts": counts,
                    "rejected_by_code": rejected_codes,
                    "progress_rows": counts["total"],
                    "updated_at": datetime.now(UTC),
                    "lease_until": None,
                }
            },
        )
        logger.error(
            "Sensor import worker failed",
            extra={"sensor_import_id": import_id, "failure_type": type(error).__name__},
        )
        raise
    finally:
        error_buffer.close()
        source_buffer.close()
        if source_body is not None:
            source_body.close()
