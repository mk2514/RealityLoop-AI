VERSION = "0006_sensor_readings"


def upgrade(database) -> None:
    database.sensor_readings.create_index(
        [("organization_id", 1), ("event_key", 1)],
        unique=True,
        name="uq_sensor_readings_org_event_key",
    )
    database.sensor_readings.create_index(
        [("organization_id", 1), ("sensor_id", 1), ("event_time_utc", 1)],
        name="ix_sensor_readings_sensor_event_time",
    )
    database.sensor_imports.create_index(
        [("organization_id", 1), ("_id", 1)],
        name="ix_sensor_imports_org_id",
    )
    database.sensor_imports.create_index(
        [("organization_id", 1), ("sensor_id", 1), ("source_checksum", 1)],
        name="ix_sensor_imports_sensor_checksum",
    )
    database.sensor_import_rows.create_index(
        [("organization_id", 1), ("import_id", 1), ("row_number", 1)],
        unique=True,
        name="uq_sensor_import_rows_org_import_row",
    )
