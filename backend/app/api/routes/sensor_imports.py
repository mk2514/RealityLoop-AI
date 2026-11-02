import csv
import hashlib
import io
import logging
import math
import re
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bson import ObjectId
from bson.errors import InvalidId
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from kombu.exceptions import OperationalError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from pymongo.errors import DuplicateKeyError

from app.api.routes.auth import (
    Principal,
    get_current_principal,
    require_csrf,
    require_roles,
)
from app.core.config import get_settings
from app.db.client import get_database
from app.telemetry.csv_format import DELIMITERS, detect_csv_dialect
from app.telemetry.readings import as_utc
from app.telemetry.storage import PrivateStorageUnavailable, get_storage_client
from app.worker.sensor_imports import process_sensor_import
from app.worker.photo_analysis import process_historical_analysis_job

router = APIRouter(dependencies=[Depends(require_csrf)])
logger = logging.getLogger(__name__)
IMPORT_ROLES = ("owner", "administrator", "engineer")
CSV_CONTENT_TYPES = {"text/csv", "application/csv", "application/vnd.ms-excel"}
SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class HistoricalAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_summary: dict[str, Any] = Field(max_length=20)

    @field_validator("evidence_summary")
    @classmethod
    def bounded_evidence(cls, value: dict[str, Any]) -> dict[str, Any]:
        encoded = str(value)
        if len(encoded) > 12_000:
            raise ValueError("The evidence summary is too large; do not send raw CSV rows.")
        return value


class ImportMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    timestamp_column: str = Field(min_length=1, max_length=128)
    timestamp_timezone: str = Field(min_length=1, max_length=128)
    value_column: str = Field(min_length=1, max_length=128)
    fixed_unit: str | None = Field(default=None, max_length=32)
    unit_column: str | None = Field(default=None, max_length=128)
    fixed_sensor_id: str | None = Field(default=None, max_length=64)
    sensor_column: str | None = Field(default=None, max_length=128)
    source_event_id_column: str | None = Field(default=None, max_length=128)

    @field_validator(
        "fixed_unit",
        "unit_column",
        "fixed_sensor_id",
        "sensor_column",
        "source_event_id_column",
        mode="before",
    )
    @classmethod
    def normalize_empty_optional_fields(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("timestamp_timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        if value == "value":
            return value
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Choose 'value' or a valid IANA timezone.") from error
        return value

    @model_validator(mode="after")
    def validate_choice_pairs(self):
        if bool(self.fixed_unit) == bool(self.unit_column):
            raise ValueError("Choose exactly one of fixed_unit or unit_column.")
        if bool(self.fixed_sensor_id) == bool(self.sensor_column):
            raise ValueError("Choose exactly one of fixed_sensor_id or sensor_column.")
        return self


def _object_id(raw_id: str) -> ObjectId:
    try:
        return ObjectId(raw_id)
    except InvalidId as error:
        raise HTTPException(status_code=404, detail="Sensor or import was not found.") from error


def _sensor(sensor_id: str, principal: Principal) -> dict[str, Any]:
    result = get_database().sensors.find_one(
        {
            "_id": _object_id(sensor_id),
            "organization_id": principal.organization_id,
            "archived_at": None,
        }
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Sensor was not found in this workspace.")
    return result


async def _read_csv_body(request: Request) -> bytes:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type not in CSV_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Upload a UTF-8 CSV file.")
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise HTTPException(status_code=415, detail="Compressed uploads are not supported.")
    settings = get_settings()
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > settings.sensor_import_max_file_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"CSV exceeds the {settings.sensor_import_max_file_bytes}-byte upload limit.",
                )
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header.") from error
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > settings.sensor_import_max_file_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"CSV exceeds the {settings.sensor_import_max_file_bytes}-byte upload limit.",
            )
        chunks.append(chunk)
    if not chunks or total == 0:
        raise HTTPException(status_code=400, detail="The CSV file is empty.")
    content = b"".join(chunks)
    try:
        content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise HTTPException(status_code=400, detail="CSV must use UTF-8 encoding.") from error
    return content


def _parse_csv(
    content: bytes, max_rows: int
) -> tuple[list[str], list[list[str]], str]:
    text = content.decode("utf-8-sig")
    try:
        dialect = detect_csv_dialect(text[:8192])
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error
    if dialect.delimiter not in DELIMITERS:
        raise HTTPException(status_code=400, detail="CSV delimiter is not supported.")
    try:
        reader = csv.reader(io.StringIO(text, newline=""), dialect)
        headers = [header.strip() for header in next(reader)]
    except (csv.Error, StopIteration) as error:
        raise HTTPException(status_code=400, detail="CSV must contain a header row.") from error
    if not headers or any(not item for item in headers) or len(set(headers)) != len(headers):
        raise HTTPException(
            status_code=400,
            detail="CSV headers must be non-empty and unique after trimming whitespace.",
        )
    rows = []
    try:
        for row in reader:
            if len(rows) >= max_rows:
                raise HTTPException(
                    status_code=413,
                    detail=f"CSV exceeds the {max_rows}-row limit.",
                )
            rows.append(row)
    except csv.Error as error:
        raise HTTPException(status_code=400, detail="CSV contains malformed quoting.") from error
    return headers, rows, dialect.delimiter


def _mapping_from_header(request: Request, headers: list[str], sensor: dict) -> ImportMapping:
    raw_mapping = request.headers.get("x-import-mapping", "")
    if not raw_mapping or len(raw_mapping) > 4096:
        raise HTTPException(status_code=400, detail="Provide the confirmed CSV column mapping.")
    try:
        mapping = ImportMapping.model_validate_json(raw_mapping)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail="The confirmed CSV mapping is invalid.") from error
    mapped_columns = [
        mapping.timestamp_column,
        mapping.value_column,
        mapping.unit_column,
        mapping.sensor_column,
        mapping.source_event_id_column,
    ]
    missing = [column for column in mapped_columns if column and column not in headers]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Mapped CSV columns are missing: {', '.join(missing)}.",
        )
    if mapping.fixed_sensor_id and mapping.fixed_sensor_id != str(sensor["_id"]):
        raise HTTPException(
            status_code=422,
            detail="fixed_sensor_id must match the selected sensor context.",
        )
    return mapping


