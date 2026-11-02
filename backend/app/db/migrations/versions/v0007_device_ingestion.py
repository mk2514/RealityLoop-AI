VERSION = "0007_device_ingestion"


def upgrade(database) -> None:
    database.device_credentials.create_index(
        [("key_id", 1)],
        unique=True,
        name="uq_device_credentials_key_id",
    )
    database.device_credentials.create_index(
        [("organization_id", 1), ("revoked_at", 1), ("expires_at", 1)],
        name="ix_device_credentials_org_lifecycle",
    )
    database.device_audit_events.create_index(
        [("organization_id", 1), ("created_at", -1)],
        name="ix_device_audit_org_created",
    )
    database.sensor_states.create_index(
        [("organization_id", 1), ("sensor_id", 1)],
        unique=True,
        name="uq_sensor_states_org_sensor",
    )
