from pymongo.database import Database

VERSION = "0002_authentication"

USER_VALIDATOR = {
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
            "password_hash": {
                "bsonType": ["string", "null"],
                "minLength": 20,
                "maxLength": 512,
            },
            "email_verified_at": {"bsonType": ["date", "null"]},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
        },
    }
}

MEMBERSHIP_VALIDATOR = {
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
            "role": {"enum": ["owner", "administrator", "engineer", "operator", "viewer"]},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
        },
    }
}

FACTORY_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "organization_id",
            "name",
            "created_at",
            "updated_at",
        ],
        "additionalProperties": False,
        "properties": {
            "_id": {"bsonType": "objectId"},
            "organization_id": {"bsonType": "objectId"},
            "name": {"bsonType": "string", "minLength": 1, "maxLength": 160},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
        },
    }
}

AUTH_TOKEN_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["user_id", "token_type", "expires_at", "created_at"],
        "additionalProperties": False,
        "properties": {
            "_id": {"bsonType": "string"},
            "user_id": {"bsonType": "objectId"},
            "token_type": {"enum": ["email_verification", "password_reset"]},
            "expires_at": {"bsonType": "date"},
            "created_at": {"bsonType": "date"},
        },
    }
}

SESSION_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["user_id", "organization_id", "expires_at", "created_at"],
        "additionalProperties": False,
        "properties": {
            "_id": {"bsonType": "string"},
            "user_id": {"bsonType": "objectId"},
            "organization_id": {"bsonType": "objectId"},
            "expires_at": {"bsonType": "date"},
            "created_at": {"bsonType": "date"},
            "last_seen_at": {"bsonType": "date"},
        },
    }
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


def upgrade(database: Database) -> None:
    database.organization_memberships.update_many(
        {"role": "admin"},
        {"$set": {"role": "administrator"}},
    )
    database.organization_memberships.update_many(
        {"role": "member"},
        {"$set": {"role": "viewer"}},
    )
    database.command(
        {
            "collMod": "users",
            "validator": USER_VALIDATOR,
            "validationLevel": "strict",
            "validationAction": "error",
        }
    )
    database.command(
        {
            "collMod": "organization_memberships",
            "validator": MEMBERSHIP_VALIDATOR,
            "validationLevel": "strict",
            "validationAction": "error",
        }
    )

    for collection, validator in (
        ("factories", FACTORY_VALIDATOR),
        ("auth_tokens", AUTH_TOKEN_VALIDATOR),
        ("sessions", SESSION_VALIDATOR),
    ):
        ensure_collection(database, collection, validator)

    database.users.create_index("email", unique=True, name="uq_users_email")
    database.organization_memberships.create_index(
        [("organization_id", 1), ("user_id", 1)],
        unique=True,
        name="uq_membership_organization_user",
    )
    database.factories.create_index(
        [("organization_id", 1), ("_id", 1)],
        name="ix_factories_organization_id",
    )
    database.auth_tokens.create_index(
        "expires_at",
        expireAfterSeconds=0,
        name="ttl_auth_tokens_expiry",
    )
    database.auth_tokens.create_index(
        [("user_id", 1), ("token_type", 1)],
        name="ix_auth_tokens_user_type",
    )
    database.sessions.create_index(
        "expires_at",
        expireAfterSeconds=0,
        name="ttl_sessions_expiry",
    )
    database.sessions.create_index("user_id", name="ix_sessions_user")
