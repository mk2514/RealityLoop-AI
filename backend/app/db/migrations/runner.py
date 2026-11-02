from datetime import UTC, datetime

from pymongo.database import Database

from app.db.client import get_database, get_mongo_client
from app.db.migrations.versions import v0001_identity_foundation
from app.db.migrations.versions import v0002_authentication
from app.db.migrations.versions import v0003_factory_assets
from app.db.migrations.versions import v0004_production_line_models

from app.db.migrations.versions import v0005_rate_windows
from app.db.migrations.versions import v0006_sensor_readings
from app.db.migrations.versions import v0007_device_ingestion
from app.db.migrations.versions import v0008_simulation_runs
from app.db.migrations.versions import v0009_dashboards
from app.db.migrations.versions import v0012_scenarios
from app.db.migrations.versions import v0013_photo_line_analysis
from app.db.migrations.versions import v0014_twin_validations

MIGRATIONS = (
    v0001_identity_foundation,
    v0002_authentication,
    v0003_factory_assets,
    v0004_production_line_models,
    v0005_rate_windows,
    v0006_sensor_readings,
    v0007_device_ingestion,
    v0008_simulation_runs,
    v0009_dashboards,
    v0012_scenarios,
    v0013_photo_line_analysis,
    v0014_twin_validations,
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
