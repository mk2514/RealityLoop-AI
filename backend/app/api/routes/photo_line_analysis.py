import hashlib
import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from kombu.exceptions import OperationalError
from PIL import Image, ImageOps, UnidentifiedImageError
from pymongo.errors import DuplicateKeyError

from app.api.routes.auth import Principal, get_current_principal, require_csrf, require_roles
from app.core.config import get_settings
from app.db.client import get_database
from app.telemetry.storage import PrivateStorageUnavailable, get_storage_client
from app.worker.photo_analysis import process_photo_analysis_job

router = APIRouter(dependencies=[Depends(require_csrf)])
EDIT_ROLES = ("owner", "administrator", "engineer")
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


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


def _object_id(value: str, label: str = "Photo analysis job") -> ObjectId:
    try:
        return ObjectId(value)
    except InvalidId as error:
        raise HTTPException(status_code=404, detail=f"{label} was not found.") from error


def sanitize_image(content: bytes, settings: Any) -> tuple[bytes, str, int, int]:
    if len(content) > settings.photo_max_image_bytes:
        raise HTTPException(status_code=413, detail=f"An image exceeds the {settings.photo_max_image_bytes}-byte limit.")
    try:
        source = Image.open(io.BytesIO(content))
        source.verify()
        source = Image.open(io.BytesIO(content))
        image = ImageOps.exif_transpose(source).convert("RGB")
        width, height = image.size
        if width * height > settings.photo_max_pixels:
            raise HTTPException(status_code=413, detail=f"An image exceeds the {settings.photo_max_pixels}-pixel limit.")
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=88, optimize=True)
        sanitized = output.getvalue()
        return sanitized, "image/jpeg", width, height
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise HTTPException(status_code=400, detail="Upload a valid JPEG, PNG or WebP image.") from error


@router.post("/photo-line-jobs")
@require_roles(*EDIT_ROLES)
async def create_photo_job(
    principal: Principal = Depends(get_current_principal),
    files: list[UploadFile] = File(...),
    line_id: str = Form(default=""),
    consent_confirmed: bool = Form(...),
    idempotency_key: str | None = Form(default=None),
) -> dict[str, Any]:
    if not consent_confirmed:
        raise HTTPException(status_code=422, detail="Consent is required before external photo processing.")
    settings = get_settings()
    if len(files) < 1 or len(files) > settings.photo_max_images:
        raise HTTPException(status_code=422, detail=f"Upload between 1 and {settings.photo_max_images} images.")
    database = get_database()
    if idempotency_key:
        existing = database.photo_line_jobs.find_one({
            "organization_id": principal.organization_id,
            "created_by": principal.user_id,
            "idempotency_key": idempotency_key,
        })
        if existing is not None:
            return {"job": _serialize(existing), "duplicate": True}
    line_object_id = None
    if line_id:
        try:
            line_object_id = ObjectId(line_id)
        except InvalidId as error:
            raise HTTPException(status_code=404, detail="Production line was not found.") from error
        line = database.production_lines.find_one({
            "_id": line_object_id,
            "organization_id": principal.organization_id,
            "archived_at": None,
        })
        if line is None:
            raise HTTPException(status_code=404, detail="Production line was not found.")
    job_count = database.photo_line_jobs.count_documents({"organization_id": principal.organization_id})
    if job_count >= settings.photo_max_jobs_per_org:
        raise HTTPException(status_code=429, detail=f"The organization photo-job limit of {settings.photo_max_jobs_per_org} has been reached.")
    try:
        storage, bucket = get_storage_client()
    except PrivateStorageUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    now = datetime.now(UTC)
    job_id = uuid.uuid4().hex
    job = {
        "_id": ObjectId(),
        "job_id": job_id,
        "organization_id": principal.organization_id,
        "created_by": principal.user_id,
        "line_id": line_object_id,
        "status": "queued",
        "idempotency_key": idempotency_key or f"auto:{job_id}",
        "created_at": now,
        "updated_at": now,
        "retention_until": now + timedelta(days=settings.photo_retention_days),
        "schema_version": 1,
        "consent_confirmed": True,
        "attempt_count": 0,
        "provider": "gemini" if settings.gemini_api_key else "unconfigured",
    }
    try:
        database.photo_line_jobs.insert_one(job)
    except DuplicateKeyError:
        existing = database.photo_line_jobs.find_one({
            "organization_id": principal.organization_id,
            "created_by": principal.user_id,
            "idempotency_key": job["idempotency_key"],
        })
        if existing is None:
            raise HTTPException(status_code=409, detail="Duplicate photo job.")
        return {"job": _serialize(existing), "duplicate": True}

    try:
        for index, upload in enumerate(files):
            if upload.content_type not in ALLOWED_IMAGE_TYPES:
                raise HTTPException(status_code=415, detail="Only JPEG, PNG and WebP images are supported.")
            content = await upload.read(settings.photo_max_image_bytes + 1)
            sanitized, content_type, width, height = sanitize_image(content, settings)
            checksum = hashlib.sha256(sanitized).hexdigest()
            key = f"photo-jobs/{principal.organization_id}/{job_id}/{index}-{checksum}.jpg"
            storage.put_object(
                Bucket=bucket,
                Key=key,
                Body=sanitized,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )
            database.photo_line_images.insert_one({
                "_id": ObjectId(),
                "organization_id": principal.organization_id,
                "job_id": job["_id"],
                "image_id": uuid.uuid4().hex,
                "image_index": index,
                "storage_key": key,
                "content_type": content_type,
                "checksum_sha256": checksum,
                "width": width,
                "height": height,
                "created_at": now,
            })
    except HTTPException:
        database.photo_line_jobs.delete_one({"_id": job["_id"]})
        raise
    except (BotoCoreError, ClientError) as error:
        database.photo_line_jobs.update_one(
            {"_id": job["_id"]},
            {"$set": {"status": "failed", "error": {"code": "private_storage_unavailable", "message": "Private image storage could not be used."}, "updated_at": datetime.now(UTC)}},
        )
        raise HTTPException(status_code=503, detail="Private image storage is unavailable.") from error

    try:
        process_photo_analysis_job.delay(str(job["_id"]))
    except OperationalError as error:
        database.photo_line_jobs.update_one(
            {"_id": job["_id"]},
            {"$set": {"status": "failed", "error": {"code": "queue_unavailable", "message": "The analysis queue is unavailable. Retry after the worker is connected."}, "updated_at": datetime.now(UTC)}},
        )
        raise HTTPException(status_code=503, detail="The analysis queue is unavailable.") from error
    return {"job": _serialize(job), "duplicate": False}


