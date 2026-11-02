VERSION = "0009_dashboards"


def upgrade(database) -> None:
    for name in (
        "dashboard_layouts",
        "dashboard_threshold_rules",
        "dashboard_alert_states",
        "dashboard_station_sensor_mappings",
    ):
        if name not in database.list_collection_names():
            database.create_collection(name)

    database.dashboard_layouts.create_index(
        [("organization_id", 1), ("user_id", 1), ("scope_key", 1)],
        unique=True,
        name="uq_dashboard_layout_owner_scope",
    )
    database.dashboard_threshold_rules.create_index(
        [("organization_id", 1), ("sensor_id", 1), ("version", -1)],
        name="ix_dashboard_rules_org_sensor_version",
    )
    database.dashboard_alert_states.create_index(
        [("organization_id", 1), ("rule_id", 1), ("updated_at", -1)],
        name="ix_dashboard_alert_org_rule_updated",
    )
    database.dashboard_station_sensor_mappings.create_index(
        [("organization_id", 1), ("line_id", 1), ("line_version", 1), ("station_id", 1)],
        unique=True,
        name="uq_dashboard_mapping_org_line_station",
    )
