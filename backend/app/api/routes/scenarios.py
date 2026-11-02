import hashlib
import json
import math
import statistics
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Literal

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.routes.auth import Principal, get_current_principal, require_csrf, require_roles
from app.core.config import get_settings
from app.db.client import get_database
from app.simulation.engine import (
    SimulationValidationError,
    build_run_snapshot,
    simulate,
    validate_snapshot,
)

router = APIRouter(dependencies=[Depends(require_csrf)])
CAN_EDIT = ("owner", "administrator", "engineer")
SUPPORTED_DELTAS = {
    "routing",
    "parallel_equipment",
    "shifts",
    "batch_sizes",
    "downtime",
    "material_delays",
    "demand_shocks",
}


class ModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Delta(ModelRequest):
    type: Literal[
        "routing", "parallel_equipment", "shifts", "batch_sizes",
        "downtime", "material_delays", "demand_shocks",
    ]
    station_id: str | None = Field(default=None, max_length=128)
    operation: str | None = Field(default=None, max_length=32)
    resource_quantity: int | None = Field(default=None, ge=1, le=1000)
    batch_size: int | None = Field(default=None, ge=1, le=100000)
    edge: dict[str, Any] | None = None
    changes: dict[str, Any] | None = None


class Candidate(ModelRequest):
    name: str = Field(min_length=1, max_length=160)
    deltas: list[Delta] = Field(min_length=1, max_length=100)


class CreateScenarioRequest(ModelRequest):
    line_id: str = Field(min_length=1, max_length=128)
    line_version: int = Field(ge=1)
    recipe_id: str = Field(min_length=1, max_length=128)
    product_id: str = Field(min_length=1, max_length=128)
    entity_count: int = Field(default=100, ge=1, le=100000)
    simulated_time_seconds: float = Field(default=3600, gt=0, le=31536000)
    seed: int = Field(default=42, ge=0, le=2147483647)
    candidates: list[Candidate] = Field(min_length=1, max_length=20)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class CreateComparisonRequest(ModelRequest):
    scenario_id: str = Field(min_length=1, max_length=128)
    replications: int = Field(default=20, ge=1, le=100)
    seed: int = Field(default=42, ge=0, le=2147483647)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class CreateChaosProfileRequest(ModelRequest):
    profile_key: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    intensity: float = Field(gt=0, le=1)
    duration_seconds: float = Field(gt=0, le=86400)
    seed: int = Field(default=42, ge=0, le=2147483647)
    fault_types: list[Literal[
        "machine_failure", "extended_repair", "material_outage",
        "demand_spike", "shift_loss",
    ]] = Field(min_length=1, max_length=5)


class OptimizationRequest(ModelRequest):
    line_id: str = Field(min_length=1, max_length=128)
    line_version: int = Field(ge=1)
    recipe_id: str = Field(min_length=1, max_length=128)
    product_id: str = Field(min_length=1, max_length=128)
    objective: Literal["throughput"] = "throughput"
    max_resources: int = Field(default=20, ge=1, le=1000)
    max_budget: float | None = Field(default=None, gt=0, le=1e12)
    resource_cost: float | None = Field(default=None, gt=0, le=1e9)
    cost_currency: str | None = Field(default=None, min_length=3, max_length=12)


def _object_id(value: str, label: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=404, detail=f"{label} not found.")
    return ObjectId(value)