@router.get("/photo-line-jobs/{job_id}")
@require_roles("owner", "administrator", "engineer", "viewer")
def get_photo_job(job_id: str, principal: Principal = Depends(get_current_principal)) -> dict[str, Any]:
    job = get_database().photo_line_jobs.find_one({
        "_id": _object_id(job_id),
        "organization_id": principal.organization_id,
    })
    if job is None:
        raise HTTPException(status_code=404, detail="Photo analysis job was not found.")
    return {"job": _serialize(job)}


@router.get("/photo-line-jobs/{job_id}/images/{image_id}")
@require_roles("owner", "administrator", "engineer", "viewer")
def get_photo_image(job_id: str, image_id: str, principal: Principal = Depends(get_current_principal)) -> dict[str, Any]:
    database = get_database()
    job_object_id = _object_id(job_id)
    job = database.photo_line_jobs.find_one({"_id": job_object_id, "organization_id": principal.organization_id})
    if job is None:
        raise HTTPException(status_code=404, detail="Photo analysis job was not found.")
    image = database.photo_line_images.find_one({
        "job_id": job_object_id,
        "image_id": image_id,
        "organization_id": principal.organization_id,
    })
    if image is None:
        raise HTTPException(status_code=404, detail="Photo was not found.")
    try:
        storage, bucket = get_storage_client()
        url = storage.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": image["storage_key"]},
            ExpiresIn=settings_download_ttl(),
        )
    except (PrivateStorageUnavailable, BotoCoreError, ClientError) as error:
        raise HTTPException(status_code=503, detail="Private image storage is unavailable.") from error
    return {"download_url": url, "image_id": image_id, "width": image["width"], "height": image["height"]}


def settings_download_ttl() -> int:
    return 300


@router.delete("/photo-line-jobs/{job_id}")
@require_roles(*EDIT_ROLES)
def delete_photo_job(job_id: str, principal: Principal = Depends(get_current_principal)) -> dict[str, Any]:
    database = get_database()
    job_object_id = _object_id(job_id)
    job = database.photo_line_jobs.find_one({"_id": job_object_id, "organization_id": principal.organization_id})
    if job is None:
        raise HTTPException(status_code=404, detail="Photo analysis job was not found.")
    images = list(database.photo_line_images.find({"job_id": job_object_id, "organization_id": principal.organization_id}))
    try:
        storage, bucket = get_storage_client()
        for image in images:
            storage.delete_object(Bucket=bucket, Key=image["storage_key"])
    except (PrivateStorageUnavailable, BotoCoreError, ClientError) as error:
        raise HTTPException(status_code=503, detail="Private image storage could not complete deletion.") from error
    database.photo_line_images.delete_many({"job_id": job_object_id, "organization_id": principal.organization_id})
    database.photo_line_jobs.delete_one({"_id": job_object_id, "organization_id": principal.organization_id})
    return {"deleted": True, "job_id": job_id}
