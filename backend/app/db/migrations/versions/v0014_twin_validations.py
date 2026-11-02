VERSION = "0014_twin_validations"


def upgrade(database) -> None:
    if "twin_validations" not in database.list_collection_names():
        database.create_collection("twin_validations")

    database.twin_validations.create_index(
        [("organization_id", 1), ("validation_id", 1)],
        unique=True,
        name="uq_twin_validation_org_id",
    )
    database.twin_validations.create_index(
        [("organization_id", 1), ("line_id", 1), ("line_version", 1), ("created_at", -1)],
        name="ix_twin_validation_org_line_version",
    )
    database.twin_validations.create_index(
        [("organization_id", 1), ("simulation_run_id", 1)],
        name="ix_twin_validation_org_run",
    )
    database.twin_validations.create_index(
        [("organization_id", 1), ("idempotency_key", 1)],
        unique=True,
        sparse=True,
        name="uq_twin_validation_org_idempotency",
    )