def _serialize(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {
            ("id" if key == "_id" else key): _serialize(item)
            for key, item in value.items()
        }
    return value


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _derived_seed(comparison_id: str, arm_id: str, replication: int) -> int:
    digest = hashlib.sha256(
        f"{comparison_id}:{arm_id}:{replication}".encode()
    ).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def _validation_error(code: str, path: str, message: str, action: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message, "action": action}


def apply_delta(snapshot: dict[str, Any], delta: Delta) -> tuple[dict[str, Any], list[dict[str, str]]]:
    candidate = deepcopy(snapshot)
    model = candidate["model"]
    nodes = model["layout"]["nodes"]
    edges = model["layout"]["edges"]
    errors: list[dict[str, str]] = []
    node_ids = {node["id"] for node in nodes}

    if delta.type == "routing":
        edge = delta.edge or {}
        operation = delta.operation or "replace"
        if operation == "add":
            source, target = edge.get("source"), edge.get("target")
            if source not in node_ids or target not in node_ids:
                errors.append(_validation_error(
                    "routing_to_missing_station", "deltas.routing.edge",
                    "Routing edge references a nonexistent station.",
                    "Set edge.source and edge.target to existing station IDs.",
                ))
            else:
                edge_id = edge.get("id") or f"scenario-edge-{uuid.uuid4().hex[:8]}"
                edges.append({
                    "id": edge_id,
                    "source": source,
                    "target": target,
                    "source_handle": edge.get("source_handle", "out"),
                    "target_handle": edge.get("target_handle", "in"),
                    "route_kind": edge.get("route_kind", "normal"),
                })
        elif operation == "remove":
            edge_id = edge.get("id")
            if not edge_id:
                errors.append(_validation_error(
                    "malformed_routing_delta", "deltas.routing.edge.id",
                    "A routing removal requires an edge ID.",
                    "Provide the existing edge.id to remove.",
                ))
            else:
                edges[:] = [item for item in edges if item.get("id") != edge_id]
        else:
            edge_id = edge.get("id")
            match = next((item for item in edges if item.get("id") == edge_id), None)
            if match is None:
                errors.append(_validation_error(
                    "unknown_routing_edge", "deltas.routing.edge.id",
                    "The routing edge was not found in the pinned line.",
                    "Use an existing edge ID or operation='add'.",
                ))
            else:
                for key in ("source", "target", "source_handle", "target_handle", "route_kind"):
                    if key in edge:
                        match[key] = edge[key]
                if match["source"] not in node_ids or match["target"] not in node_ids:
                    errors.append(_validation_error(
                        "routing_to_missing_station", "deltas.routing.edge",
                        "The changed routing references a nonexistent station.",
                        "Set source and target to existing station IDs.",
                    ))

    elif delta.type == "parallel_equipment":
        if not delta.station_id or delta.station_id not in node_ids:
            errors.append(_validation_error(
                "unknown_station", "deltas.parallel_equipment.station_id",
                "The requested station is not present in the pinned line.",
                "Use an existing machine node ID.",
            ))
        else:
            node = next(item for item in nodes if item["id"] == delta.station_id)
            if node.get("type") != "machine":
                errors.append(_validation_error(
                    "invalid_resource_station", "deltas.parallel_equipment.station_id",
                    "Parallel equipment can only be assigned to a machine station.",
                    "Choose a station with type='machine'.",
                ))
            elif delta.resource_quantity is None or delta.resource_quantity < 1:
                errors.append(_validation_error(
                    "invalid_resource_quantity", "deltas.parallel_equipment.resource_quantity",
                    "Resource quantity must be a positive integer.",
                    "Set resource_quantity to at least 1.",
                ))
            else:
                node["resource_quantity"] = delta.resource_quantity

    elif delta.type == "batch_sizes":
        if delta.batch_size is None:
            errors.append(_validation_error(
                "invalid_batch_size", "deltas.batch_sizes.batch_size",
                "Batch size is required.",
                "Set a positive batch_size.",
            ))
        else:
            changed = False
            for recipe in model.get("recipes", []):
                for step in recipe.get("steps", []):
                    if not delta.station_id or delta.station_id in step.get("machine_node_ids", []):
                        step["batch_size"] = delta.batch_size
                        changed = True
            if not changed:
                errors.append(_validation_error(
                    "unknown_station", "deltas.batch_sizes.station_id",
                    "No process step uses the requested station.",
                    "Choose a machine ID assigned to a recipe step.",
                ))

    elif delta.type == "shifts":
        if not isinstance(delta.changes, dict):
            errors.append(_validation_error(
                "malformed_shift_delta", "deltas.shifts.changes",
                "Shift changes must be an explicit object.",
                "Provide shifts and an IANA timezone.",
            ))
        else:
            candidate["factory_calendar"] = deepcopy(delta.changes)
            candidate["assumptions"]["shifts"] = "scenario_calendar_applied"

    elif delta.type in {"downtime", "material_delays", "demand_shocks"}:
        if not isinstance(delta.changes, dict):
            errors.append(_validation_error(
                f"malformed_{delta.type}_delta", f"deltas.{delta.type}.changes",
                f"{delta.type.replace('_', ' ').title()} requires explicit parameters.",
                "Provide bounded, documented delta parameters.",
            ))
        else:
            candidate["assumptions"]["scenario_delta_types"] = list(
                set(candidate["assumptions"].get("scenario_delta_types", []) + [delta.type])
            )
            candidate["assumptions"][delta.type] = deepcopy(delta.changes)

    if delta.type not in SUPPORTED_DELTAS:
        errors.append(_validation_error(
            "unsupported_delta_type", "deltas.type",
            "This scenario delta type is unsupported.",
            "Use one of the documented delta types.",
        ))
    return candidate, errors


def _build_baseline(
    line_id: str,
    version: int,
    recipe_id: str,
    product_id: str,
    entity_count: int,
    simulated_time_seconds: float,
    seed: int,
    principal: Principal,
) -> tuple[dict[str, Any], dict[str, Any]]:
    db = get_database()
    line = db.production_lines.find_one({
        "_id": _object_id(line_id, "Production line"),
        "organization_id": principal.organization_id,
        "archived_at": None,
    })
    if line is None:
        raise HTTPException(status_code=404, detail="Production line not found.")
    line_version = db.production_line_versions.find_one({
        "organization_id": principal.organization_id,
        "line_id": line["_id"],
        "version": version,
    })
    if line_version is None:
        raise HTTPException(status_code=404, detail="Production line version not found.")
    machine_ids = {
        node["machine_id"]
        for node in line_version["model"].get("layout", {}).get("nodes", [])
        if node.get("type") == "machine" and node.get("machine_id")
    }
    machines = list(db.machines.find({
        "_id": {"$in": [ObjectId(machine_id) for machine_id in machine_ids if ObjectId.is_valid(machine_id)]},
        "organization_id": principal.organization_id,
        "archived_at": None,
    })) if machine_ids else []
    factory = db.factories.find_one({
        "_id": line.get("factory_id"),
        "organization_id": principal.organization_id,
        "archived_at": None,
    })
    snapshot = build_run_snapshot(
        line_version={"model": line_version["model"]},
        line_id=line_id,
        version=version,
        machines=machines,
        factory=factory,
        recipe_id=recipe_id,
        product_id=product_id,
        seed=seed,
        entity_count=entity_count,
        simulated_time_seconds=simulated_time_seconds,
        assumptions={"distribution": "deterministic", "data_kind": "simulated"},
    )
    errors = validate_snapshot(snapshot)
    if errors:
        raise HTTPException(status_code=422, detail={"code": "SCENARIO_VALIDATION_FAILED", "errors": errors})
    return snapshot, line_version


@router.post("/simulation/scenarios", status_code=201)
def create_scenario(
    payload: CreateScenarioRequest,
    principal: Principal = Depends(require_roles(*CAN_EDIT)),
) -> dict[str, Any]:
    db = get_database()
    if payload.idempotency_key:
        existing = db.scenarios.find_one({
            "organization_id": principal.organization_id,
            "idempotency_key": payload.idempotency_key,
        })
        if existing is not None:
            return {"scenario": _serialize(existing)}
    baseline, _ = _build_baseline(
        payload.line_id, payload.line_version, payload.recipe_id, payload.product_id,
        payload.entity_count, payload.simulated_time_seconds, payload.seed, principal,
    )
    candidate_records: list[dict[str, Any]] = []
    all_errors: list[dict[str, Any]] = []
    for candidate_index, candidate in enumerate(payload.candidates):
        resolved = deepcopy(baseline)
        candidate_errors: list[dict[str, str]] = []
        for delta in candidate.deltas:
            resolved, delta_errors = apply_delta(resolved, delta)
            candidate_errors.extend(delta_errors)
        if candidate_errors:
            all_errors.append({"candidate": candidate.name, "errors": candidate_errors})
            continue
        validation_errors = validate_snapshot(resolved)
        if validation_errors:
            all_errors.append({"candidate": candidate.name, "errors": validation_errors})
            continue
        candidate_records.append({
            "candidate_id": uuid.uuid4().hex,
            "name": candidate.name,
            "deltas": [delta.model_dump() for delta in candidate.deltas],
            "delta_hash": _hash([delta.model_dump() for delta in candidate.deltas]),
            "resolved_snapshot": resolved,
            "resolved_snapshot_hash": _hash(resolved),
            "kind": "simulated",
        })
    if all_errors:
        raise HTTPException(
            status_code=422,
            detail={"code": "SCENARIO_DELTA_VALIDATION_FAILED", "errors": all_errors},
        )
    now = datetime.now(UTC)
    record = {
        "scenario_id": uuid.uuid4().hex,
        "organization_id": principal.organization_id,
        "created_by": principal.user_id,
        "created_at": now,
        "updated_at": now,
        "line_id": payload.line_id,
        "line_version": payload.line_version,
        "recipe_id": payload.recipe_id,
        "product_id": payload.product_id,
        "entity_count": payload.entity_count,
        "simulated_time_seconds": payload.simulated_time_seconds,
        "seed": payload.seed,
        "baseline_snapshot": baseline,
        "baseline_snapshot_hash": _hash(baseline),
        "candidates": candidate_records,
        "kind": "simulated",
        "chaos": False,
        "immutable": True,
        "result_hash": None,
    }
    if payload.idempotency_key:
        record["idempotency_key"] = payload.idempotency_key
    db.scenarios.insert_one(record)
    return {"scenario": _serialize(record)}


def _metric_spread(values: list[float]) -> dict[str, float]:
    return {
        "mean": statistics.fmean(values) if values else 0.0,
        "min": min(values) if values else 0.0,
        "max": max(values) if values else 0.0,
        "stddev": statistics.pstdev(values) if len(values) > 1 else 0.0,
    }


def _paired_throughput(values: list[float]) -> dict[str, Any]:
    if len(values) < 2:
        return {"mean": values[0] if values else 0.0, "ci95": [values[0] if values else 0.0, values[0] if values else 0.0], "difference_distinguishable": False}
    mean = statistics.fmean(values)
    spread = statistics.stdev(values)
    margin = 1.96 * spread / math.sqrt(len(values))
    return {
        "mean": mean,
        "ci95": [mean - margin, mean + margin],
        "difference_distinguishable": abs(mean) > margin,
    }


@router.post("/simulation/comparisons", status_code=201)
def create_comparison(
    payload: CreateComparisonRequest,
    principal: Principal = Depends(require_roles(*CAN_EDIT)),
) -> dict[str, Any]:
    db = get_database()
    settings = get_settings()
    if payload.replications > settings.scenario_max_replications:
        raise HTTPException(status_code=422, detail={
            "code": "REPLICATION_LIMIT",
            "message": f"Replications exceed the configured limit of {settings.scenario_max_replications}.",
            "action": "Reduce the replication count.",
        })
    if payload.idempotency_key:
        existing = db.scenario_comparisons.find_one({
            "organization_id": principal.organization_id,
            "idempotency_key": payload.idempotency_key,
        })
        if existing is not None:
            return {"comparison": _serialize(existing)}
    scenario = db.scenarios.find_one({
        "organization_id": principal.organization_id,
        "scenario_id": payload.scenario_id,
    })
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found.")

    comparison_id = uuid.uuid4().hex
    baseline_values: list[dict[str, Any]] = []
    baseline_runs: list[str] = []
    for replication in range(payload.replications):
        snapshot = deepcopy(scenario["baseline_snapshot"])
        snapshot["seed"] = _derived_seed(comparison_id, "baseline", replication)
        result = simulate(snapshot, settings)
        baseline_values.append(result["metrics"])
        run_id = uuid.uuid4().hex
        baseline_runs.append(run_id)
        db.scenario_runs.insert_one({
            "organization_id": principal.organization_id,
            "comparison_id": comparison_id,
            "scenario_id": scenario["scenario_id"],
            "arm": "baseline",
            "candidate_id": None,
            "replication": replication,
            "run_id": run_id,
            "snapshot": snapshot,
            "snapshot_hash": result["snapshot_hash"],
            "event_log_hash": result["event_log_hash"],
            "metrics": result["metrics"],
            "kind": "simulated",
        })

    candidate_results: list[dict[str, Any]] = []
    for candidate in scenario["candidates"]:
        candidate_values: list[dict[str, Any]] = []
        candidate_runs: list[str] = []
        paired_deltas: list[float] = []
        bottlenecks: list[str] = []
        for replication in range(payload.replications):
            snapshot = deepcopy(candidate["resolved_snapshot"])
            snapshot["seed"] = _derived_seed(comparison_id, candidate["candidate_id"], replication)
            result = simulate(snapshot, settings)
            candidate_values.append(result["metrics"])
            run_id = uuid.uuid4().hex
            candidate_runs.append(run_id)
            db.scenario_runs.insert_one({
                "organization_id": principal.organization_id,
                "comparison_id": comparison_id,
                "scenario_id": scenario["scenario_id"],
                "arm": candidate["name"],
                "candidate_id": candidate["candidate_id"],
                "replication": replication,
                "run_id": run_id,
                "snapshot": snapshot,
                "snapshot_hash": result["snapshot_hash"],
                "event_log_hash": result["event_log_hash"],
                "metrics": result["metrics"],
                "kind": "simulated",
            })
            baseline_throughput = float(baseline_values[replication]["throughput_per_second"])
            paired_deltas.append(float(result["metrics"]["throughput_per_second"]) - baseline_throughput)
            utilization = result["metrics"]["station_utilization"]
            bottlenecks.append(max(utilization, key=utilization.get) if utilization else "none")

        baseline_throughputs = [
            float(value["throughput_per_second"]) for value in baseline_values
        ]
        candidate_throughputs = [
            float(value["throughput_per_second"]) for value in candidate_values
        ]
        frequency: dict[str, float] = {}
        for station in set(bottlenecks):
            frequency[station] = bottlenecks.count(station) / payload.replications
        candidate_results.append({
            "candidate_id": candidate["candidate_id"],
            "candidate_name": candidate["name"],
            "delta_hash": candidate["delta_hash"],
            "resolved_snapshot_hash": candidate["resolved_snapshot_hash"],
            "run_ids": candidate_runs,
            "kind": "simulated",
            "baseline_throughput": _metric_spread(baseline_throughputs),
            "candidate_throughput": _metric_spread(candidate_throughputs),
            "paired_throughput_difference": _paired_throughput(paired_deltas),
            "trade_offs": {"throughput": _metric_spread(paired_deltas)},
            "bottleneck_frequency": frequency,
        })

    result = {
        "schema_version": 1,
        "comparison_id": comparison_id,
        "organization_id": principal.organization_id,
        "scenario_id": scenario["scenario_id"],
        "line_id": scenario["line_id"],
        "line_version": scenario["line_version"],
        "baseline_snapshot_hash": scenario["baseline_snapshot_hash"],
        "baseline_run_ids": baseline_runs,
        "replication_count": payload.replications,
        "paired_seed_method": "SHA256(comparison_id + ':' + arm_id + ':' + replication)[0:4] & 0x7fffffff",
        "confidence_interval_method": "paired differences; normal approximation; 95% CI; independence of replications assumed",
        "engine": {"translator": "realityloop-simpy-v1", "simpy": "4.1.1"},
        "kind": "simulated",
        "candidates": candidate_results,
        "cost_energy": {"status": "inputs_not_provided", "inputs": None},
        "created_by": principal.user_id,
        "created_at": datetime.now(UTC),
        "immutable": True,
    }
    result_hash = _hash(result)
    result["result_hash"] = result_hash
    record = {
        **result,
        "status": "completed",
    }
    if payload.idempotency_key:
        record["idempotency_key"] = payload.idempotency_key
    db.scenario_comparisons.insert_one(record)
    return {"comparison": _serialize(record)}


@router.get("/simulation/scenarios/{scenario_id}")
def get_scenario(
    scenario_id: str,
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    record = get_database().scenarios.find_one({
        "organization_id": principal.organization_id,
        "scenario_id": scenario_id,
    })
    if record is None:
        raise HTTPException(status_code=404, detail="Scenario not found.")
    return {"scenario": _serialize(record)}


@router.get("/simulation/comparisons/{comparison_id}")
def get_comparison(
    comparison_id: str,
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    record = get_database().scenario_comparisons.find_one({
        "organization_id": principal.organization_id,
        "comparison_id": comparison_id,
    })
    if record is None:
        raise HTTPException(status_code=404, detail="Comparison not found.")
    return {"comparison": _serialize(record)}


@router.post("/simulation/chaos-profiles", status_code=201)
def create_chaos_profile(
    payload: CreateChaosProfileRequest,
    principal: Principal = Depends(require_roles(*CAN_EDIT)),
) -> dict[str, Any]:
    db = get_database()
    settings = get_settings()
    if payload.duration_seconds > settings.scenario_solver_max_seconds * 2:
        raise HTTPException(status_code=422, detail={
            "code": "CHAOS_DURATION_LIMIT",
            "message": "Chaos duration exceeds the configured safety bound.",
            "action": "Reduce duration_seconds or use the documented limit.",
        })
    profile = {
        "organization_id": principal.organization_id,
        "profile_key": payload.profile_key,
        "version": 1,
        "intensity": payload.intensity,
        "duration_seconds": payload.duration_seconds,
        "seed": payload.seed,
        "fault_types": payload.fault_types,
        "simulation_only": True,
        "kind": "simulated",
        "created_by": principal.user_id,
        "created_at": datetime.now(UTC),
    }
    result = db.chaos_profiles.update_one(
        {
            "organization_id": principal.organization_id,
            "profile_key": payload.profile_key,
            "version": 1,
        },
        {"$setOnInsert": profile},
        upsert=True,
    )
    stored = db.chaos_profiles.find_one({
        "organization_id": principal.organization_id,
        "profile_key": payload.profile_key,
        "version": 1,
    })
    return {"profile": _serialize(stored), "simulation_only": True}


@router.get("/simulation/chaos-profiles")
def list_chaos_profiles(
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    profiles = list(get_database().chaos_profiles.find({
        "organization_id": principal.organization_id,
    }).sort("created_at", -1).limit(limit))
    return {"profiles": [_serialize(profile) for profile in profiles]}


@router.post("/simulation/optimizations")
def optimize_scenario(
    payload: OptimizationRequest,
    principal: Principal = Depends(require_roles(*CAN_EDIT)),
) -> dict[str, Any]:
    settings = get_settings()
    if payload.max_budget is not None and (
        payload.resource_cost is None or payload.cost_currency is None
    ):
        raise HTTPException(status_code=422, detail={
            "code": "MISSING_COST_INPUTS",
            "message": "Budget optimization requires explicit resource cost and currency.",
            "action": "Provide resource_cost and cost_currency, or omit max_budget.",
        })
    baseline, _ = _build_baseline(
        payload.line_id,
        payload.line_version,
        payload.recipe_id,
        payload.product_id,
        100,
        3600,
        42,
        principal,
    )
    machine_nodes = [
        node for node in baseline["model"]["layout"]["nodes"]
        if node.get("type") == "machine"
    ]
    candidates: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    if not machine_nodes:
        errors.append(_validation_error(
            "missing_machine_station", "model.layout.nodes",
            "The pinned line contains no machine stations.",
            "Add a machine station to the saved line version.",
        ))

    resource_budget = payload.max_resources
    if machine_nodes:
        # Bounded enumeration: quantity allocations range from the current
        # quantity through the remaining configured resource budget.
        remaining = max(1, resource_budget - len(machine_nodes))
        allocations = [(1, min(remaining + 1, 4))]
        for machine_index, node in enumerate(machine_nodes[:settings.scenario_solver_max_candidates]):
            station_id = node["id"]
            current = int(node.get("resource_quantity", 1))
            for quantity in range(current, current + allocations[0][1]):
                candidate_snapshot = deepcopy(baseline)
                candidate_node = next(
                    item for item in candidate_snapshot["model"]["layout"]["nodes"]
                    if item["id"] == station_id
                )
                candidate_node["resource_quantity"] = quantity
                candidate_snapshot["seed"] = 42
                validation_errors = validate_snapshot(candidate_snapshot, settings)
                if validation_errors:
                    errors.extend(validation_errors)
                    continue
                if payload.max_budget is not None:
                    cost = quantity * payload.resource_cost
                    if cost > payload.max_budget:
                        errors.append(_validation_error(
                            "budget_limit_exceeded",
                            f"machine_nodes.{station_id}",
                            "The resource quantity exceeds the explicit budget.",
                            "Reduce the quantity or increase max_budget with approved inputs.",
                        ))
                        continue
                result = simulate(candidate_snapshot, settings)
                candidates.append({
                    "station_id": station_id,
                    "resource_quantity": quantity,
                    "resolved_snapshot_hash": _hash(candidate_snapshot),
                    "kind": "simulated",
                    "simulator_validation": {
                        "status": "validated",
                        "throughput_per_second": result["metrics"]["throughput_per_second"],
                        "event_log_hash": result["event_log_hash"],
                    },
                })
                if len(candidates) >= settings.scenario_solver_max_candidates:
                    break

    status = "feasible" if candidates else ("infeasible" if errors else "limit")
    return {
        "optimization": {
            "schema_version": 1,
            "objective": payload.objective,
            "solver": "bounded_feasible_search_v1",
            "solver_parameters": {
                "max_seconds": settings.scenario_solver_max_seconds,
                "max_candidates": settings.scenario_solver_max_candidates,
            },
            "status": status,
            "candidates": candidates,
            "constraints": {
                "max_resources": resource_budget,
                "max_budget": payload.max_budget,
                "resource_cost": payload.resource_cost,
                "cost_currency": payload.cost_currency,
            },
            "errors": errors,
            "kind": "simulated",
            "no_actuator_writes": True,
        }
    }
