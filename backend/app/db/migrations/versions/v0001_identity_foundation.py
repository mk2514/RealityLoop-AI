from pymongo.database import Database

VERSION = "0001_identity_foundation"

COLLECTIONS = {
    "organizations": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["name", "slug", "created_at", "updated_at"],
            "additionalProperties": False,
            "properties": {
                "_id": {"bsonType": "objectId"},
                "name": {"bsonType": "string", "minLength": 1, "maxLength": 200},
                "slug": {
                    "bsonType": "string",
                    "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
                    "minLength": 1,
                    "maxLength": 80,
                },
                "created_at": {"bsonType": "date"},
                "updated_at": {"bsonType": "date"},
            },
        }
    },
    "users": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["email", "full_name", "created_at", "updated_at"],
            "additionalProperties": False,
            "properties": {
                "_id": {"bsonType": "objectId"},
                "email": {
                    "bsonType": "string",
                    "pattern": r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
                    "minLength": 3,
                    "maxLength": 320,
                },
                "full_name": {"bsonType": "string", "minLength": 1, "maxLength": 200},
                "email_verified_at": {"bsonType": ["date", "null"]},
                "created_at": {"bsonType": "date"},
                "updated_at": {"bsonType": "date"},
            },
        }
    },
    "organization_memberships": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": [
                "organization_id",
                "user_id",
                "role",
                "created_at",
                "updated_at",
            ],
            "additionalProperties": False,
            "properties": {
                "_id": {"bsonType": "objectId"},
                "organization_id": {"bsonType": "objectId"},
                "user_id": {"bsonType": "objectId"},
                "role": {"enum": ["owner", "admin", "member", "viewer"]},
                "created_at": {"bsonType": "date"},
                "updated_at": {"bsonType": "date"},
            },
        }
    },
}


def ensure_collection(database: Database, name: str, validator: dict) -> None:
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


def create_indexes(database: Database) -> None:
    database.organizations.create_index("slug", unique=True, name="uq_organizations_slug")
    database.users.create_index("email", unique=True, name="uq_users_email")
    database.organization_memberships.create_index(
        [("organization_id", 1), ("user_id", 1)],
        unique=True,
        name="uq_membership_organization_user",
    )
    database.organization_memberships.create_index("user_id", name="ix_membership_user")


def upgrade(database: Database) -> None:
    for collection, validator in COLLECTIONS.items():
        ensure_collection(database, collection, validator)
    create_indexes(database)
