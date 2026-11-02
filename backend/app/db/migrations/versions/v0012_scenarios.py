VERSION = "0012_scenarios"


def upgrade(database) -> None:
    for name in ("scenarios", "scenario_runs", "scenario_comparisons", "chaos_profiles"):
        if name not in database.list_collection_names():
            database.create_collection(name)

    database.scenarios.create_index(
        [("organization_id", 1), ("scenario_id", 1)],
        unique=True,
        name="uq_scenarios_org_id",
    )
    database.scenarios.create_index(
        [("organization_id", 1), ("line_id", 1), ("created_at", -1)],
        name="ix_scenarios_org_line_created",
    )
    database.scenario_runs.create_index(
        [("organization_id", 1), ("run_id", 1)],
        unique=True,
        name="uq_scenario_runs_org_id",
    )
    database.scenario_comparisons.create_index(
        [("organization_id", 1), ("comparison_id", 1)],
        unique=True,
        name="uq_scenario_comparisons_org_id",
    )
    database.scenario_comparisons.create_index(
        [("organization_id", 1), ("line_id", 1), ("created_at", -1)],
        name="ix_comparisons_org_line_created",
    )
    database.chaos_profiles.create_index(
        [("organization_id", 1), ("profile_key", 1), ("version", 1)],
        unique=True,
        name="uq_chaos_profiles_org_key_version",
    )