def _sample_result(
    rows: list[list[str]],
    headers: list[str],
    mapping: ImportMapping | None,
    limit: int,
) -> list[dict[str, Any]]:
    sample: list[dict[str, Any]] = []
    for row_number, row in enumerate(rows[:limit], start=2):
        result: dict[str, Any] = {
            "row_number": row_number,
            "values": row[: len(headers)],
            "parse_status": "mapping_required",
            "warnings": [],
        }
        if len(row) != len(headers):
            result["parse_status"] = "rejected"
            result["warnings"].append("MALFORMED_ROW: Column count does not match the header.")
        elif mapping:
            values = dict(zip(headers, row, strict=True))
            try:
                from app.telemetry.readings import parse_event_time

                parse_event_time(
                    values[mapping.timestamp_column],
                    None if mapping.timestamp_timezone == "value" else mapping.timestamp_timezone,
                )
                parsed_value = float(values[mapping.value_column])
                if not math.isfinite(parsed_value):
                    raise ValueError("NON_FINITE_VALUE: Value must be finite.")
                result["parse_status"] = "valid"
            except (ValueError, KeyError) as error:
                result["parse_status"] = "review"
                result["warnings"].append(str(error))
        sample.append(result)
    return sample


def _serialize_import(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "import_id": str(record["_id"]),
        "sensor_id": str(record["sensor_id"]),
        "machine_id": str(record["machine_id"]),
        "source_checksum": record["source_checksum"],
        "status": record["status"],
        "created_at": as_utc(record["created_at"]).isoformat(),
        "updated_at": as_utc(record["updated_at"]).isoformat(),
        "counts": record.get("counts", {"total": 0, "inserted": 0, "duplicates": 0, "rejected": 0}),
        "rejected_by_code": record.get("rejected_by_code", {}),
        "error_summary": record.get("error_summary"),
        "identical_source_imports": record.get("identical_source_imports", 0),
        "worker_attempt_count": record.get("worker_attempt_count", 0),
        "progress_rows": record.get("progress_rows", 0),
        "has_error_file": bool(record.get("error_object_key")),
    }


