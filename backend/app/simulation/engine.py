import hashlib
import json
import math
import random
import sys
from copy import deepcopy
from datetime import datetime
from typing import Any

import simpy

TRANSLATOR_VERSION = "realityloop-simpy-v1"
SCHEMA_VERSION = 1


class SimulationValidationError(ValueError):
    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        super().__init__("Simulation snapshot validation failed.")


def _error(code: str, path: str, message: str, action: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message, "action": action}


def validate_snapshot(snapshot: dict[str, Any], settings: Any = None) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    version_snapshot = snapshot.get("line_version_snapshot")
    model = snapshot.get("model") or (
        version_snapshot.get("model", {}) if isinstance(version_snapshot, dict) else {}
    )
    nodes = model.get("layout", {}).get("nodes", [])
    edges = model.get("layout", {}).get("edges", [])
    recipes = model.get("recipes", [])
    products = model.get("products", [])
    nodes_by_id = {node.get("id"): node for node in nodes}
    if not products:
        errors.append(_error("missing_product", "products", "No product is defined.", "Add one product to the line model."))
    if not recipes:
        errors.append(_error("missing_recipe", "recipes", "No production recipe is defined.", "Add a recipe that maps the product through process steps."))
    if len(recipes) > 1:
        errors.append(_error("unsupported_multiple_recipes", "recipes", "A run currently supports one recipe.", "Create a line snapshot containing one recipe."))

    run = snapshot.get("run_limits", {})
    simulated_time = float(run.get("simulated_time_seconds", 0))
    if not math.isfinite(simulated_time) or simulated_time <= 0:
        errors.append(_error("missing_simulated_time", "run_limits.simulated_time_seconds", "Simulation horizon must be a finite positive number.", "Set a positive simulated time horizon."))
    if settings is not None and simulated_time > float(settings.simulation_max_time_seconds):
        errors.append(_error("simulated_time_limit", "run_limits.simulated_time_seconds", "Simulation horizon exceeds the configured limit.", "Reduce the horizon."))

    seen_steps: list[str] = []
    for recipe_index, recipe in enumerate(recipes[:1]):
        for step_index, step in enumerate(recipe.get("steps", [])):
            path = f"recipes.{recipe_index}.steps.{step_index}"
            machine_ids = step.get("machine_node_ids") or []
            cycle_time = step.get("cycle_time_seconds")
            if not machine_ids:
                errors.append(_error("missing_machine_assignment", path, "Process step has no machine node.", "Assign at least one machine station."))
            if cycle_time is None or not math.isfinite(float(cycle_time)) or float(cycle_time) <= 0:
                errors.append(_error("missing_cycle_time", f"{path}.cycle_time_seconds", "Process step cycle time is missing or invalid.", "Set a positive finite cycle time."))
            if step.get("setup_time_seconds") is not None and (not math.isfinite(float(step["setup_time_seconds"])) or float(step["setup_time_seconds"]) < 0):
                errors.append(_error("invalid_setup_time", f"{path}.setup_time_seconds", "Setup/changeover time is invalid.", "Set a non-negative finite setup time or omit it."))
            if step.get("batch_size") is not None and int(step["batch_size"]) < 1:
                errors.append(_error("invalid_batch_size", f"{path}.batch_size", "Batch size must be at least one.", "Set a positive batch size."))
            for machine_id in machine_ids:
                if machine_id not in nodes_by_id:
                    errors.append(_error("routing_to_missing_station", f"{path}.machine_node_ids", f"Node '{machine_id}' is not in the line layout.", "Assign an existing station node."))
                seen_steps.append(machine_id)

    machine_parameters = snapshot.get("resolved_machine_parameters", {})
    for node in nodes:
        if node.get("type") == "machine":
            resource_quantity = node.get("resource_quantity", 1)
            if not isinstance(resource_quantity, int) or resource_quantity < 1 or resource_quantity > 1000:
                errors.append(_error(
                    "invalid_resource_quantity",
                    f"layout.nodes.{node.get('id')}.resource_quantity",
                    "Parallel resource quantity must be a positive integer.",
                    "Set resource_quantity to an integer from 1 through 1000.",
                ))
            machine_id = node.get("machine_id")
            resolved = machine_parameters.get(machine_id, {})
            if resolved.get("nominal_cycle_time_seconds") is None:
                if node.get("id") in seen_steps:
                    errors.append(_error("missing_resolved_cycle_time", f"machines.{machine_id}.nominal_cycle_time_seconds", "Referenced machine has no resolved cycle-time parameter.", "Enter the machine nominal cycle time."))
            if node.get("machine_id") and not resolved:
                errors.append(_error("missing_machine_snapshot", f"machines.{machine_id}", "Machine is not pinned in the run snapshot.", "Recreate the run so machine metadata is resolved and pinned."))
        if node.get("type") == "buffer":
            if node.get("buffer_capacity") is None or int(node["buffer_capacity"]) <= 0:
                errors.append(_error("missing_buffer_capacity", f"layout.nodes.{node.get('id')}.buffer_capacity", "Finite buffer has no capacity.", "Set buffer capacity to at least one."))

    edge_ids: set[str] = set()
    for index, edge in enumerate(edges):
        if edge.get("id") in edge_ids:
            errors.append(_error("duplicate_edge_id", f"layout.edges.{index}", "Duplicate edge ID found.", "Assign a unique edge ID."))
        edge_ids.add(edge.get("id"))
        if edge.get("source") not in nodes_by_id or edge.get("target") not in nodes_by_id:
            errors.append(_error("routing_to_missing_station", f"layout.edges.{index}", "Edge references a node outside the layout.", "Correct the source and target station IDs."))
        if edge.get("route_kind") == "rework":
            rule = edge.get("rework_rule") or {}
            limit = rule.get("max_revisits")
            if limit is None or int(limit) < 1:
                errors.append(_error("unbounded_rework", f"layout.edges.{index}.rework_rule.max_revisits", "Rework revisits are unbounded or missing.", "Set a positive bounded revisit limit."))
    return errors


