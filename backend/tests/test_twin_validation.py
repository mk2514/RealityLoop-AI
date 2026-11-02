from datetime import UTC, datetime, timedelta

import mongomock

from app.api.routes.twin_validations import evaluate_validation


def _reading(sensor_id, value, event_time):
    return {
        "organization_id": "org-1",
        "sensor_id": sensor_id,
        "quantity": "count",
        "unit": "count",
        "value": value,
        "event_time_utc": event_time,
        "quality": "good",
    }


def test_known_fixture_has_hand_calculated_error() -> None:
    database = mongomock.MongoClient().get_database("realityloop")
    sensor_id = database.sensors.insert_one({"organization_id": "org-1", "measurement_type": "count"}).inserted_id
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for value, minutes in ((100, 0), (105, 1), (110, 2), (115, 3)):
        database.sensor_readings.insert_one(_reading(sensor_id, value, start + timedelta(minutes=minutes)))

    record = {
        "organization_id": "org-1",
        "pinned": {
            "sensor_mapping": {"exit_count_sensor_id": str(sensor_id)},
            "observation_window": {
                "start": (start - timedelta(seconds=1)).isoformat(),
                "end": (start + timedelta(minutes=4)).isoformat(),
            },
            "data_quality_rules": {
                "counter_mode": "cumulative",
                "expected_interval_seconds": 60,
                "max_missing_gap_seconds": 300,
                "minimum_samples": 3,
                "duplicate_tolerance_seconds": 1,
            },
            "feed_conditions": {"product": "fixture", "feed_rate": 20},
            "simulation_metrics": {"cycle_completions": {"machine-a": 18}},
        },
    }
    result = evaluate_validation(database, record)
    metric = result["metrics"]["conveyor_exit_count"]
    # Fixture arithmetic: observed counter rise = 115 - 100 = 15; simulated = 18.
    assert metric["observed_total"] == 15
    assert metric["simulated_total"] == 18
    assert metric["signed_bias"] == 3
    assert metric["absolute_error"] == 3
    assert metric["sample_size"] == 4
    assert result["status"] == "completed"


def test_missing_ground_truth_is_insufficient_evidence() -> None:
    database = mongomock.MongoClient().get_database("realityloop")
    sensor_id = database.sensors.insert_one({"organization_id": "org-1", "measurement_type": "count"}).inserted_id
    start = datetime(2026, 1, 1, tzinfo=UTC)
    record = {
        "organization_id": "org-1",
        "pinned": {
            "sensor_mapping": {"exit_count_sensor_id": str(sensor_id)},
            "observation_window": {"start": start.isoformat(), "end": (start + timedelta(hours=1)).isoformat()},
            "data_quality_rules": {
                "counter_mode": "cumulative",
                "expected_interval_seconds": None,
                "max_missing_gap_seconds": 300,
                "minimum_samples": 2,
                "duplicate_tolerance_seconds": 1,
            },
            "feed_conditions": {},
            "simulation_metrics": {"cycle_completions": {"machine-a": 10}},
        },
    }
    result = evaluate_validation(database, record)
    assert result["status"] == "insufficient_evidence"
    assert result["metrics"]["conveyor_exit_count"]["status"] == "insufficient_evidence"
    assert any(item["code"] == "INSUFFICIENT_GROUND_TRUTH" for item in result["evidence"])
