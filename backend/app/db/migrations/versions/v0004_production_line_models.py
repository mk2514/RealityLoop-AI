from pymongo.database import Database

VERSION = "0004_production_line_models"

MODEL_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "organization_id",
            "line_id",
            "revision",
            "model",
            "updated_by",
            "updated_at",
        ],
        "additionalProperties": False,
        "properties": {
            "_id": {"bsonType": "objectId"},
            "organization_id": {"bsonType": "objectId"},
            "line_id": {"bsonType": "objectId"},
            "revision": {"bsonType": "int", "minimum": 1},
            "model": {"bsonType": "object"},
            "updated_by": {"bsonType": "objectId"},
            "updated_at": {"bsonType": "date"},
        },
    }
}

VERSION_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "organization_id",
            "line_id",
            "version",
            "model",
            "validation",
            "created_by",
            "created_at",
        ],
        "additionalProperties": False,
        "properties": {
            "_id": {"bsonType": "objectId"},
            "organization_id": {"bsonType": "objectId"},
            "line_id": {"bsonType": "objectId"},
            "version": {"bsonType": "int", "minimum": 1},
            "model": {"bsonType": "object"},
            "validation": {
                "bsonType": "object",
                "required": ["valid", "errors", "transfer_times"],
                "additionalProperties": False,
                "properties": {
                    "valid": {"bsonType": "bool"},
                    "errors": {"bsonType": "array", "maxItems": 20000},
                    "transfer_times": {"bsonType": "array", "maxItems": 500},
                },
            },
            "created_by": {"bsonType": "objectId"},
            "created_at": {"bsonType": "date"},
        },
    }
}


def _ensure_collection(database: Database, name: str, validator: dict) -> None:
    if name in database.list_collection_names():
        database.command(
            {
                "collMod": name,
                "validator": validator,
                "validationLevel": "strict",
                "validationAction": "error",
            }
        )
    else:
        database.create_collection(
            name,
            validator=validator,
            validationLevel="strict",
            validationAction="error",
        )


def upgrade(database: Database) -> None:
    _ensure_collection(database, "production_line_models", MODEL_VALIDATOR)
    _ensure_collection(database, "production_line_versions", VERSION_VALIDATOR)
    database.production_line_models.create_index(
        [("organization_id", 1), ("line_id", 1)],
        unique=True,
        name="uq_line_models_organization_line",
    )
    database.production_line_versions.create_index(
        [("organization_id", 1), ("line_id", 1), ("version", 1)],
        unique=True,
        name="uq_line_versions_organization_line_version",
    )
    database.production_line_versions.create_index(
        [("organization_id", 1), ("line_id", 1), ("created_at", -1)],
        name="ix_line_versions_organization_line_created",
    )