def build_run_snapshot(
    *,
    line_version: dict[str, Any],
    line_id: str,
    version: int,
    machines: list[dict[str, Any]],
    factory: dict[str, Any] | None,
    recipe_id: str,
    product_id: str,
    seed: int,
    entity_count: int,
    simulated_time_seconds: float,
    assumptions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    model = deepcopy(line_version["model"])
    if not 1 <= entity_count <= 100_000:
        raise SimulationValidationError([_error(
            "invalid_entity_count", "entity_count",
            "Entity count is outside the supported range.",
            "Choose between 1 and 100,000 entities.",
        )])
    resolved_machines: dict[str, dict[str, Any]] = {}
    for machine in machines:
        resolved_machines[str(machine["_id"])] = {
            "name": machine.get("name", ""),
            "machine_type": machine.get("machine_type"),
            "nominal_cycle_time_seconds": machine.get("nominal_cycle_time_seconds"),
            "capacity_per_hour": machine.get("capacity_per_hour"),
            "operating_state": machine.get("operating_state"),
            "archive_revision": machine.get("updated_at"),
        }
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "line_id": line_id,
        "line_version": version,
        "line_version_snapshot": deepcopy(line_version),
        "model": model,
        "resolved_machine_parameters": resolved_machines,
        "factory_calendar": deepcopy(factory.get("operating_calendar", {"shifts": []})) if factory else {"shifts": []},
        "factory_timezone": factory.get("timezone", "UTC") if factory else "UTC",
        "recipe_id": recipe_id,
        "product_id": product_id,
        "assumptions": assumptions or {
            "distribution": "deterministic",
            "entity_arrival": "all_entities_released_at_time_zero",
            "failures": "none",
            "shifts": "calendar_recorded_but_not_applied_without_valid_shift_overlap",
        },
        "engine": {
            "translator_version": TRANSLATOR_VERSION,
            "simpy_version": getattr(simpy, "__version__", "unknown"),
            "python_version": sys.version.split()[0],
        },
        "seed": int(seed),
        "run_limits": {
            "entity_count": entity_count,
            "simulated_time_seconds": float(simulated_time_seconds),
        },
    }
    return snapshot


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def simulate(snapshot: dict[str, Any], settings: Any = None) -> dict[str, Any]:
    errors = validate_snapshot(snapshot, settings)
    if errors:
        raise SimulationValidationError(errors)
    model = snapshot["model"]
    recipe_id = snapshot["recipe_id"]
    recipe = next((item for item in model.get("recipes", []) if item.get("id") == recipe_id), None)
    if recipe is None:
        raise SimulationValidationError([_error(
            "unknown_recipe", "recipe_id",
            "The selected recipe is not present in the pinned line snapshot.",
            "Choose a recipe from this saved line version.",
        )])

    horizon = float(snapshot["run_limits"]["simulated_time_seconds"])
    entity_count = int(snapshot["run_limits"]["entity_count"])
    seed = int(snapshot["seed"])
    rng = random.Random(seed)
    env = simpy.Environment()
    events: list[dict[str, Any]] = []
    sequence = 0
    station_busy: dict[str, float] = {}
    station_blocked: dict[str, float] = {}
    station_idle: dict[str, float] = {}
    station_starved: dict[str, float] = {}
    queue_wait: dict[str, list[float]] = {}
    completions: dict[str, int] = {}
    resources: dict[str, simpy.Resource] = {}
    node_names = {
        node["id"]: node.get("label") or node["id"]
        for node in model["layout"]["nodes"]
    }

    def station_event(time: float, event_type: str, station: str, entity_id: str, state: dict[str, Any] | None = None) -> None:
        nonlocal sequence
        sequence += 1
        if settings is not None and sequence > settings.simulation_max_events:
            raise RuntimeError("SIMULATION_EVENT_LIMIT: The configured event limit was exceeded.")
        events.append({
            "schema_version": SCHEMA_VERSION,
            "sequence": sequence,
            "time": float(time),
            "entity_id": entity_id,
            "station": station,
            "station_name": node_names.get(station, station),
            "event_type": event_type,
            "state": state or {},
        })

    machine_nodes = {
        node["id"]: node
        for node in model["layout"]["nodes"]
        if node["type"] == "machine"
    }
    for node_id in machine_nodes:
        resources[node_id] = simpy.Resource(
            env,
            capacity=int(machine_nodes[node_id].get("resource_quantity", 1)),
        )
        station_busy[node_id] = 0.0
        station_blocked[node_id] = 0.0
        station_idle[node_id] = horizon
        station_starved[node_id] = 0.0
        queue_wait[node_id] = []
        completions[node_id] = 0

    edges = model["layout"].get("edges", [])
    buffer_node_ids = {
        node["id"]: int(node["buffer_capacity"])
        for node in model["layout"]["nodes"]
        if node["type"] == "buffer" and node.get("buffer_capacity")
    }
    stores: dict[str, simpy.Store] = {
        node_id: simpy.Store(env, capacity=capacity)
        for node_id, capacity in buffer_node_ids.items()
    }

    def process_entity(entity_number: int) -> Any:
        entity_id = f"part-{entity_number:06d}"
        station_event(env.now, "arrive", "source", entity_id)
        for step_index, step in enumerate(recipe["steps"]):
            machine_ids = step["machine_node_ids"]
            if not machine_ids:
                continue
            chosen = min(machine_ids, key=lambda machine_id: len(resources[machine_id].queue))
            resource = resources[chosen]
            queue_start = env.now
            station_event(env.now, "starved", chosen, entity_id)
            incoming_buffer = next((
                stores[edge["source"]]
                for edge in edges
                if edge["target"] == chosen and edge["source"] in stores
            ), None)
            if incoming_buffer is not None:
                yield incoming_buffer.get()
            with resource.request() as request:
                yield request
                station_event(env.now, "start", chosen, entity_id)
                queue_wait[chosen].append(env.now - queue_start)
                station_idle[chosen] = max(0.0, station_idle[chosen] - (env.now - queue_start))
                cycle_time = float(step.get("cycle_time_seconds") or 0)
                if cycle_time <= 0:
                    raise RuntimeError(f"VALIDATION_ERROR: missing cycle time for {chosen}")
                if snapshot["assumptions"].get("distribution") == "uniform_cycle_time":
                    spread = float(snapshot["assumptions"].get("cycle_time_spread_seconds", 0))
                    cycle_time = max(0.001, rng.uniform(cycle_time - spread, cycle_time + spread))
                setup_time = float(step.get("setup_time_seconds") or 0)
                if setup_time > 0:
                    station_event(env.now, "setup_start", chosen, entity_id)
                    yield env.timeout(setup_time)
                    station_event(env.now, "setup_end", chosen, entity_id)
                station_event(env.now, "finish", chosen, entity_id)
                station_busy[chosen] += setup_time + cycle_time
                yield env.timeout(cycle_time)
                completions[chosen] += 1

                downstream_buffer = None
                for edge in edges:
                    if edge["source"] == chosen:
                        target = edge["target"]
                        if target in stores:
                            downstream_buffer = stores[target]
                        elif target in machine_nodes and step_index < len(recipe["steps"]) - 1:
                            next_station = target
                            break
                if downstream_buffer is not None:
                    blocked_start = env.now
                    try:
                        yield downstream_buffer.put(entity_id)
                    except Exception:
                        raise
                    blocked = env.now - blocked_start
                    if blocked > 0:
                        station_blocked[chosen] += blocked
                        station_event(env.now, "blocked", chosen, entity_id, {"reason": "finite_buffer_backpressure"})
        station_event(env.now, "finish", "sink", entity_id)

    for entity_number in range(entity_count):
        env.process(process_entity(entity_number + 1))

    env.run(until=horizon)
    completed = sum(completions.values()) // max(1, len(completions))
    throughput = completed / horizon if horizon > 0 else 0.0
    metrics = {
        "throughput_per_second": throughput,
        "cycle_completions": completions,
        "station_utilization": {
            station: (busy / horizon) if horizon > 0 else 0.0
            for station, busy in station_busy.items()
        },
        "station_state_duration": {
            station: {
                "busy": station_busy[station],
                "idle": max(0.0, station_idle[station]),
                "blocked": station_blocked[station],
                "starved": station_starved[station],
                "down": 0.0,
                "setup": 0.0,
                "off_shift": 0.0,
            }
            for station in machine_nodes
        },
        "queue_wait_seconds": {
            station: {
                "count": len(values),
                "mean": (sum(values) / len(values)) if values else 0.0,
                "min": min(values) if values else 0.0,
                "max": max(values) if values else 0.0,
            }
            for station, values in queue_wait.items()
        },
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "snapshot": snapshot,
        "metrics": metrics,
        "events": events,
        "event_log_hash": _canonical_hash(events),
        "snapshot_hash": _canonical_hash(snapshot),
        "data_kind": "simulated",
    }
    if settings is not None and len(json.dumps(payload, default=str).encode()) > settings.simulation_max_event_log_bytes:
        raise RuntimeError("SIMULATION_EVENT_LOG_LIMIT: The configured event-log byte limit was exceeded.")
    return payload
