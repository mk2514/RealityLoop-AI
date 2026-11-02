from copy import deepcopy

import pytest

from app.simulation.engine import (
    SimulationValidationError,
    simulate,
    validate_snapshot,
)
from app.api.routes.scenarios import (
    Delta,
    _derived_seed,
    apply_delta,
)


def deterministic_snapshot() -> dict:
    return {
        "schema_version": 1,
        "line_id": "line-1",
        "line_version": 1,
        "line_version_snapshot": {"model": {}},
        "model": {
            "layout": {
                "nodes": [
                    {"id": "source", "type": "source"},
                    {"id": "machine-a", "type": "machine", "machine_id": "machine-1", "label": "Machine A"},
                    {"id": "sink", "type": "sink"},
                ],
                "edges": [
                    {"id": "edge-1", "source": "source", "target": "machine-a"},
                    {"id": "edge-2", "source": "machine-a", "target": "sink"},
                ],
            },
            "products": [{"id": "product-1", "name": "Fixture part"}],
            "recipes": [{
                "id": "recipe-1",
                "product_id": "product-1",
                "steps": [{
                    "id": "step-1",
                    "operation": "process",
                    "machine_node_ids": ["machine-a"],
                    "cycle_time_seconds": 10.0,
                    "setup_time_seconds": 0,
                    "batch_size": 1,
                }],
            }],
        },
        "resolved_machine_parameters": {
            "machine-1": {"nominal_cycle_time_seconds": 10.0},
        },
        "factory_calendar": {"shifts": []},
        "factory_timezone": "UTC",
        "recipe_id": "recipe-1",
        "product_id": "product-1",
        "assumptions": {"distribution": "deterministic"},
        "seed": 42,
        "run_limits": {"entity_count": 100, "simulated_time_seconds": 100.0},
    }


def test_deterministic_fixture_hand_calculated_output() -> None:
    snapshot = deterministic_snapshot()
    first = simulate(snapshot)
    second = simulate(deepcopy(snapshot))

    assert first["event_log_hash"] == second["event_log_hash"]
    assert first["snapshot_hash"] == second["snapshot_hash"]
    # Arithmetic: 100 seconds / 10-second cycle = 10 cycle slots, but the
    # final entity reaches its start before 100 seconds and is not counted
    # until its completion timeout, so this fixture records 9 completions.
    assert first["metrics"]["cycle_completions"] == {"machine-a": 9}
    assert first["metrics"]["throughput_per_second"] == 0.09
    assert first["metrics"]["station_utilization"]["machine-a"] == 1.0


def test_different_seed_is_allowed_but_deterministic_fixture_differs_only_when_stochastic() -> None:
    snapshot = deterministic_snapshot()
    snapshot["assumptions"] = {"distribution": "deterministic"}
    snapshot["seed"] = 42
    first = simulate(snapshot)
    snapshot["seed"] = 43
    second = simulate(snapshot)
    assert first["event_log_hash"] == second["event_log_hash"]

    snapshot["assumptions"] = {
        "distribution": "uniform_cycle_time",
        "cycle_time_spread_seconds": 2.0,
    }
    snapshot["seed"] = 42
    first = simulate(snapshot)
    snapshot["seed"] = 43
    second = simulate(snapshot)
    assert first["event_log_hash"] != second["event_log_hash"]


def test_snapshot_is_pinned_and_validation_is_actionable() -> None:
    snapshot = deterministic_snapshot()
    original = simulate(snapshot)["snapshot_hash"]
    live_machine_change = deepcopy(snapshot)
    live_machine_change["resolved_machine_parameters"]["machine-1"]["nominal_cycle_time_seconds"] = 999
    assert original != simulate(live_machine_change)["snapshot_hash"]

    invalid = deterministic_snapshot()
    invalid["line_id"] = "line-1"
    invalid["model"]["layout"]["nodes"][1]["machine_id"] = None
    invalid["resolved_machine_parameters"] = {}
    errors = validate_snapshot(invalid)
    assert any(error["code"] == "missing_resolved_cycle_time" for error in errors)

    with pytest.raises(SimulationValidationError) as raised:
        simulate(invalid)
    assert raised.value.errors


def test_scenario_parallel_delta_and_routing_validation() -> None:
    snapshot = deterministic_snapshot()
    candidate, errors = apply_delta(
        snapshot,
        Delta(type="parallel_equipment", station_id="machine-a", resource_quantity=3),
    )
    assert errors == []
    machine = candidate["model"]["layout"]["nodes"][1]
    assert machine["resource_quantity"] == 3

    _, errors = apply_delta(
        snapshot,
        Delta(
            type="routing",
            operation="add",
            edge={"source": "machine-a", "target": "missing-station"},
        ),
    )
    assert any(error["code"] == "routing_to_missing_station" for error in errors)


def test_paired_replication_seed_is_deterministic() -> None:
    assert _derived_seed("comparison-1", "candidate-a", 2) == _derived_seed(
        "comparison-1",
        "candidate-a",
        2,
    )
    assert _derived_seed("comparison-1", "candidate-a", 2) != _derived_seed(
        "comparison-1",
        "candidate-b",
        2,
    )
