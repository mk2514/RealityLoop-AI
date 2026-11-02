import math
import re
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any, Literal

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from pymongo.errors import DuplicateKeyError

from app.api.routes.auth import (
    Principal,
    get_current_principal,
    require_csrf,
    require_roles,
)
from app.db.client import get_database, get_mongo_client

router = APIRouter(dependencies=[Depends(require_csrf)])
CAN_EDIT_MODELS = ("owner", "administrator", "engineer")
NODE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
MAX_NODES = 200
MAX_EDGES = 500
MAX_TOTAL_STEPS = 1000
MAX_TOTAL_MACHINE_ASSIGNMENTS = 2000
MAX_TOTAL_RESOURCES = 2000


class ModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Position(ModelRequest):
    x: float
    y: float


class FlowNode(ModelRequest):
    id: str
    type: Literal["source", "sink", "machine", "buffer"]
    position: Position
    rotation: int = 0
    label: str = Field(default="", max_length=160)
    machine_id: str | None = None
    required: bool = True
    buffer_capacity: int | None = None


class ReworkRule(ModelRequest):
    condition: str = Field(default="", max_length=500)
    max_revisits: int = 1


class FlowEdge(ModelRequest):
    id: str
    source: str
    target: str
    source_handle: str
    target_handle: str
    route_kind: Literal["normal", "rework"] = "normal"
    rework_rule: ReworkRule | None = None
    transfer_time_seconds: float | None = None
    distance_meters: float | None = None
    speed_meters_per_second: float | None = None


class TransferSettings(ModelRequest):
    use_layout_distance: bool = False
    pixels_per_meter: float = 100.0
    default_speed_meters_per_second: float = 1.0


class LineLayout(ModelRequest):
    nodes: list[FlowNode] = Field(default_factory=list, max_length=MAX_NODES)
    edges: list[FlowEdge] = Field(default_factory=list, max_length=MAX_EDGES)
    transfer_settings: TransferSettings = Field(default_factory=TransferSettings)


class Product(ModelRequest):
    id: str
    name: str = Field(min_length=1, max_length=160)
    sku: str = Field(default="", max_length=120)


class ResourceRequirement(ModelRequest):
    name: str = Field(min_length=1, max_length=120)
    quantity: int


class ProcessStep(ModelRequest):
    id: str
    operation: str = Field(min_length=1, max_length=120)
    machine_node_ids: list[str] = Field(default_factory=list, max_length=MAX_NODES)
    cycle_time_seconds: float | None = None
    setup_time_seconds: float | None = None
    changeover_time_seconds: float | None = None
    batch_size: int | None = None
    operator_count: int | None = None
    resources: list[ResourceRequirement] = Field(default_factory=list, max_length=50)


class Recipe(ModelRequest):
    id: str
    product_id: str
    steps: list[ProcessStep] = Field(default_factory=list, max_length=MAX_NODES)


class ProductionLineModel(ModelRequest):
    schema_version: Literal[1] = 1
    layout: LineLayout = Field(default_factory=LineLayout)
    products: list[Product] = Field(default_factory=list, max_length=50)
    recipes: list[Recipe] = Field(default_factory=list, max_length=100)


class SaveModelRequest(ModelRequest):
    expected_revision: int = Field(ge=0)
    model: ProductionLineModel


def _object_id(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=404, detail="Production line not found.")
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


def _get_line(line_id: ObjectId, organization_id: ObjectId) -> dict[str, Any]:
    line = get_database().production_lines.find_one(
        {
            "_id": line_id,
            "organization_id": organization_id,
            "archived_at": None,
        }
    )
    if line is None:
        raise HTTPException(status_code=404, detail="Production line not found.")
    return line


def _validation_error(code: str, path: str, message: str, action: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message, "action": action}


