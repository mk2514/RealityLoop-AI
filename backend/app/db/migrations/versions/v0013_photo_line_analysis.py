from pymongo.database import Database

VERSION = "0013_photo_line_analysis"


PHOTO_JOBS_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "organization_id", "job_id", "line_id", "created_by", "status",
            "idempotency_key", "created_at", "updated_at", "retention_until",
            "schema_version", "consent_confirmed",
        ],
        "properties": {
            "organization_id": {"bsonType": "objectId"},
            "line_id": {"bsonType": ["objectId", "null"]},
            "status": {"enum": ["queued", "processing", "completed", "failed", "cancelled", "missing_key", "provider_outage"]},
            "schema_version": {"enum": [1]},
        },
    }
}


def _ensure_collection(database: Database, name: str, validator: dict) -> None:
    if name in database.list_collection_names():
        database.command({"collMod": name, "validator": validator, "validationLevel": "strict", "validationAction": "error"})
    else:
        database.create_collection(name, validator=validator, validationLevel="strict", validationAction="error")


def upgrade(database: Database) -> None:
    _ensure_collection(database, "photo_line_jobs", PHOTO_JOBS_VALIDATOR)
    if "photo_line_images" not in database.list_collection_names():
        database.create_collection("photo_line_images")

    database.photo_line_jobs.create_index(
        [("organization_id", 1), ("job_id", 1)],
        unique=True,
        name="uq_photo_jobs_org_job",
    )
    database.photo_line_jobs.create_index(
        [("organization_id", 1), ("created_by", 1), ("idempotency_key", 1)],
        unique=True,
        sparse=True,
        name="uq_photo_jobs_org_user_idempotency",
    )
    database.photo_line_jobs.create_index(
        [("organization_id", 1), ("line_id", 1), ("created_at", -1)],
        name="ix_photo_jobs_org_line_created",
    )
    database.photo_line_jobs.create_index(
        [("retention_until", 1)],
        expireAfterSeconds=0,
        name="ttl_photo_jobs_retention",
    )
    database.photo_line_images.create_index(
        [("organization_id", 1), ("job_id", 1), ("image_id", 1)],
        unique=True,
        name="uq_photo_images_org_job_image",
    )