@router.post("/sensor-imports/preview")
async def preview_sensor_import(
    request: Request,
    sensor_id: str = Query(min_length=1, max_length=64),
    principal: Principal = Depends(require_roles(*IMPORT_ROLES)),
) -> dict[str, Any]:
    sensor = _sensor(sensor_id, principal)
    content = await _read_csv_body(request)
    settings = get_settings()
    headers, rows, delimiter = _parse_csv(content, settings.sensor_import_max_rows)
    mapping = _mapping_from_header(request, headers, sensor) if request.headers.get("x-import-mapping") else None
    return {
        "headers": headers,
        "delimiter": "TAB" if delimiter == "\t" else delimiter,
        "rows_total": len(rows),
        "sample_rows": _sample_result(rows, headers, mapping, settings.sensor_import_preview_rows),
        "mapping_confirmed": mapping is not None,
        "warnings": [] if mapping else ["Select columns and timezone, then preview again to validate the mapping."],
        "sensor": {
            "id": str(sensor["_id"]),
            "name": sensor["name"],
            "measurement_type": sensor["measurement_type"],
            "registered_unit": sensor["unit"],
        },
    }


@router.post("/sensor-imports", status_code=202)
async def create_sensor_import(
    request: Request,
    sensor_id: str = Query(min_length=1, max_length=64),
    principal: Principal = Depends(require_roles(*IMPORT_ROLES)),
) -> dict[str, Any]:
    settings = get_settings()
    sensor = _sensor(sensor_id, principal)
    content = await _read_csv_body(request)
    headers, rows, _delimiter = _parse_csv(content, settings.sensor_import_max_rows)
    mapping = _mapping_from_header(request, headers, sensor)
    checksum = hashlib.sha256(content).hexdigest()
    identical_count = get_database().sensor_imports.count_documents(
        {
            "organization_id": principal.organization_id,
            "sensor_id": sensor["_id"],
            "source_checksum": checksum,
        }
    )
    import_id = ObjectId()
    object_key = f"sensor-imports/{principal.organization_id}/{import_id}/source.csv"
    component = get_database().components.find_one(
        {
            "_id": sensor["component_id"],
            "organization_id": principal.organization_id,
            "archived_at": None,
        }
    )
    if component is None:
        raise HTTPException(status_code=409, detail="The sensor's component is archived or unavailable.")
    try:
        storage, bucket = get_storage_client()
        storage.put_object(
            Bucket=bucket,
            Key=object_key,
            Body=content,
            ContentType="text/csv; charset=utf-8",
            ServerSideEncryption="AES256",
            Metadata={"sha256": checksum, "import-id": str(import_id)},
        )
    except PrivateStorageUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (BotoCoreError, ClientError) as error:
        logger.error("Private sensor import upload failed", extra={"sensor_import_id": str(import_id)})
        raise HTTPException(status_code=503, detail="Private file storage is unavailable; retry the upload.") from error

    now = datetime.now(UTC)
    record = {
        "_id": import_id,
        "organization_id": principal.organization_id,
        "uploader_id": principal.user_id,
        "factory_id": sensor["factory_id"],
        "line_id": sensor["line_id"],
        "machine_id": sensor["machine_id"],
        "component_id": sensor["component_id"],
        "sensor_id": sensor["_id"],
        "source_object_key": object_key,
        "source_checksum": checksum,
        "original_filename": SAFE_FILENAME.sub("_", request.headers.get("x-file-name", "sensor-data.csv"))[:180],
        "mapping": mapping.model_dump(),
        "status": "queued",
        "schema_version": 1,
        "created_at": now,
        "updated_at": now,
        "counts": {"total": 0, "inserted": 0, "duplicates": 0, "rejected": 0},
        "rejected_by_code": {},
        "error_summary": None,
        "error_object_key": None,
        "worker_attempt_count": 0,
        "progress_rows": 0,
        "cancel_requested": False,
        "identical_source_imports": identical_count,
        "dispatch_token": secrets.token_hex(16),
    }
    try:
        get_database().sensor_imports.insert_one(record)
    except DuplicateKeyError as error:
        raise HTTPException(status_code=409, detail="This import could not be recorded; retry once.") from error

    try:
        process_sensor_import.delay(str(import_id))
    except OperationalError as error:
        get_database().sensor_imports.update_one(
            {"_id": import_id, "organization_id": principal.organization_id, "status": "queued"},
            {
                "$set": {
                    "status": "failed",
                    "error_summary": "The background worker could not be reached. Retry this import.",
                    "updated_at": datetime.now(UTC),
                }
            },
        )
        logger.error("Could not dispatch sensor import", extra={"sensor_import_id": str(import_id), "exception_type": type(error).__name__})
        raise HTTPException(
            status_code=503,
            detail=f"The background worker is unavailable. Import {import_id} was recorded as failed; retry it from import history.",
        ) from error
    return {"import": _serialize_import(record)}