def validate_line_model(
    model: ProductionLineModel,
    *,
    organization_id: ObjectId,
    line_id: ObjectId,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    total_steps = sum(len(recipe.steps) for recipe in model.recipes)
    total_machine_assignments = sum(
        len(step.machine_node_ids)
        for recipe in model.recipes
        for step in recipe.steps
    )
    total_resources = sum(
        len(step.resources) for recipe in model.recipes for step in recipe.steps
    )
    if (
        total_steps > MAX_TOTAL_STEPS
        or total_machine_assignments > MAX_TOTAL_MACHINE_ASSIGNMENTS
        or total_resources > MAX_TOTAL_RESOURCES
    ):
        return {
            "valid": False,
            "errors": [
                _validation_error(
                    "model_complexity_limit",
                    "recipes",
                    "This production model exceeds the supported recipe complexity.",
                    "Reduce the total process steps, machine assignments, or resources and validate again.",
                )
            ],
            "transfer_times": [],
        }
    nodes = model.layout.nodes
    edges = model.layout.edges
    node_by_id = {node.id: node for node in nodes}
    if len(node_by_id) != len(nodes):
        errors.append(
            _validation_error(
                "duplicate_node_id",
                "layout.nodes",
                "Node IDs must be unique.",
                "Assign a distinct ID to each station.",
            )
        )
    edge_ids = [edge.id for edge in edges]
    if len(set(edge_ids)) != len(edge_ids):
        errors.append(
            _validation_error(
                "duplicate_edge_id",
                "layout.edges",
                "Edge IDs must be unique.",
                "Remove the duplicate connection or assign it a new ID.",
            )
        )

    for node in nodes:
        if not NODE_ID_PATTERN.fullmatch(node.id):
            errors.append(
                _validation_error(
                    "invalid_node_id",
                    f"layout.nodes.{node.id}",
                    "Node IDs may contain letters, numbers, underscores, and hyphens.",
                    "Use a short unique node ID with only supported characters.",
                )
            )
        if not math.isfinite(node.position.x) or not math.isfinite(node.position.y):
            errors.append(
                _validation_error(
                    "invalid_position",
                    f"layout.nodes.{node.id}.position",
                    "Station layout coordinates must be finite numbers.",
                    "Move this station to a valid position on the canvas.",
                )
            )
        if not 0 <= node.rotation < 360:
            errors.append(
                _validation_error(
                    "invalid_rotation",
                    f"layout.nodes.{node.id}.rotation",
                    "Station rotation must be between 0 and 359 degrees.",
                    "Set rotation to a whole-number angle in that range.",
                )
            )
        if node.type == "machine" and not node.machine_id:
            errors.append(
                _validation_error(
                    "machine_reference_required",
                    f"layout.nodes.{node.id}.machine_id",
                    "Machine stations must reference a machine asset.",
                    "Select an active machine from this production line.",
                )
            )
        if node.type != "machine" and node.machine_id is not None:
            errors.append(
                _validation_error(
                    "unexpected_machine_reference",
                    f"layout.nodes.{node.id}.machine_id",
                    "Only machine stations can reference a machine asset.",
                    "Remove the machine reference or change this node to a machine station.",
                )
            )
        if node.type == "buffer" and (
            node.buffer_capacity is None or node.buffer_capacity <= 0
        ):
            errors.append(
                _validation_error(
                    "invalid_buffer_capacity",
                    f"layout.nodes.{node.id}.buffer_capacity",
                    "Buffer capacity must be a finite positive whole number.",
                    "Set capacity to at least one unit.",
                )
            )
        if node.type != "buffer" and node.buffer_capacity is not None:
            errors.append(
                _validation_error(
                    "unexpected_buffer_capacity",
                    f"layout.nodes.{node.id}.buffer_capacity",
                    "Only buffer nodes can define a buffer capacity.",
                    "Remove this value or change the node type to buffer.",
                )
            )

    transfer_settings = model.layout.transfer_settings
    for field_name, value, label in (
        ("pixels_per_meter", transfer_settings.pixels_per_meter, "Pixels per meter"),
        (
            "default_speed_meters_per_second",
            transfer_settings.default_speed_meters_per_second,
            "Default transfer speed",
        ),
    ):
        if not math.isfinite(value) or value <= 0:
            errors.append(
                _validation_error(
                    "invalid_transfer_setting",
                    f"layout.transfer_settings.{field_name}",
                    f"{label} must be a finite positive number.",
                    "Enter a value greater than zero.",
                )
            )

    sources = [node for node in nodes if node.type == "source"]
    sinks = [node for node in nodes if node.type == "sink"]
    if len(sources) != 1:
        errors.append(
            _validation_error(
                "source_count",
                "layout.nodes",
                f"Exactly one source node is required; found {len(sources)}.",
                "Add one source node and remove any extra source nodes.",
            )
        )
    if len(sinks) != 1:
        errors.append(
            _validation_error(
                "sink_count",
                "layout.nodes",
                f"Exactly one sink node is required; found {len(sinks)}.",
                "Add one sink node and remove any extra sink nodes.",
            )
        )

    machines: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if node.type != "machine":
            continue
        try:
            machine_id = ObjectId(node.machine_id)
        except (TypeError, ValueError):
            machine_id = None
        machine = (
            get_database().machines.find_one(
                {
                    "_id": machine_id,
                    "organization_id": organization_id,
                    "line_id": line_id,
                    "archived_at": None,
                }
            )
            if machine_id is not None
            else None
        )
        if machine is None:
            errors.append(
                _validation_error(
                    "machine_unavailable",
                    f"layout.nodes.{node.id}.machine_id",
                    "This machine is missing, archived, or belongs to another production line.",
                    "Choose an active machine from this production line.",
                )
            )
        else:
            machines[node.id] = machine

    forward: dict[str, set[str]] = defaultdict(set)
    reverse: dict[str, set[str]] = defaultdict(set)
    normal_forward: dict[str, set[str]] = defaultdict(set)
    indegree = {node.id: 0 for node in nodes}
    seen_connections: set[tuple[str, str]] = set()
    for index, edge in enumerate(edges):
        path = f"layout.edges.{index}"
        if not NODE_ID_PATTERN.fullmatch(edge.id):
            errors.append(
                _validation_error(
                    "invalid_edge_id",
                    f"{path}.id",
                    "Edge IDs may contain letters, numbers, underscores, and hyphens.",
                    "Use a short unique connection ID with only supported characters.",
                )
            )
        source = node_by_id.get(edge.source)
        target = node_by_id.get(edge.target)
        if source is None or target is None:
            errors.append(
                _validation_error(
                    "missing_endpoint",
                    path,
                    "A connection references a node that is not in this model.",
                    "Reconnect it to existing nodes or delete the dangling connection.",
                )
            )
            continue
        connection = (source.id, target.id)
        if connection in seen_connections:
            errors.append(
                _validation_error(
                    "duplicate_connection",
                    path,
                    "Only one connection is allowed between a pair of stations.",
                    "Remove the duplicate connection.",
                )
            )
            continue
        seen_connections.add(connection)
        if source.id == target.id:
            errors.append(
                _validation_error(
                    "self_connection",
                    path,
                    "A station cannot connect directly to itself.",
                    "Connect this station to a different station.",
                )
            )
        if edge.route_kind == "rework":
            if edge.rework_rule is None or not edge.rework_rule.condition.strip():
                errors.append(
                    _validation_error(
                        "missing_rework_rule",
                        f"{path}.rework_rule",
                        "Intentional rework routes require an explicit routing condition.",
                        "Describe the condition that sends work back for rework.",
                    )
                )
            elif not 1 <= edge.rework_rule.max_revisits <= 100:
                errors.append(
                    _validation_error(
                        "invalid_rework_limit",
                        f"{path}.rework_rule.max_revisits",
                        "Maximum rework revisits must be between 1 and 100.",
                        "Set a finite positive revisit limit.",
                    )
                )
        elif edge.rework_rule is not None:
            errors.append(
                _validation_error(
                    "unexpected_rework_rule",
                    f"{path}.rework_rule",
                    "A rework rule is attached to a normal route.",
                    "Mark this as a rework route or remove its rework rule.",
                )
            )
        if edge.transfer_time_seconds is not None and (
            not math.isfinite(edge.transfer_time_seconds) or edge.transfer_time_seconds <= 0
        ):
            errors.append(
                _validation_error(
                    "invalid_transfer_time",
                    f"{path}.transfer_time_seconds",
                    "Transfer time must be a finite positive number.",
                    "Enter a duration greater than zero or clear the setting.",
                )
            )
        if edge.distance_meters is not None and (
            not math.isfinite(edge.distance_meters) or edge.distance_meters <= 0
        ):
            errors.append(
                _validation_error(
                    "invalid_transfer_distance",
                    f"{path}.distance_meters",
                    "Transfer distance must be a finite positive number.",
                    "Enter a distance greater than zero or clear the setting.",
                )
            )
        if edge.speed_meters_per_second is not None and (
            not math.isfinite(edge.speed_meters_per_second)
            or edge.speed_meters_per_second <= 0
        ):
            errors.append(
                _validation_error(
                    "invalid_transfer_speed",
                    f"{path}.speed_meters_per_second",
                    "Transfer speed must be a finite positive number.",
                    "Enter a speed greater than zero or clear the setting.",
                )
            )
        if edge.transfer_time_seconds is not None and (
            edge.distance_meters is not None or edge.speed_meters_per_second is not None
        ):
            errors.append(
                _validation_error(
                    "conflicting_transfer_settings",
                    path,
                    "Use direct transfer time or distance/speed, not both.",
                    "Keep only one transfer-time calculation method.",
                )
            )
        if (edge.distance_meters is None) != (edge.speed_meters_per_second is None):
            errors.append(
                _validation_error(
                    "incomplete_transfer_assumptions",
                    path,
                    "Transfer distance and speed must be supplied together.",
                    "Enter both values or clear both values.",
                )
            )
        if edge.source_handle != "out" or source.type == "sink":
            errors.append(
                _validation_error(
                    "invalid_output_port",
                    f"{path}.source_handle",
                    f"{source.type.title()} nodes expose an output port named 'out'.",
                    "Reconnect from an available output port.",
                )
            )
        if edge.target_handle != "in" or target.type == "source":
            errors.append(
                _validation_error(
                    "invalid_input_port",
                    f"{path}.target_handle",
                    f"{target.type.title()} nodes expose an input port named 'in'.",
                    "Reconnect to an available input port.",
                )
            )
        forward[source.id].add(target.id)
        reverse[target.id].add(source.id)
        if edge.route_kind != "rework":
            normal_forward[source.id].add(target.id)
            indegree[target.id] += 1

    products = {product.id: product for product in model.products}
    if not products:
        errors.append(
            _validation_error(
                "missing_products",
                "products",
                "The production model has no product definitions.",
                "Add at least one product and an ordered process recipe.",
            )
        )
    if len(products) != len(model.products):
        errors.append(
            _validation_error(
                "duplicate_product_id",
                "products",
                "Product IDs must be unique.",
                "Assign a distinct ID to every product.",
            )
        )
    recipes_by_product: dict[str, int] = defaultdict(int)
    seen_recipe_ids: set[str] = set()
    for recipe_index, recipe in enumerate(model.recipes):
        recipe_path = f"recipes.{recipe_index}"
        if recipe.id in seen_recipe_ids:
            errors.append(
                _validation_error(
                    "duplicate_recipe_id",
                    f"{recipe_path}.id",
                    "Recipe IDs must be unique.",
                    "Assign a distinct ID to each recipe.",
                )
            )
        seen_recipe_ids.add(recipe.id)
        recipes_by_product[recipe.product_id] += 1
        if recipe.product_id not in products:
            errors.append(
                _validation_error(
                    "missing_product",
                    f"{recipe_path}.product_id",
                    "This recipe references a product that does not exist.",
                    "Select an existing product or add the product first.",
                )
            )
        if not recipe.steps:
            product = products.get(recipe.product_id)
            product_name = product.name if product is not None else recipe.product_id
            errors.append(
                _validation_error(
                    "missing_process_steps",
                    f"{recipe_path}.steps",
                    f"Recipe for {product_name} has no process steps.",
                    "Add the ordered operations required to make this product.",
                )
            )
        seen_step_ids: set[str] = set()
        for step_index, step in enumerate(recipe.steps):
            step_path = f"{recipe_path}.steps.{step_index}"
            if step.id in seen_step_ids:
                errors.append(
                    _validation_error(
                        "duplicate_step_id",
                        f"{step_path}.id",
                        "Process-step IDs must be unique within a recipe.",
                        "Assign a distinct ID to each ordered process step.",
                    )
                )
            seen_step_ids.add(step.id)
            if not step.machine_node_ids:
                errors.append(
                    _validation_error(
                        "missing_machine_assignment",
                        f"{step_path}.machine_node_ids",
                        f"Operation '{step.operation}' has no compatible station assigned.",
                        "Assign at least one compatible machine station.",
                    )
                )
            for field_name, value, allow_zero in (
                ("cycle_time_seconds", step.cycle_time_seconds, False),
                ("setup_time_seconds", step.setup_time_seconds, True),
                ("changeover_time_seconds", step.changeover_time_seconds, True),
            ):
                if value is None or not math.isfinite(value) or value < 0 or (value == 0 and not allow_zero):
                    errors.append(
                        _validation_error(
                            "invalid_process_time",
                            f"{step_path}.{field_name}",
                            f"{field_name.replace('_', ' ').title()} must be a finite {'nonnegative' if allow_zero else 'positive'} number.",
                            "Enter a valid duration in seconds.",
                        )
                    )
            if step.batch_size is None or step.batch_size <= 0:
                errors.append(
                    _validation_error(
                        "invalid_batch_size",
                        f"{step_path}.batch_size",
                        "Batch size must be a positive whole number.",
                        "Set the batch size to at least one.",
                    )
                )
            if step.operator_count is None or step.operator_count < 0:
                errors.append(
                    _validation_error(
                        "invalid_operator_count",
                        f"{step_path}.operator_count",
                        "Operator requirements must be zero or a positive whole number.",
                        "Set the operator count to zero or more.",
                    )
                )
            for resource_index, resource in enumerate(step.resources):
                if resource.quantity <= 0:
                    errors.append(
                        _validation_error(
                            "invalid_resource_quantity",
                            f"{step_path}.resources.{resource_index}.quantity",
                            "Resource quantity must be a positive whole number.",
                            "Set the resource quantity to at least one.",
                        )
                    )
            for node_id in step.machine_node_ids:
                node = node_by_id.get(node_id)
                machine = machines.get(node_id)
                if node is None or node.type != "machine":
                    errors.append(
                        _validation_error(
                            "invalid_machine_assignment",
                            f"{step_path}.machine_node_ids",
                            f"'{node_id}' is not a machine station in this model.",
                            "Choose an existing machine station.",
                        )
                    )
                elif machine is not None and step.operation not in machine.get("capabilities", []):
                    errors.append(
                        _validation_error(
                            "incompatible_operation",
                            f"{step_path}.machine_node_ids",
                            f"Machine '{machine['name']}' does not declare capability '{step.operation}'.",
                            "Choose a compatible machine or add the capability in the asset registry.",
                        )
                    )
        for step, next_step in zip(recipe.steps, recipe.steps[1:]):
            for first_node in step.machine_node_ids:
                reachable: set[str] = set()
                pending = deque([first_node])
                while pending:
                    current = pending.popleft()
                    for target_id in forward[current]:
                        if target_id not in reachable:
                            reachable.add(target_id)
                            pending.append(target_id)
                if not any(target_node in reachable for target_node in next_step.machine_node_ids):
                    errors.append(
                        _validation_error(
                            "impossible_recipe_route",
                            f"recipes.{recipe_index}.steps",
                            f"No route connects operation '{step.operation}' to the following operation '{next_step.operation}'.",
                            "Add a directed connection between the assigned stations.",
                        )
                    )
                    break

    for product in model.products:
        if recipes_by_product[product.id] == 0:
            errors.append(
                _validation_error(
                    "missing_recipe",
                    f"products.{product.id}",
                    f"Product '{product.name}' has no process recipe.",
                    "Add an ordered recipe for this product.",
                )
            )
        elif recipes_by_product[product.id] > 1:
            errors.append(
                _validation_error(
                    "duplicate_product_recipe",
                    f"products.{product.id}",
                    f"Product '{product.name}' has more than one recipe.",
                    "Keep one ordered recipe per product.",
                )
            )

    if sources and sinks:
        start_id = sources[0].id
        finish_id = sinks[0].id

        def walk(graph: dict[str, set[str]], start: str) -> set[str]:
            visited: set[str] = set()
            pending = deque([start])
            while pending:
                current = pending.popleft()
                if current in visited:
                    continue
                visited.add(current)
                pending.extend(graph[current] - visited)
            return visited

        from_source = walk(forward, start_id)
        to_sink = walk(reverse, finish_id)
        for node in nodes:
            if node.required and node.id not in from_source:
                errors.append(
                    _validation_error(
                        "disconnected_station",
                        f"layout.nodes.{node.id}",
                        f"Required {node.type} '{node.label or node.id}' cannot be reached from the source.",
                        "Connect this station downstream of the source.",
                    )
                )
            if node.required and node.id not in to_sink:
                errors.append(
                    _validation_error(
                        "dead_end_station",
                        f"layout.nodes.{node.id}",
                        f"Required {node.type} '{node.label or node.id}' has no route to the sink.",
                        "Connect this station to a path that reaches the sink.",
                    )
                )

    queue = deque(node_id for node_id, degree in indegree.items() if degree == 0)
    visited_count = 0
    while queue:
        current = queue.popleft()
        visited_count += 1
        for target in normal_forward[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited_count != len(nodes):
        errors.append(
            _validation_error(
                "unbounded_loop",
                "layout.edges",
                "A routing loop exists without an explicit rework route and visit limit.",
                "Mark an intentional loop connection as rework and define its condition and maximum revisits.",
            )
        )

    transfer_times: list[dict[str, Any]] = []
    for edge in edges:
        if edge.transfer_time_seconds is not None and (
            not math.isfinite(edge.transfer_time_seconds)
            or edge.transfer_time_seconds <= 0
        ):
            transfer_times.append(
                {
                    "edge_id": edge.id,
                    "seconds": None,
                    "method": "invalid_configured_time",
                }
            )
        elif edge.transfer_time_seconds is not None:
            transfer_times.append(
                {"edge_id": edge.id, "seconds": edge.transfer_time_seconds, "method": "configured_time"}
            )
        elif edge.distance_meters is not None and edge.speed_meters_per_second is not None:
            assumptions_valid = (
                math.isfinite(edge.distance_meters)
                and edge.distance_meters > 0
                and math.isfinite(edge.speed_meters_per_second)
                and edge.speed_meters_per_second > 0
            )
            seconds = (
                edge.distance_meters / edge.speed_meters_per_second
                if assumptions_valid
                else None
            )
            if seconds is not None and math.isfinite(seconds) and seconds > 0:
                transfer_times.append(
                    {
                        "edge_id": edge.id,
                        "seconds": seconds,
                        "method": "configured_distance_and_speed",
                    }
                )
            else:
                if assumptions_valid:
                    errors.append(
                        _validation_error(
                            "invalid_derived_transfer",
                            f"layout.edges.{edge.id}",
                            "Transfer distance and speed produce an invalid duration.",
                            "Use finite positive values that produce a finite transfer time.",
                        )
                    )
                transfer_times.append(
                    {
                        "edge_id": edge.id,
                        "seconds": None,
                        "method": "invalid_distance_and_speed",
                    }
                )
        elif model.layout.transfer_settings.use_layout_distance:
            source = node_by_id.get(edge.source)
            target = node_by_id.get(edge.target)
            settings_valid = (
                math.isfinite(model.layout.transfer_settings.pixels_per_meter)
                and model.layout.transfer_settings.pixels_per_meter > 0
                and math.isfinite(
                    model.layout.transfer_settings.default_speed_meters_per_second
                )
                and model.layout.transfer_settings.default_speed_meters_per_second > 0
            )
            if source is not None and target is not None and settings_valid:
                pixels = math.hypot(
                    target.position.x - source.position.x,
                    target.position.y - source.position.y,
                )
                meters = pixels / model.layout.transfer_settings.pixels_per_meter
                seconds = (
                    meters
                    / model.layout.transfer_settings.default_speed_meters_per_second
                )
                if math.isfinite(seconds):
                    transfer_times.append(
                        {
                            "edge_id": edge.id,
                            "seconds": seconds,
                            "method": "derived_from_layout",
                        }
                    )
                else:
                    errors.append(
                        _validation_error(
                            "invalid_derived_transfer",
                            f"layout.edges.{edge.id}",
                            "Layout distance assumptions produce an invalid transfer duration.",
                            "Use valid positions, a positive scale, and a positive transfer speed.",
                        )
                    )
                    transfer_times.append(
                        {
                            "edge_id": edge.id,
                            "seconds": None,
                            "method": "invalid_layout_assumptions",
                        }
                    )
            else:
                transfer_times.append(
                    {
                        "edge_id": edge.id,
                        "seconds": None,
                        "method": "invalid_layout_assumptions",
                    }
                )
        else:
            transfer_times.append(
                {"edge_id": edge.id, "seconds": None, "method": "unspecified"}
            )

    return {
        "valid": not errors,
        "errors": errors,
        "transfer_times": transfer_times,
    }


def _transaction(callback):
    with get_mongo_client().start_session() as session:
        return session.with_transaction(callback)


@router.get("/lines/{line_id}/model")
def get_line_model(
    line_id: str,
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    line_object_id = _object_id(line_id)
    _get_line(line_object_id, principal.organization_id)
    draft = get_database().production_line_models.find_one(
        {"organization_id": principal.organization_id, "line_id": line_object_id}
    )
    if draft is None:
        return {"revision": 0, "model": ProductionLineModel().model_dump(), "updated_at": None}
    return {
        "revision": draft["revision"],
        "model": _serialize(draft["model"]),
        "updated_at": _serialize(draft["updated_at"]),
    }


@router.put("/lines/{line_id}/model")
def save_line_model(
    line_id: str,
    payload: SaveModelRequest,
    principal: Principal = Depends(require_roles(*CAN_EDIT_MODELS)),
) -> dict[str, Any]:
    line_object_id = _object_id(line_id)
    _get_line(line_object_id, principal.organization_id)
    model_document = payload.model.model_dump(mode="python")
    validation = validate_line_model(
        payload.model,
        organization_id=principal.organization_id,
        line_id=line_object_id,
    )
    now = datetime.now(UTC)
    next_revision = payload.expected_revision + 1
    draft_key = {"organization_id": principal.organization_id, "line_id": line_object_id}
    version_document = {
        **draft_key,
        "version": next_revision,
        "model": model_document,
        "validation": validation,
        "created_by": principal.user_id,
        "created_at": now,
    }

    def operation(session):
        if payload.expected_revision == 0:
            get_database().production_line_models.insert_one(
                {
                    **draft_key,
                    "revision": next_revision,
                    "model": model_document,
                    "updated_by": principal.user_id,
                    "updated_at": now,
                },
                session=session,
            )
        else:
            result = get_database().production_line_models.update_one(
                {
                    **draft_key,
                    "revision": payload.expected_revision,
                },
                {
                    "$set": {
                        "revision": next_revision,
                        "model": model_document,
                        "updated_by": principal.user_id,
                        "updated_at": now,
                    }
                },
                session=session,
            )
            if result.modified_count != 1:
                raise HTTPException(
                    status_code=409,
                    detail="This production line changed since you loaded it. Reload before saving.",
                )
        get_database().production_line_versions.insert_one(
            version_document,
            session=session,
        )
        return {
            "revision": next_revision,
            "model": model_document,
            "validation": validation,
            "updated_at": now,
        }

    try:
        return _serialize(_transaction(operation))
    except DuplicateKeyError as error:
        raise HTTPException(
            status_code=409,
            detail="This production line changed since you loaded it. Reload before saving.",
        ) from error


@router.get("/lines/{line_id}/versions")
def list_line_versions(
    line_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    line_object_id = _object_id(line_id)
    _get_line(line_object_id, principal.organization_id)
    versions = get_database().production_line_versions.find(
        {"organization_id": principal.organization_id, "line_id": line_object_id}
    ).sort("version", -1).limit(limit)
    return {
        "versions": [
            {
                "version": version["version"],
                "validation": _serialize(version["validation"]),
                "created_at": _serialize(version["created_at"]),
            }
            for version in versions
        ]
    }


@router.get("/lines/{line_id}/versions/{version}")
def get_line_version(
    line_id: str,
    version: int,
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    line_object_id = _object_id(line_id)
    _get_line(line_object_id, principal.organization_id)
    snapshot = get_database().production_line_versions.find_one(
        {
            "organization_id": principal.organization_id,
            "line_id": line_object_id,
            "version": version,
        }
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Production line version not found.")
    return {
        "version": version,
        "model": _serialize(snapshot["model"]),
        "validation": _serialize(snapshot["validation"]),
        "created_at": _serialize(snapshot["created_at"]),
    }


@router.post("/lines/{line_id}/validate")
def validate_line_model_endpoint(
    line_id: str,
    payload: ProductionLineModel,
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    line_object_id = _object_id(line_id)
    _get_line(line_object_id, principal.organization_id)
    return validate_line_model(
        payload,
        organization_id=principal.organization_id,
        line_id=line_object_id,
    )
