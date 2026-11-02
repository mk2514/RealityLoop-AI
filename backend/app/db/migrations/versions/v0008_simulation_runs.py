VERSION = "0008_simulation_runs"


def upgrade(database) -> None:
    for name in ("simulation_runs", "simulation_events"):
        if name not in database.list_collection_names():
            database.create_collection(name)

    database.simulation_runs.create_index(
        [("organization_id", 1), ("line_id", 1), ("created_at", -1)],
        name="ix_sim_runs_org_line_created",
    )
    database.simulation_runs.create_index(
        [("organization_id", 1), ("run_id", 1)],
        unique=True,
        name="uq_sim_runs_org_run",
    )
    database.simulation_runs.create_index(
        [("organization_id", 1), ("status", 1), ("created_at", -1)],
        name="ix_sim_runs_org_status",
    )
    database.simulation_events.create_index(
        [("organization_id", 1), ("run_id", 1), ("time", 1), ("sequence", 1)],
        unique=True,
        name="uq_sim_events_org_run_sequence",
    )