@router.get("/sensor-imports")
def list_sensor_imports(
    sensor_id: str | None = Query(default=None, max_length=64),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    query: dict[str, Any] = {"organization_id": principal.organization_id}
    if sensor_id:
        sensor = _sensor(sensor_id, principal)
        query["sensor_id"] = sensor["_id"]
    records = list(
        get_database().sensor_imports.find(query).sort("created_at", -1).limit(100)
    )
    return {"imports": [_serialize_import(record) for record in records]}


@router.get("/sensor-imports/{import_id}")
def get_sensor_import(
    import_id: str,
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    record = get_database().sensor_imports.find_one(
        {"_id": _object_id(import_id), "organization_id": principal.organization_id}
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Import was not found.")
    return {"import": _serialize_import(record)}


@router.post("/historical-replay/analysis", status_code=202)
def create_historical_analysis(
    payload: HistoricalAnalysisRequest,
    principal: Principal = Depends(require_roles(*IMPORT_ROLES)),
) -> dict[str, Any]:
    settings = get_settings()
    job_id = ObjectId()
    now = datetime.now(UTC)
    job = {
        "_id": job_id,
        "organization_id": principal.organization_id,
        "created_by": principal.user_id,
        "status": "queued",
        "attempt_count": 0,
        "provider": "gemini" if settings.gemini_api_key else "unconfigured",
        "evidence_summary": payload.evidence_summary,
        "created_at": now,
        "updated_at": now,
    }
    get_database().historical_analysis_jobs.insert_one(job)
    if not settings.gemini_api_key:
        get_database().historical_analysis_jobs.update_one(
            {"_id": job_id, "organization_id": principal.organization_id},
            {"$set": {"status": "missing_key", "error": {"code": "missing_key", "message": "Gemini key is not configured for the worker."}, "updated_at": now}},
        )
        return {"job_id": str(job_id), "status": "missing_key"}
    try:
        process_historical_analysis_job.delay(str(job_id))
    except OperationalError:
        get_database().historical_analysis_jobs.update_one(
            {"_id": job_id, "organization_id": principal.organization_id},
            {"$set": {"status": "provider_outage", "error": {"code": "provider_outage", "message": "The analysis worker is unavailable."}, "updated_at": datetime.now(UTC)}},
        )
        return {"job_id": str(job_id), "status": "provider_outage"}
    return {"job_id": str(job_id), "status": "queued"}


@router.get("/historical-replay/analysis/{job_id}")
def get_historical_analysis(
    job_id: str,
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    try:
        object_id = ObjectId(job_id)
    except InvalidId as error:
        raise HTTPException(status_code=404, detail="Historical analysis job was not found.") from error
    job = get_database().historical_analysis_jobs.find_one(
        {"_id": object_id, "organization_id": principal.organization_id}
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Historical analysis job was not found.")
    return {
        "job_id": str(job["_id"]),
        "status": job["status"],
        "result": job.get("result"),
        "error": job.get("error"),
    }


@router.get("/sensor-imports/{import_id}/errors")
def get_sensor_import_errors(
    import_id: str,
    principal: Principal = Depends(get_current_principal),
) -> dict[str, str]:
    record = get_database().sensor_imports.find_one(
        {"_id": _object_id(import_id), "organization_id": principal.organization_id}
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Import was not found.")
    if not record.get("error_object_key"):
        raise HTTPException(status_code=404, detail="This import has no rejected-row file.")
    try:
        storage, bucket = get_storage_client()
        url = storage.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": bucket,
                "Key": record["error_object_key"],
                "ResponseContentType": "text/csv; charset=utf-8",
                "ResponseContentDisposition": 'attachment; filename="sensor-import-errors.csv"',
            },
            ExpiresIn=get_settings().sensor_import_error_url_ttl_seconds,
        )
    except PrivateStorageUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (BotoCoreError, ClientError) as error:
        logger.error("Could not sign sensor error report", extra={"sensor_import_id": import_id})
        raise HTTPException(status_code=503, detail="Private file storage is unavailable.") from error
    return {"download_url": url, "expires_in_seconds": get_settings().sensor_import_error_url_ttl_seconds}


@router.post("/sensor-imports/{import_id}/cancel")
def cancel_sensor_import(
    import_id: str,
    principal: Principal = Depends(require_roles(*IMPORT_ROLES)),
) -> dict[str, Any]:
    database = get_database()
    record = database.sensor_imports.find_one(
        {"_id": _object_id(import_id), "organization_id": principal.organization_id}
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Import was not found.")
    if record["status"] == "queued":
        database.sensor_imports.update_one(
            {"_id": record["_id"], "organization_id": principal.organization_id, "status": "queued"},
            {"$set": {"status": "cancelled", "cancel_requested": True, "updated_at": datetime.now(UTC)}},
        )
    elif record["status"] == "processing":
        database.sensor_imports.update_one(
            {"_id": record["_id"], "organization_id": principal.organization_id, "status": "processing"},
            {"$set": {"cancel_requested": True, "updated_at": datetime.now(UTC)}},
        )
    else:
        raise HTTPException(status_code=409, detail="Only queued or processing imports can be cancelled.")
    updated = database.sensor_imports.find_one(
        {"_id": record["_id"], "organization_id": principal.organization_id}
    )
    return {"import": _serialize_import(updated)}


@router.post("/sensor-imports/{import_id}/retry", status_code=202)
def retry_sensor_import(
    import_id: str,
    principal: Principal = Depends(require_roles(*IMPORT_ROLES)),
) -> dict[str, Any]:
    database = get_database()
    object_id = _object_id(import_id)
    updated = database.sensor_imports.find_one_and_update(
        {
            "_id": object_id,
            "organization_id": principal.organization_id,
            "status": "failed",
        },
        {
            "$set": {
                "status": "queued",
                "cancel_requested": False,
                "updated_at": datetime.now(UTC),
                "error_summary": None,
                "dispatch_token": secrets.token_hex(16),
            }
        },
        return_document=True,
    )
    if updated is None:
        existing = database.sensor_imports.find_one(
            {"_id": object_id, "organization_id": principal.organization_id}
        )
        if existing is None:
            raise HTTPException(status_code=404, detail="Import was not found.")
        raise HTTPException(status_code=409, detail="Only failed imports can be retried.")
    try:
        process_sensor_import.delay(str(object_id))
    except OperationalError as error:
        database.sensor_imports.update_one(
            {"_id": object_id, "organization_id": principal.organization_id, "status": "queued"},
            {
                "$set": {
                    "status": "failed",
                    "error_summary": "The background worker could not be reached. Retry this import.",
                    "updated_at": datetime.now(UTC),
                }
            },
        )
        logger.error("Could not dispatch sensor import retry", extra={"sensor_import_id": import_id, "exception_type": type(error).__name__})
        raise HTTPException(status_code=503, detail="The background worker is unavailable. Retry this import.") from error
    return {"import": _serialize_import(updated)}
