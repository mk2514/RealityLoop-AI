from datetime import UTC, datetime

from pymongo.database import Database

from app.db.client import get_database, get_mongo_client
from app.db.migrations.versions import v0001_identity_foundation
from app.db.migrations.versions import v0002_authentication
from app.db.migrations.versions import v0003_factory_assets

MIGRATIONS = (
    v0001_identity_foundation,
    v0002_authentication,
    v0003_factory_assets,
)


def migrate(database: Database) -> list[str]:
    if "schema_migrations" not in database.list_collection_names():
        database.create_collection("schema_migrations")

    applied: list[str] = []
    history = database["schema_migrations"]
    for migration in MIGRATIONS:
        if history.find_one({"_id": migration.VERSION}) is not None:
            continue
        migration.upgrade(database)
        history.insert_one({"_id": migration.VERSION, "applied_at": datetime.now(UTC)})
        applied.append(migration.VERSION)
    return applied


def main() -> None:
    client = get_mongo_client()
    try:
        applied = migrate(get_database())
        if applied:
            print(f"Applied MongoDB migrations: {', '.join(applied)}")
        else:
            print("MongoDB schema is up to date.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
