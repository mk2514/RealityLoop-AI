import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  Handle,
  Position,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type NodeProps,
} from "@xyflow/react";
import { lazy, Suspense, useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { ApiError, apiRequest } from "./api";
import type { ReplayEvent, ReviewEdge, ReviewMachine, ReviewNode } from "./Line3DReview";

const Line3DReview = lazy(async () => {
  const module = await import("./Line3DReview");
  return { default: module.Line3DReview };
});
const ReplayControls = lazy(async () => {
  const module = await import("./Line3DReview");
  return { default: module.ReplayControls };
});

type NodeKind = "source" | "sink" | "machine" | "buffer";
type NodeData = {
  label: string;
  machine_id?: string;
  required: boolean;
  buffer_capacity?: number;
  rotation: number;
};
type TransferData = {
  route_kind: "normal" | "rework";
  rework_rule?: { condition: string; max_revisits: number };
  transfer_time_seconds?: number;
  distance_meters?: number;
  speed_meters_per_second?: number;
};
type FlowNode = Node<NodeData, NodeKind>;
type FlowEdge = Edge<TransferData>;
type Product = { id: string; name: string; sku: string };
type ResourceRequirement = { name: string; quantity: number };
type ProcessStep = {
  id: string;
  operation: string;
  machine_node_ids: string[];
  cycle_time_seconds: number | null;
  setup_time_seconds: number | null;
  changeover_time_seconds: number | null;
  batch_size: number | null;
  operator_count: number | null;
  resources: ResourceRequirement[];
};
type Recipe = { id: string; product_id: string; steps: ProcessStep[] };
type TransferSettings = {
  use_layout_distance: boolean;
  pixels_per_meter: number;
  default_speed_meters_per_second: number;
};
type EditorState = {
  nodes: FlowNode[];
  edges: FlowEdge[];
  products: Product[];
  recipes: Recipe[];
  transferSettings: TransferSettings;
};
type MachineAsset = {
  id: string;
  name: string;
  identity: string;
  machine_type: string;
  custom_type_name: string;
  capabilities: string[];
  manufacturer: string;
  model: string;
  nominal_cycle_time_seconds: number;
  capacity_per_hour: number;
  operating_state: string;
  archived_at?: string | null;
};
type MachineComponent = {
  id: string;
  name: string;
  identity: string;
  component_type: string;
  manufacturer: string;
  model: string;
  archived_at?: string | null;
};
type ValidationError = {
  code: string;
  path: string;
  message: string;
  action: string;
};
type ValidationResult = {
  valid: boolean;
  errors: ValidationError[];
  transfer_times: { edge_id: string; seconds: number | null; method: string }[];
};
type TwinValidation = {
  validation_id: string;
  simulation_run_id: string;
  status: string;
  created_at: string;
  metrics: Record<string, {
    status: string;
    sample_size: number;
    coverage: number;
    observed_total: number | null;
    simulated_total: number | null;
    signed_bias: number | null;
    absolute_error: number | null;
    unit: string;
  }> | null;
  operating_envelope: Record<string, unknown> | null;
  evidence: Array<{ code: string; message: string; source: string }> | null;
  error: { code: string; message: string } | null;
};
type VersionSummary = {
  version: number;
  validation: ValidationResult;
  created_at: string;
};
type StoredModel = {
  revision: number;
  model: ServerModel;
  updated_at: string | null;
};
type ServerModel = {
  schema_version: 1;
  layout: {
    nodes: {
      id: string;
      type: NodeKind;
      position: { x: number; y: number };
      rotation: number;
      label: string;
      machine_id: string | null;
      required: boolean;
      buffer_capacity: number | null;
    }[];
    edges: {
      id: string;
      source: string;
      target: string;
      source_handle: string;
      target_handle: string;
      route_kind: "normal" | "rework";
      rework_rule: { condition: string; max_revisits: number } | null;
      transfer_time_seconds: number | null;
      distance_meters: number | null;
      speed_meters_per_second: number | null;
    }[];
    transfer_settings: TransferSettings;
  };
  products: Product[];
  recipes: Recipe[];
};
const EMPTY_STATE: EditorState = {
  nodes: [
    {
      id: "source",
      type: "source",
      position: { x: 80, y: 180 },
      data: { label: "Material source", required: true, rotation: 0 },
    },
    {
      id: "sink",
      type: "sink",
      position: { x: 650, y: 180 },
      data: { label: "Finished goods", required: true, rotation: 0 },
    },
  ],
  edges: [],
  products: [],
  recipes: [],
  transferSettings: {
    use_layout_distance: false,
    pixels_per_meter: 100,
    default_speed_meters_per_second: 1,
  },
};

function newId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID().replaceAll("-", "")}`;
}

function fromServer(model: ServerModel): EditorState {
  return {
    nodes: model.layout.nodes.map((node) => ({
      id: node.id,
      type: node.type,
      position: node.position,
      data: {
        label: node.label,
        machine_id: node.machine_id ?? undefined,
        required: node.required,
        buffer_capacity: node.buffer_capacity ?? undefined,
        rotation: node.rotation,
      },
    })),
    edges: model.layout.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.source_handle,
      targetHandle: edge.target_handle,
      type: "smoothstep",
      markerEnd: { type: MarkerType.ArrowClosed, color: "#36382f" },
      data: {
        route_kind: edge.route_kind,
        rework_rule: edge.rework_rule ?? undefined,
        transfer_time_seconds: edge.transfer_time_seconds ?? undefined,
        distance_meters: edge.distance_meters ?? undefined,
        speed_meters_per_second: edge.speed_meters_per_second ?? undefined,
      },
    })),
    products: model.products,
    recipes: model.recipes,
    transferSettings: model.layout.transfer_settings,
  };
}

function toServer(state: EditorState): ServerModel {
  return {
    schema_version: 1,
    layout: {
      nodes: state.nodes.map((node) => ({
        id: node.id,
        type: node.type ?? "machine",
        position: node.position,
        rotation: node.data.rotation,
        label: node.data.label,
        machine_id: node.data.machine_id ?? null,
        required: node.data.required,
        buffer_capacity: node.data.buffer_capacity ?? null,
      })),
      edges: state.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        source_handle: edge.sourceHandle ?? "",
        target_handle: edge.targetHandle ?? "",
        route_kind: edge.data?.route_kind ?? "normal",
        rework_rule: edge.data?.rework_rule ?? null,
        transfer_time_seconds: edge.data?.transfer_time_seconds ?? null,
        distance_meters: edge.data?.distance_meters ?? null,
        speed_meters_per_second: edge.data?.speed_meters_per_second ?? null,
      })),
      transfer_settings: state.transferSettings,
    },
    products: state.products,
    recipes: state.recipes,
  };
}

function MachineNode({ data, selected, type }: NodeProps<FlowNode>) {
  const classes = {
    source: "flow-node flow-node-source",
    sink: "flow-node flow-node-sink",
    machine: "flow-node flow-node-machine",
    buffer: "flow-node flow-node-buffer",
  };
  const kind = data.machine_id ? "machine" : "station";
  return (
    <div
      className={`${classes[type ?? "machine"]} ${selected ? "flow-node-selected" : ""}`}
      style={{ transform: `rotate(${data.rotation}deg)` }}
    >
      {type !== "source" && <Handle id="in" position={Position.Left} type="target" />}
      <strong>{data.label || kind}</strong>
      {data.machine_id && <small>{data.machine_id.slice(-8)}</small>}
      {typeof data.buffer_capacity === "number" && <small>CAPACITY {data.buffer_capacity}</small>}
      {type !== "sink" && <Handle id="out" position={Position.Right} type="source" />}
    </div>
  );
}

const nodeTypes = { source: MachineNode, sink: MachineNode, machine: MachineNode, buffer: MachineNode };

function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "The production-line model service could not be reached.";
}

function numberValue(value: string): number | null {
  if (value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function FlowCanvas({
  state,
  revision,
  lineId,
  canEdit,
  onStateChange,
  onRevisionChange,
  onClose,
}: {
  state: EditorState;
  revision: number;
  lineId: string;
  canEdit: boolean;
  onStateChange: (state: EditorState, historyFrom?: EditorState) => void;
  onRevisionChange: (revision: number) => void;
  onClose: () => void;
}) {
  const { screenToFlowPosition } = useReactFlow();
  const current = useRef(state);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [status, setStatus] = useState<"Loading" | "Saved" | "Unsaved" | "Saving" | "Conflict" | "Error">("Loading");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [versions, setVersions] = useState<VersionSummary[]>([]);
  const [historyVersion, setHistoryVersion] = useState("");
  const [reviewVersion, setReviewVersion] = useState("");
  const [reviewModel, setReviewModel] = useState<EditorState | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewError, setReviewError] = useState("");
  const [activeView, setActiveView] = useState<"editor" | "review">("editor");
  const [replayMode, setReplayMode] = useState(false);
  const [replayRuns, setReplayRuns] = useState<Array<{run_id: string; status: string; seed: number; line_version: number; created_at: string}>>([]);
  const [replayRunId, setReplayRunId] = useState("");
  const [replayEvents, setReplayEvents] = useState<ReplayEvent[]>([]);
  const [replayLoading, setReplayLoading] = useState(false);
  const [replayError, setReplayError] = useState("");
  const [twinValidations, setTwinValidations] = useState<TwinValidation[]>([]);
  const [twinLoading, setTwinLoading] = useState(false);
  const [twinError, setTwinError] = useState("");
  const [twinRunId, setTwinRunId] = useState("");
  const [twinExitSensor, setTwinExitSensor] = useState("");
  const [twinTimezone, setTwinTimezone] = useState("UTC");
  const [twinCalibrationStart, setTwinCalibrationStart] = useState("");
  const [twinCalibrationEnd, setTwinCalibrationEnd] = useState("");
  const [twinObservationStart, setTwinObservationStart] = useState("");
  const [twinObservationEnd, setTwinObservationEnd] = useState("");
  const [motionPaused, setMotionPaused] = useState(false);
  const [components, setComponents] = useState<MachineComponent[]>([]);
  const [selectedComponentId, setSelectedComponentId] = useState<string | null>(null);
  const [assetDetailsError, setAssetDetailsError] = useState("");
  const [assetDetailsLoading, setAssetDetailsLoading] = useState(false);
  const [operationError, setOperationError] = useState("");
  const history = useRef<{ undo: EditorState[]; redo: EditorState[] }>({ undo: [], redo: [] });
  const dragStart = useRef<EditorState | null>(null);

  useEffect(() => {
    current.current = state;
  }, [state]);

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const [stored, versionsResult] = await Promise.all([
        apiRequest<StoredModel>(`/lines/${encodeURIComponent(lineId)}/model`),
        apiRequest<{ versions: VersionSummary[] }>(
          `/lines/${encodeURIComponent(lineId)}/versions`,
        ),
      ]);
      const loaded = stored.revision === 0 ? EMPTY_STATE : fromServer(stored.model);
      history.current = { undo: [], redo: [] };
      onStateChange(loaded);
      current.current = loaded;
      onRevisionChange(stored.revision);
      setVersions(versionsResult.versions);
      setReviewVersion(String(versionsResult.versions[0]?.version ?? ""));
      setReviewModel(null);
      setReviewError("");
      setValidation(null);
      setStatus("Saved");
      setOperationError("");
    } catch (reason) {
      setError(errorText(reason));
      setStatus("Error");
    } finally {
      setBusy(false);
    }
  }, [lineId, onRevisionChange, onStateChange]);

  useEffect(() => {
    const root = document.documentElement;
    if (motionPaused) root.setAttribute("data-motion-paused", "true");
    else root.removeAttribute("data-motion-paused");
    return () => root.removeAttribute("data-motion-paused");
  }, [motionPaused]);

  useEffect(() => {
    if (!reviewVersion) {
      setReviewModel(null);
      return;
    }
    let active = true;
    setReviewLoading(true);
    setReviewError("");
    apiRequest<{ model: ServerModel }>(
      `/lines/${encodeURIComponent(lineId)}/versions/${encodeURIComponent(reviewVersion)}`,
    ).then((result) => {
      if (active) setReviewModel(fromServer(result.model));
    }).catch((reason: unknown) => {
      if (active) {
        setReviewModel(null);
        setReviewError(errorText(reason));
      }
    }).finally(() => {
      if (active) setReviewLoading(false);
    });
    return () => {
      active = false;
    };
  }, [lineId, reviewVersion]);

  useEffect(() => {
    if (!reviewVersion || !lineId) {
      setTwinValidations([]);
      return;
    }
    let active = true;
    setTwinLoading(true);
    apiRequest<{ validations: TwinValidation[] }>(
      `/lines/${encodeURIComponent(lineId)}/versions/${encodeURIComponent(reviewVersion)}/validations`,
    ).then((result) => {
      if (active) setTwinValidations(result.validations);
    }).catch((reason: unknown) => {
      if (active) setTwinError(errorText(reason));
    }).finally(() => {
      if (active) setTwinLoading(false);
    });
    return () => { active = false; };
  }, [lineId, reviewVersion]);

  useEffect(() => {
    if (!lineId) return;
    let active = true;
    apiRequest<{ runs: Array<{run_id: string; status: string; seed: number; line_version: number; created_at: string}> }>(
      `/simulation/runs?line_id=${encodeURIComponent(lineId)}&limit=50`,
    ).then((result) => {
      if (active) {
        const completed = result.runs.filter((run) => run.status === "completed");
        setReplayRuns(completed);
        if (!replayRunId && completed.length > 0) setReplayRunId(completed[0].run_id);
      }
    }).catch((reason: unknown) => {
      if (active) setReplayError(errorText(reason));
    });
    return () => {
      active = false;
    };
  }, [lineId, replayMode, replayRunId]);

  useEffect(() => {
    if (!replayMode || !replayRunId) {
      setReplayEvents([]);
      return;
    }
    let active = true;
    setReplayLoading(true);
    setReplayError("");
    apiRequest<{ events: ReplayEvent[] }>(
      `/simulation/runs/${encodeURIComponent(replayRunId)}/events?limit=2000`,
    ).then((result) => {
      if (active) setReplayEvents(result.events);
    }).catch((reason: unknown) => {
      if (active) {
        setReplayEvents([]);
        setReplayError(errorText(reason));
      }
    }).finally(() => {
      if (active) setReplayLoading(false);
    });
    return () => {
      active = false;
    };
  }, [replayMode, replayRunId]);

  async function createTwinValidation() {
    if (!twinRunId || !twinExitSensor || !twinCalibrationStart || !twinCalibrationEnd || !twinObservationStart || !twinObservationEnd) {
      setTwinError("Select a completed simulation and provide calibration and observation windows plus an exit-count sensor.");
      return;
    }
    setTwinLoading(true);
    setTwinError("");
    try {
      await apiRequest<{ validation: TwinValidation }>(
        `/lines/${encodeURIComponent(lineId)}/versions/${encodeURIComponent(reviewVersion)}/validations`,
        {
          method: "POST",
          body: JSON.stringify({
            simulation_run_id: twinRunId,
            calibration_window: {
              start: new Date(twinCalibrationStart).toISOString(),
              end: new Date(twinCalibrationEnd).toISOString(),
            },
            observation_window: {
              start: new Date(twinObservationStart).toISOString(),
              end: new Date(twinObservationEnd).toISOString(),
            },
            timezone: twinTimezone,
            feed_conditions: {},
            sensor_mapping: { exit_count_sensor_id: twinExitSensor },
          }),
        },
      );
      const result = await apiRequest<{ validations: TwinValidation[] }>(
        `/lines/${encodeURIComponent(lineId)}/versions/${encodeURIComponent(reviewVersion)}/validations`,
      );
      setTwinValidations(result.validations);
    } catch (reason: unknown) {
      setTwinError(errorText(reason));
    } finally {
      setTwinLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [load]);

  const commit = useCallback(
    (next: EditorState, from: EditorState = current.current) => {
      if (canEdit && !busy) {
        history.current.undo = [...history.current.undo.slice(-49), from];
        history.current.redo = [];
        current.current = next;
        onStateChange(next);
        setStatus("Unsaved");
        setValidation(null);
        setError("");
      }
    },
    [busy, canEdit, onStateChange],
  );

  const onNodesChange = useCallback(
    (changes: NodeChange<FlowNode>[]) => {
      if (busy) return;
      const nodes = applyNodeChanges(changes, current.current.nodes);
      const next = { ...current.current, nodes };
      current.current = next;
      onStateChange(next);
    },
    [busy, onStateChange],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange<FlowEdge>[]) => {
      if (busy) return;
      const edges = applyEdgeChanges(changes, current.current.edges);
      const next = { ...current.current, edges };
      current.current = next;
      onStateChange(next);
    },
    [busy, onStateChange],
  );

  function onNodeDragStart() {
    dragStart.current = current.current;
  }

  function onNodeDragStop() {
    if (dragStart.current) {
      const next = current.current;
      const before = dragStart.current;
      dragStart.current = null;
      if (JSON.stringify(next.nodes) !== JSON.stringify(before.nodes)) commit(next, before);
    }
  }

  function addNode(type: NodeKind, machine?: MachineAsset, position?: { x: number; y: number }) {
    const node: FlowNode = {
      id: newId(type),
      type,
      position: position ?? {
        x: 180 + current.current.nodes.length * 38,
        y: 150 + (current.current.nodes.length % 4) * 55,
      },
      data: {
        label: machine?.name ?? (type === "source" ? "Material source" : type === "sink" ? "Finished goods" : type === "buffer" ? "Buffer" : "Machine"),
        machine_id: machine?.id,
        required: true,
        buffer_capacity: type === "buffer" ? 10 : undefined,
        rotation: 0,
      },
    };
    commit({ ...current.current, nodes: [...current.current.nodes, node] });
    setSelectedNodeId(node.id);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    if (!canEdit || busy) return;
    const payload = event.dataTransfer.getData("application/realityloop-node");
    if (!payload) return;
    const [kind, machineId] = payload.split(":");
    const type = kind as NodeKind;
    const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
    const machine = machines.find((candidate) => candidate.id === machineId);
    addNode(type, machine, position);
  }

  const [machines, setMachines] = useState<MachineAsset[]>([]);
  useEffect(() => {
    let active = true;
    apiRequest<{ machines: MachineAsset[] }>(
      `/lines/${encodeURIComponent(lineId)}/machines`,
    ).then((result) => {
      if (active) setMachines(result.machines.filter((machine) => !("archived_at" in machine && machine.archived_at)));
    }).catch((reason: unknown) => {
      if (active) setError(errorText(reason));
    });
    return () => {
      active = false;
    };
  }, [lineId]);

  function connect(connection: Connection) {
    if (!canEdit || busy || !connection.source || !connection.target) return;
    const edge: FlowEdge = {
      id: newId("edge"),
      source: connection.source,
      target: connection.target,
      sourceHandle: connection.sourceHandle,
      targetHandle: connection.targetHandle,
      type: "smoothstep",
      markerEnd: { type: MarkerType.ArrowClosed, color: "#36382f" },
      data: { route_kind: "normal" },
    };
    commit({ ...current.current, edges: addEdge(edge, current.current.edges) });
  }

  function updateNode(nodeId: string, patch: Partial<NodeData>) {
    commit({
      ...current.current,
      nodes: current.current.nodes.map((node) =>
        node.id === nodeId ? { ...node, data: { ...node.data, ...patch } } : node,
      ),
    });
  }

  function updateEdge(edgeId: string, patch: Partial<TransferData>) {
    commit({
      ...current.current,
      edges: current.current.edges.map((edge) =>
        edge.id === edgeId
          ? {
              ...edge,
              data: {
                route_kind: patch.route_kind ?? edge.data?.route_kind ?? "normal",
                ...edge.data,
                ...patch,
              },
            }
          : edge,
      ),
    });
  }

  function undo() {
    const previous = history.current.undo.at(-1);
    if (!previous) return;
    history.current.undo = history.current.undo.slice(0, -1);
    history.current.redo = [...history.current.redo, current.current];
    current.current = previous;
    onStateChange(previous);
    setStatus("Unsaved");
    setValidation(null);
  }

  function redo() {
    const next = history.current.redo.at(-1);
    if (!next) return;
    history.current.redo = history.current.redo.slice(0, -1);
    history.current.undo = [...history.current.undo, current.current];
    current.current = next;
    onStateChange(next);
    setStatus("Unsaved");
    setValidation(null);
  }

  function changeProducts(products: Product[], recipes = current.current.recipes) {
    commit({ ...current.current, products, recipes });
  }

  function changeRecipe(recipeId: string, transform: (recipe: Recipe) => Recipe) {
    commit({
      ...current.current,
      recipes: current.current.recipes.map((recipe) =>
        recipe.id === recipeId ? transform(recipe) : recipe,
      ),
    });
  }

  async function validateModel() {
    setBusy(true);
    setError("");
    try {
      const result = await apiRequest<ValidationResult>(
        `/lines/${encodeURIComponent(lineId)}/validate`,
        { method: "POST", body: JSON.stringify(toServer(current.current)) },
      );
      setValidation(result);
      setOperationError("");
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function saveModel() {
    setBusy(true);
    setStatus("Saving");
    setError("");
    try {
      const result = await apiRequest<{
        revision: number;
        validation: ValidationResult;
      }>(`/lines/${encodeURIComponent(lineId)}/model`, {
        method: "PUT",
        body: JSON.stringify({
          expected_revision: revision,
          model: toServer(current.current),
        }),
      });
      onRevisionChange(result.revision);
      setValidation(result.validation);
      const versionsResult = await apiRequest<{ versions: VersionSummary[] }>(
        `/lines/${encodeURIComponent(lineId)}/versions`,
      );
      setVersions(versionsResult.versions);
      setReviewVersion(String(result.revision));
      setStatus("Saved");
      setOperationError("");
    } catch (reason) {
      const isConflict = reason instanceof ApiError && reason.status === 409;
      setStatus(isConflict ? "Conflict" : "Error");
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function loadVersion(version: number) {
    setBusy(true);
    setError("");
    try {
      const result = await apiRequest<{ model: ServerModel; validation: ValidationResult }>(
        `/lines/${encodeURIComponent(lineId)}/versions/${version}`,
      );
      const loaded = fromServer(result.model);
      history.current.undo = [...history.current.undo.slice(-49), current.current];
      history.current.redo = [];
      current.current = loaded;
      onStateChange(loaded);
      setValidation(result.validation);
      setHistoryVersion("");
      setStatus("Unsaved");
    } finally {
      setBusy(false);
    }
  }

  function duplicateSelected() {
    const selected = current.current.nodes.find((node) => node.id === selectedNodeId);
    if (!selected) return;
    const duplicate: FlowNode = {
      ...selected,
      id: newId(selected.type ?? "station"),
      position: { x: selected.position.x + 45, y: selected.position.y + 45 },
      data: { ...selected.data, label: `${selected.data.label} copy` },
      selected: false,
    };
    commit({ ...current.current, nodes: [...current.current.nodes, duplicate] });
    setSelectedNodeId(duplicate.id);
  }

  function deleteSelected() {
    if (selectedNodeId) {
      const nodeId = selectedNodeId;
      commit({
        ...current.current,
        nodes: current.current.nodes.filter((node) => node.id !== nodeId),
        edges: current.current.edges.filter((edge) => edge.source !== nodeId && edge.target !== nodeId),
      });
      setSelectedNodeId(null);
      return;
    }
    if (selectedEdgeId) {
      commit({
        ...current.current,
        edges: current.current.edges.filter((edge) => edge.id !== selectedEdgeId),
      });
      setSelectedEdgeId(null);
    }
  }

  const selectedNode = state.nodes.find((node) => node.id === selectedNodeId) ?? null;
  const selectedEdge = state.edges.find((edge) => edge.id === selectedEdgeId) ?? null;
  const allCapabilities = [...new Set(machines.flatMap((machine) => machine.capabilities))].sort();
  const editable = canEdit && !busy;
  const reviewNode = reviewModel?.nodes.find((node) => node.id === selectedNodeId) ?? null;
  const inspectorNode = activeView === "review" ? reviewNode : selectedNode;
  const selectedMachineId = inspectorNode?.data.machine_id ?? "";
  const [machineDetails, setMachineDetails] = useState<MachineAsset | null>(null);
  const selectedMachine = machineDetails?.id === selectedMachineId
    ? machineDetails
    : machines.find((machine) => machine.id === selectedMachineId) ?? null;
  const reviewMachines: ReviewMachine[] = machines;
  const reviewNodes: ReviewNode[] = (reviewModel?.nodes ?? []).map((node) => ({
    id: node.id,
    type: node.type ?? "machine",
    position: node.position,
    data: node.data,
  }));
  const reviewEdges: ReviewEdge[] = (reviewModel?.edges ?? []).map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    data: { route_kind: edge.data?.route_kind },
  }));

  useEffect(() => {
    setComponents([]);
    setMachineDetails(null);
    setSelectedComponentId(null);
    setAssetDetailsError("");
    setAssetDetailsLoading(Boolean(selectedMachineId));
    if (!selectedMachineId) return;
    let active = true;
    Promise.all([
      apiRequest<MachineAsset>(
        `/machines/${encodeURIComponent(selectedMachineId)}?include_archived=true`,
      ),
      apiRequest<{ components: MachineComponent[] }>(
        `/machines/${encodeURIComponent(selectedMachineId)}/components?include_archived=true`,
      ),
    ]).then(([machine, result]) => {
      if (active) {
        setMachineDetails(machine);
        setComponents(result.components);
      }
    }).catch((reason: unknown) => {
      if (active) setAssetDetailsError(errorText(reason));
    }).finally(() => {
      if (active) setAssetDetailsLoading(false);
    });
    return () => {
      active = false;
    };
  }, [selectedMachineId]);

  const selectedComponent = components.find((component) => component.id === selectedComponentId) ?? null;

  function addProduct() {
    const product: Product = { id: newId("product"), name: "New product", sku: "" };
    const recipe: Recipe = { id: newId("recipe"), product_id: product.id, steps: [] };
    changeProducts([...current.current.products, product], [...current.current.recipes, recipe]);
  }

  return (
    <section className="line-editor" aria-label="Production-line editor">
      <header className="line-editor-header">
        <div>
          <p className="font-mono text-xs tracking-widest text-accent">PRODUCTION MODEL / REVISION {revision}</p>
          <h3 className="mt-2 text-xl font-semibold">{activeView === "editor" ? "2D line editor" : "3D line review"}</h3>
          <p className="mt-1 text-xs text-ink/60">
            {activeView === "editor"
              ? "Layout coordinates are visual; operation and transfer parameters are stored separately."
              : "Review an immutable saved line version. Unsaved draft changes are excluded."}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={`line-save-status line-save-${status.toLowerCase()}`} role="status">{status.toUpperCase()}</span>
          <button
            aria-pressed={activeView === "editor"}
            className={activeView === "editor" ? "action-button" : "secondary-button"}
            onClick={() => setActiveView("editor")}
            type="button"
          >
            2D EDITOR
          </button>
          <button
            aria-pressed={activeView === "review"}
            className={activeView === "review" ? "action-button" : "secondary-button"}
            onClick={() => setActiveView("review")}
            type="button"
          >
            3D REVIEW
          </button>
          <button
            aria-pressed={motionPaused}
            className="secondary-button"
            onClick={() => setMotionPaused((paused) => !paused)}
            type="button"
          >
            {motionPaused ? "RESUME GLOBAL ANIMATIONS" : "PAUSE GLOBAL ANIMATIONS"}
          </button>
          {activeView === "editor" && (
            <>
              <button className="secondary-button" disabled={!history.current.undo.length || !canEdit || busy} onClick={undo} type="button">UNDO</button>
              <button className="secondary-button" disabled={!history.current.redo.length || !canEdit || busy} onClick={redo} type="button">REDO</button>
              <button className="secondary-button" disabled={busy} onClick={() => void validateModel()} type="button">VALIDATE</button>
              <button className="action-button" disabled={busy || !canEdit || status === "Saved"} onClick={() => void saveModel()} type="button">SAVE VERSION</button>
            </>
          )}
          <button className="secondary-button" onClick={onClose} type="button">CLOSE</button>
        </div>
      </header>

      {!canEdit && <p className="mt-4 border-l-2 border-accent pl-3 text-sm">Read-only workspace role. Editing and saving are disabled.</p>}
      {error && (
        <div className="mt-4 border-l-2 border-red-700 pl-3 text-sm text-red-800" role="alert">
          <p>{error}</p>
          {status === "Conflict" && (
            <button
              className="text-link mt-2"
              onClick={() => {
                if (window.confirm("Reloading replaces your unsaved changes with the latest saved version.")) void load();
              }}
              type="button"
            >
              RELOAD LATEST (DISCARD LOCAL CHANGES)
            </button>
          )}
        </div>
      )}
      {operationError && <p className="mt-3 text-sm text-red-800" role="alert">{operationError}</p>}

      <fieldset className="contents" disabled={busy || !canEdit}>
      <div className="line-editor-toolbar">
        <div className="line-palette" aria-label="Equipment palette">
          <span className="line-panel-label">PALETTE — DRAG OR ADD</span>
          {(["source", "sink", "buffer"] as NodeKind[]).map((type) => (
            <button
              className="line-palette-item"
              disabled={!canEdit}
              draggable={canEdit}
              key={type}
              onClick={() => addNode(type)}
              onDragStart={(event) => event.dataTransfer.setData("application/realityloop-node", type)}
              type="button"
            >
              + {type.toUpperCase()}
            </button>
          ))}
          {machines.map((machine) => (
            <button
              className="line-palette-item"
              disabled={!canEdit}
              draggable={canEdit}
              key={machine.id}
              onClick={() => addNode("machine", machine)}
              onDragStart={(event) => event.dataTransfer.setData("application/realityloop-node", `machine:${machine.id}`)}
              title={machine.capabilities.join(", ") || "No capabilities configured"}
              type="button"
            >
              + {machine.name}
            </button>
          ))}
          {machines.length === 0 && <p className="text-xs text-ink/60">Add an active machine to this line in the asset registry.</p>}
        </div>
        <div className="line-flow-actions">
          <button className="secondary-button" disabled={!selectedNode || !canEdit} onClick={duplicateSelected} type="button">DUPLICATE NODE</button>
          <button className="secondary-button" disabled={(!selectedNode && !selectedEdge) || !canEdit} onClick={deleteSelected} type="button">DELETE SELECTED</button>
          <button className="secondary-button" disabled={!selectedNode || selectedNode.type !== "machine" || !canEdit} onClick={() => selectedNode && updateNode(selectedNode.id, { rotation: (selectedNode.data.rotation + 90) % 360 })} type="button">ROTATE 90°</button>
          <label className="line-switch">
            <input
              checked={state.transferSettings.use_layout_distance}
              disabled={!canEdit}
              onChange={(event) => commit({ ...current.current, transferSettings: { ...current.current.transferSettings, use_layout_distance: event.target.checked } })}
              type="checkbox"
            />
            Derive transfer time from layout distance
          </label>
          {state.transferSettings.use_layout_distance && (
            <>
              <label className="form-field"><span>Pixels per meter</span><input disabled={!canEdit} min="0.001" onChange={(event) => commit({ ...current.current, transferSettings: { ...current.current.transferSettings, pixels_per_meter: numberValue(event.target.value) ?? 100 } })} type="number" value={state.transferSettings.pixels_per_meter} /></label>
              <label className="form-field"><span>Default speed (m/s)</span><input disabled={!canEdit} min="0.001" onChange={(event) => commit({ ...current.current, transferSettings: { ...current.current.transferSettings, default_speed_meters_per_second: numberValue(event.target.value) ?? 1 } })} type="number" value={state.transferSettings.default_speed_meters_per_second} /></label>
            </>
          )}
          <label className="form-field">
            <span>Version history</span>
            <select value={historyVersion} onChange={(event) => setHistoryVersion(event.target.value)}>
              <option value="">Select a saved version</option>
              {versions.map((version) => (
                <option key={version.version} value={version.version}>
                  v{version.version} · {version.validation.valid ? "valid" : "has issues"} · {new Date(version.created_at).toLocaleString()}
                </option>
              ))}
            </select>
          </label>
          {historyVersion && (
            <button
              className="text-link text-left text-sm"
              onClick={() => {
                void loadVersion(Number(historyVersion)).catch((reason: unknown) => setError(errorText(reason)));
              }}
              type="button"
            >
              LOAD VERSION AS UNSAVED DRAFT
            </button>
          )}
        </div>
      </div>

      {activeView === "editor" && <div className="line-editor-workspace">
        <div className="line-flow-canvas" onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "move"; }} onDrop={onDrop}>
          <ReactFlow
            deleteKeyCode={null}
            edges={state.edges}
            elementsSelectable
            fitView
            fitViewOptions={{ padding: 0.2 }}
            maxZoom={1.8}
            minZoom={0.25}
            nodes={state.nodes.map((node) => ({ ...node, selected: node.id === selectedNodeId }))}
            nodesConnectable={editable}
            nodesDraggable={editable}
            nodeTypes={nodeTypes}
            onConnect={connect}
            onEdgeClick={(_event, edge) => { setSelectedEdgeId(edge.id); setSelectedNodeId(null); }}
            onEdgesChange={onEdgesChange}
            onNodeClick={(_event, node) => { setSelectedNodeId(node.id); setSelectedEdgeId(null); }}
            onNodeDragStart={onNodeDragStart}
            onNodeDragStop={onNodeDragStop}
            onNodesChange={onNodesChange}
            onPaneClick={() => { setSelectedNodeId(null); setSelectedEdgeId(null); }}
            proOptions={{ hideAttribution: true }}
            selectionOnDrag={false}
          >
            <Background color="#c9c8bd" gap={20} size={1} variant={BackgroundVariant.Dots} />
            <Controls />
            <MiniMap nodeColor={(node) => node.type === "source" ? "#b94a28" : node.type === "sink" ? "#53677a" : node.type === "buffer" ? "#b8a270" : "#6e7667"} />
          </ReactFlow>
        </div>

        <aside className="line-model-panel">
          {selectedNode && (
            <>
              <p className="line-panel-label">SELECTED STATION</p>
              <label className="form-field"><span>Label</span><input disabled={!canEdit} onChange={(event) => updateNode(selectedNode.id, { label: event.target.value })} value={selectedNode.data.label} /></label>
              {selectedNode.type === "machine" && (
                <>
                  <p className="text-xs text-ink/60">Machine asset: {machines.find((item) => item.id === selectedNode.data.machine_id)?.name ?? "unavailable"}</p>
                  <label className="line-switch"><input checked={selectedNode.data.required} disabled={!canEdit} onChange={(event) => updateNode(selectedNode.id, { required: event.target.checked })} type="checkbox" /> Required routing station</label>
                </>
              )}
              {selectedNode.type === "buffer" && (
                <label className="form-field"><span>Finite buffer capacity (units)</span><input disabled={!canEdit} min="1" onChange={(event) => updateNode(selectedNode.id, { buffer_capacity: numberValue(event.target.value) ?? 0 })} type="number" value={selectedNode.data.buffer_capacity ?? ""} /></label>
              )}
            </>
          )}
          {selectedEdge && (
            <>
              <p className="line-panel-label">CONNECTION PARAMETERS</p>
              <label className="line-switch"><input checked={selectedEdge.data?.route_kind === "rework"} disabled={!canEdit} onChange={(event) => updateEdge(selectedEdge.id, { route_kind: event.target.checked ? "rework" : "normal", rework_rule: event.target.checked ? { condition: "", max_revisits: 1 } : undefined })} type="checkbox" /> Intentional rework route</label>
              {selectedEdge.data?.route_kind === "rework" && (
                <>
                  <label className="form-field"><span>Routing condition</span><input disabled={!canEdit} onChange={(event) => updateEdge(selectedEdge.id, { rework_rule: { condition: event.target.value, max_revisits: selectedEdge.data?.rework_rule?.max_revisits ?? 1 } })} value={selectedEdge.data.rework_rule?.condition ?? ""} /></label>
                  <label className="form-field"><span>Maximum revisits</span><input disabled={!canEdit} max="100" min="1" onChange={(event) => updateEdge(selectedEdge.id, { rework_rule: { condition: selectedEdge.data?.rework_rule?.condition ?? "", max_revisits: numberValue(event.target.value) ?? 1 } })} type="number" value={selectedEdge.data.rework_rule?.max_revisits ?? 1} /></label>
                </>
              )}
              <label className="form-field"><span>Transfer time (seconds)</span><input disabled={!canEdit} min="0.001" onChange={(event) => updateEdge(selectedEdge.id, { transfer_time_seconds: numberValue(event.target.value) ?? undefined, distance_meters: undefined, speed_meters_per_second: undefined })} placeholder="Optional" type="number" value={selectedEdge.data?.transfer_time_seconds ?? ""} /></label>
              <label className="form-field"><span>Transfer distance (meters)</span><input disabled={!canEdit} min="0.001" onChange={(event) => updateEdge(selectedEdge.id, { distance_meters: numberValue(event.target.value) ?? undefined, transfer_time_seconds: undefined })} placeholder="Optional" type="number" value={selectedEdge.data?.distance_meters ?? ""} /></label>
              {selectedEdge.data?.distance_meters != null && (
                <label className="form-field"><span>Transfer speed (m/s)</span><input disabled={!canEdit} min="0.001" onChange={(event) => updateEdge(selectedEdge.id, { speed_meters_per_second: numberValue(event.target.value) ?? undefined })} placeholder="Required with distance" type="number" value={selectedEdge.data.speed_meters_per_second ?? ""} /></label>
              )}
              <p className="text-xs text-ink/60">Explicit transfer settings override layout-based estimates.</p>
            </>
          )}
          {!selectedNode && !selectedEdge && (
            <>
              <p className="line-panel-label">MODEL CONTENTS</p>
              <p className="text-sm">{state.nodes.length} stations · {state.edges.length} connections</p>
              <p className="text-xs text-ink/60">Connect output ports to input ports. Branches and merges are allowed.</p>
            </>
          )}
          <hr className="border-rule" />
          <div className="flex items-center justify-between gap-2">
            <p className="line-panel-label">PRODUCTS & RECIPES</p>
            <button className="text-link font-mono text-xs" disabled={!canEdit} onClick={addProduct} type="button">+ PRODUCT</button>
          </div>
          {state.products.length === 0 && <p className="text-xs text-ink/60">Add a product and its ordered process recipe.</p>}
          {state.products.map((product) => {
            const recipe = state.recipes.find((item) => item.product_id === product.id);
            return (
              <section className="line-recipe" key={product.id}>
                <label className="form-field"><span>Product name</span><input disabled={!canEdit} onChange={(event) => changeProducts(current.current.products.map((item) => item.id === product.id ? { ...item, name: event.target.value } : item))} value={product.name} /></label>
                <label className="form-field"><span>SKU</span><input disabled={!canEdit} onChange={(event) => changeProducts(current.current.products.map((item) => item.id === product.id ? { ...item, sku: event.target.value } : item))} value={product.sku} /></label>
                {recipe?.steps.map((step, index) => (
                  <div className="line-step" key={step.id}>
                    <div className="flex items-center justify-between gap-2">
                      <strong className="font-mono text-xs">STEP {index + 1}</strong>
                      <div className="flex gap-2">
                        <button aria-label="Move process step up" className="text-link" disabled={!canEdit || index === 0} onClick={() => changeRecipe(recipe.id, (currentRecipe) => { const steps = [...currentRecipe.steps]; [steps[index - 1], steps[index]] = [steps[index], steps[index - 1]]; return { ...currentRecipe, steps }; })} type="button">↑</button>
                        <button aria-label="Move process step down" className="text-link" disabled={!canEdit || index === recipe.steps.length - 1} onClick={() => changeRecipe(recipe.id, (currentRecipe) => { const steps = [...currentRecipe.steps]; [steps[index + 1], steps[index]] = [steps[index], steps[index + 1]]; return { ...currentRecipe, steps }; })} type="button">↓</button>
                        <button aria-label="Remove process step" className="text-link" disabled={!canEdit} onClick={() => changeRecipe(recipe.id, (currentRecipe) => ({ ...currentRecipe, steps: currentRecipe.steps.filter((item) => item.id !== step.id) }))} type="button">REMOVE</button>
                      </div>
                    </div>
                    <label className="form-field"><span>Operation / capability</span><input disabled={!canEdit} list={`capabilities-${step.id}`} onChange={(event) => changeRecipe(recipe.id, (item) => ({ ...item, steps: item.steps.map((candidate) => candidate.id === step.id ? { ...candidate, operation: event.target.value } : candidate) }))} value={step.operation} /><datalist id={`capabilities-${step.id}`}>{allCapabilities.map((capability) => <option key={capability} value={capability} />)}</datalist></label>
                    <div className="line-machine-choices">
                      <span className="line-panel-label">COMPATIBLE STATIONS</span>
                      {state.nodes.filter((node) => node.type === "machine").map((node) => {
                        const machine = machines.find((item) => item.id === node.data.machine_id);
                        return (
                          <label className="line-switch" key={node.id}>
                            <input
                              checked={step.machine_node_ids.includes(node.id)}
                              disabled={!canEdit}
                              onChange={(event) => changeRecipe(recipe.id, (item) => ({
                                ...item,
                                steps: item.steps.map((candidate) => candidate.id === step.id
                                  ? { ...candidate, machine_node_ids: event.target.checked ? [...candidate.machine_node_ids, node.id] : candidate.machine_node_ids.filter((id) => id !== node.id) }
                                  : candidate),
                              }))}
                              type="checkbox"
                            />
                            {node.data.label} <small>{machine?.capabilities.join(", ") ?? "machine missing"}</small>
                          </label>
                        );
                      })}
                    </div>
                    <div className="line-number-grid">
                      {([
                        ["cycle_time_seconds", "Cycle (s)"],
                        ["setup_time_seconds", "Setup (s)"],
                        ["changeover_time_seconds", "Changeover (s)"],
                        ["batch_size", "Batch size"],
                        ["operator_count", "Operators"],
                      ] as const).map(([field, label]) => (
                        <label className="form-field" key={field}>
                          <span>{label}</span>
                          <input
                            disabled={!canEdit}
                            min={field === "setup_time_seconds" || field === "changeover_time_seconds" ? "0" : "1"}
                            onChange={(event) => changeRecipe(recipe.id, (item) => ({
                              ...item,
                              steps: item.steps.map((candidate) => candidate.id === step.id ? { ...candidate, [field]: numberValue(event.target.value) } : candidate),
                            }))}
                            type="number"
                            value={step[field] ?? ""}
                          />
                        </label>
                      ))}
                    </div>
                    <div className="line-machine-choices">
                      <span className="line-panel-label">RESOURCE REQUIREMENTS</span>
                      {step.resources.map((resource, resourceIndex) => (
                        <div className="line-number-grid" key={`${step.id}-resource-${resourceIndex}`}>
                          <label className="form-field">
                            <span>Resource name</span>
                            <input
                              disabled={!canEdit}
                              onChange={(event) => changeRecipe(recipe.id, (item) => ({
                                ...item,
                                steps: item.steps.map((candidate) => candidate.id === step.id
                                  ? { ...candidate, resources: candidate.resources.map((entry, index) => index === resourceIndex ? { ...entry, name: event.target.value } : entry) }
                                  : candidate),
                              }))}
                              placeholder="e.g. fixture, tool"
                              value={resource.name}
                            />
                          </label>
                          <label className="form-field">
                            <span>Quantity</span>
                            <input
                              disabled={!canEdit}
                              min="1"
                              onChange={(event) => changeRecipe(recipe.id, (item) => ({
                                ...item,
                                steps: item.steps.map((candidate) => candidate.id === step.id
                                  ? { ...candidate, resources: candidate.resources.map((entry, index) => index === resourceIndex ? { ...entry, quantity: numberValue(event.target.value) ?? 1 } : entry) }
                                  : candidate),
                              }))}
                              type="number"
                              value={resource.quantity}
                            />
                          </label>
                          <button
                            aria-label={`Remove ${resource.name || "resource"} requirement`}
                            className="text-link"
                            disabled={!canEdit}
                            onClick={() => changeRecipe(recipe.id, (item) => ({
                              ...item,
                              steps: item.steps.map((candidate) => candidate.id === step.id
                                ? { ...candidate, resources: candidate.resources.filter((_entry, index) => index !== resourceIndex) }
                                : candidate),
                            }))}
                            type="button"
                          >
                            REMOVE
                          </button>
                        </div>
                      ))}
                      <button
                        className="text-link text-left text-sm"
                        disabled={!canEdit}
                        onClick={() => changeRecipe(recipe.id, (item) => ({
                          ...item,
                          steps: item.steps.map((candidate) => candidate.id === step.id
                            ? { ...candidate, resources: [...candidate.resources, { name: "", quantity: 1 }] }
                            : candidate),
                        }))}
                        type="button"
                      >
                        + ADD RESOURCE
                      </button>
                    </div>
                  </div>
                ))}
                <button
                  className="text-link text-sm"
                  disabled={!canEdit}
                  onClick={() => changeRecipe(recipe?.id ?? "", (item) => ({
                    ...item,
                    steps: [...item.steps, {
                      id: newId("step"),
                      operation: "",
                      machine_node_ids: [],
                      cycle_time_seconds: null,
                      setup_time_seconds: 0,
                      changeover_time_seconds: 0,
                      batch_size: 1,
                      operator_count: 0,
                      resources: [],
                    }],
                  }))}
                  type="button"
                >
                  + ADD ORDERED PROCESS STEP
                </button>
              </section>
            );
          })}
        </aside>
      </div>}
      </fieldset>

      {activeView === "review" && (
        <section className="line-review-panel" aria-label="Saved production-line 3D review">
          <div className="line-review-version">
            <label className="form-field">
              <span>Saved line version</span>
              <select
                className="registry-select"
                disabled={reviewLoading || versions.length === 0}
                onChange={(event) => setReviewVersion(event.target.value)}
                value={reviewVersion}
              >
                {versions.length === 0 && <option value="">No saved versions</option>}
                {versions.map((version) => (
                  <option key={version.version} value={version.version}>
                    v{version.version} · {version.validation.valid ? "valid" : "has issues"} · {new Date(version.created_at).toLocaleString()}
                  </option>
                ))}
              </select>
            </label>
            {reviewVersion && (
              <p className="text-xs text-ink/60">
                IMMUTABLE SNAPSHOT V{reviewVersion}. Draft edits appear here only after saving a new version.
              </p>
            )}
            <div className="mt-3 border border-rule bg-white/40 p-3">
              <p className="font-mono text-xs tracking-widest text-ink/60">TWIN VALIDATION · SAVED VERSION</p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <label className="form-field">
                  <span>Completed simulation</span>
                  <select className="registry-select" value={twinRunId} onChange={(event) => setTwinRunId(event.target.value)}>
                    <option value="">Select run</option>
                    {replayRuns.filter((run) => run.status === "completed" && run.line_version === Number(reviewVersion)).map((run) => (
                      <option key={run.run_id} value={run.run_id}>{run.run_id.slice(0, 8)} · seed {run.seed}</option>
                    ))}
                  </select>
                </label>
                <label className="form-field"><span>Exit-count sensor ID</span><input value={twinExitSensor} onChange={(event) => setTwinExitSensor(event.target.value)} /></label>
                <label className="form-field"><span>Timezone</span><input value={twinTimezone} onChange={(event) => setTwinTimezone(event.target.value)} /></label>
                <label className="form-field"><span>Calibration start</span><input type="datetime-local" value={twinCalibrationStart} onChange={(event) => setTwinCalibrationStart(event.target.value)} /></label>
                <label className="form-field"><span>Calibration end</span><input type="datetime-local" value={twinCalibrationEnd} onChange={(event) => setTwinCalibrationEnd(event.target.value)} /></label>
                <label className="form-field"><span>Observation start</span><input type="datetime-local" value={twinObservationStart} onChange={(event) => setTwinObservationStart(event.target.value)} /></label>
                <label className="form-field"><span>Observation end</span><input type="datetime-local" value={twinObservationEnd} onChange={(event) => setTwinObservationEnd(event.target.value)} /></label>
                <button className="action-button self-end" disabled={twinLoading || !reviewVersion || replayRuns.length === 0} onClick={() => void createTwinValidation()} type="button">
                  {twinLoading ? "STARTING…" : "VALIDATE THIS TWIN"}
                </button>
              </div>
              {twinError && <p className="mt-3 text-sm text-red-800" role="alert">{twinError}</p>}
              <div className="mt-3 divide-y divide-rule">
                {twinValidations.map((item) => {
                  const exitMetric = item.metrics?.conveyor_exit_count;
                  return (
                    <article className="py-3 text-sm" key={item.validation_id}>
                      <p className="font-mono text-xs">
                        {item.validation_id.slice(0, 8)} · {item.status.toUpperCase()}
                      </p>
                      {exitMetric ? (
                        <p className="mt-1">
                          Exit count: {exitMetric.status} · sample {exitMetric.sample_size} · observed {exitMetric.observed_total ?? "n/a"} ·
                          simulated {exitMetric.simulated_total ?? "n/a"} · bias {exitMetric.signed_bias ?? "n/a"} · absolute error {exitMetric.absolute_error ?? "n/a"} {exitMetric.unit}
                        </p>
                      ) : <p className="mt-1 text-ink/65">Awaiting measured evidence.</p>}
                      {item.evidence?.map((reason) => <p className="mt-1 text-xs text-ink/65" key={reason.code}>{reason.code}: {reason.message}</p>)}
                    </article>
                  );
                })}
              </div>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <button
                className={replayMode ? "secondary-button" : "text-link"}
                disabled={!reviewModel}
                onClick={() => setReplayMode(false)}
                type="button"
              >
                STATIC REVIEW
              </button>
              <button
                className={replayMode ? "text-link" : "secondary-button"}
                disabled={!reviewModel}
                onClick={() => setReplayMode(true)}
                type="button"
              >
                STORED REPLAY
              </button>
            </div>
            {replayMode && (
              <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
                <label className="form-field">
                  <span>Completed simulation run</span>
                  <select
                    className="registry-select"
                    disabled={replayRuns.length === 0}
                    onChange={(event) => setReplayRunId(event.target.value)}
                    value={replayRunId}
                  >
                    {replayRuns.length === 0 && <option value="">No completed runs</option>}
                    {replayRuns.map((run) => (
                      <option key={run.run_id} value={run.run_id}>
                        {run.run_id.slice(0, 8)} · V{run.line_version} · seed {run.seed} · {new Date(run.created_at).toLocaleString()}
                      </option>
                    ))}
                  </select>
                </label>
                {replayRunId && (
                  <p className="self-end text-xs text-ink/60">
                    REPLAY OF RUN {replayRunId.slice(0, 8)} · STORED EVENTS ONLY
                  </p>
                )}
              </div>
            )}
          </div>
          {reviewError && <p className="line-3d-fallback-message" role="alert">{reviewError}</p>}
          {replayMode && (
            <div className="mt-4">
              {replayLoading ? (
                <p className="line-review-empty" role="status">Loading stored replay events…</p>
              ) : replayError ? (
                <p className="line-3d-fallback-message" role="alert">{replayError}</p>
              ) : replayRunId ? (
                <Suspense fallback={<p className="line-review-empty" role="status">Loading replay controls…</p>}>
                  <ReplayControls
                    events={replayEvents}
                    runLabel={`${replayRunId.slice(0, 8)} · VERSION ${reviewVersion}`}
                  />
                </Suspense>
              ) : (
                <p className="line-review-empty">No completed simulation run is available for replay.</p>
              )}
            </div>
          )}
          {reviewLoading ? (
            <p className="line-review-empty" role="status">Loading saved line version…</p>
          ) : reviewModel ? (
            <div className="line-review-workspace">
              <Suspense fallback={<p className="line-review-empty" role="status">Loading 3D review tools…</p>}>
                <Line3DReview
                  edges={reviewEdges}
                  machines={reviewMachines}
                  nodes={reviewNodes}
                  onSelectNode={(nodeId) => {
                    setSelectedNodeId(nodeId);
                    setSelectedEdgeId(null);
                  }}
                  selectedNodeId={selectedNodeId}
                />
              </Suspense>
              <aside className="line-model-panel line-asset-inspector" aria-label="Machine and component inspector">
                <p className="line-panel-label">SAVED VERSION ASSET INSPECTOR</p>
                {inspectorNode ? (
                  <>
                    <h4 className="text-base font-semibold">{inspectorNode.data.label}</h4>
                    <p className="text-xs text-ink/60">
                      {inspectorNode.type?.toUpperCase() ?? "MACHINE"} · MODEL NODE {inspectorNode.id}
                    </p>
                    {inspectorNode.type === "machine" && selectedMachine ? (
                      <>
                        {selectedMachine.archived_at && (
                          <p className="line-3d-fallback-message">This saved version references an archived machine asset.</p>
                        )}
                          <p className="text-xs text-ink/60">Stored asset metadata only; this view contains no live telemetry.</p>
                          <dl className="line-asset-details">
                            <div><dt>Asset</dt><dd>{selectedMachine.name}</dd></div>
                            <div><dt>Identity</dt><dd>{selectedMachine.identity}</dd></div>
                            <div><dt>Template</dt><dd>{selectedMachine.machine_type === "custom" ? selectedMachine.custom_type_name || "Custom station" : selectedMachine.machine_type.replaceAll("_", " ")}</dd></div>
                            <div><dt>Recorded state</dt><dd>{selectedMachine.operating_state}</dd></div>
                            <div><dt>Manufacturer / model</dt><dd>{[selectedMachine.manufacturer, selectedMachine.model].filter(Boolean).join(" / ") || "Not recorded"}</dd></div>
                            <div><dt>Nominal cycle time</dt><dd>{selectedMachine.nominal_cycle_time_seconds} s</dd></div>
                            <div><dt>Nominal capacity</dt><dd>{selectedMachine.capacity_per_hour} units/hour</dd></div>
                        </dl>
                        <div className="line-asset-component-list">
                          <p className="line-panel-label">STORED COMPONENTS</p>
                          {assetDetailsError && <p className="text-sm text-red-800" role="alert">{assetDetailsError}</p>}
                          {assetDetailsLoading && <p className="text-xs text-ink/60" role="status">Loading stored components…</p>}
                          {!assetDetailsLoading && !assetDetailsError && components.length === 0 && <p className="text-xs text-ink/60">No components are recorded for this machine.</p>}
                          {components.map((component) => (
                            <button
                              aria-pressed={selectedComponentId === component.id}
                              className={`line-3d-equipment-item ${selectedComponentId === component.id ? "line-3d-equipment-selected" : ""}`}
                              key={component.id}
                              onClick={() => setSelectedComponentId(component.id)}
                              type="button"
                            >
                              <span>{component.name}</span>
                              <small>{component.component_type} · {component.identity}{component.archived_at ? " · ARCHIVED" : ""}</small>
                            </button>
                          ))}
                          {selectedComponent && (
                            <dl className="line-asset-details">
                              <div><dt>Selected component</dt><dd>{selectedComponent.name}</dd></div>
                              <div><dt>Component type</dt><dd>{selectedComponent.component_type}</dd></div>
                              <div><dt>Manufacturer / model</dt><dd>{[selectedComponent.manufacturer, selectedComponent.model].filter(Boolean).join(" / ") || "Not recorded"}</dd></div>
                            </dl>
                          )}
                        </div>
                      </>
                    ) : (
                      <p className="text-sm text-ink/65">
                        {inspectorNode.type === "machine"
                          ? "No linked machine asset is recorded for this model node."
                          : inspectorNode.type === "buffer"
                            ? `Finite buffer capacity: ${inspectorNode.data.buffer_capacity ?? "not configured"} units.`
                            : "Material boundary node from the saved model."}
                      </p>
                    )}
                  </>
                ) : (
                  <p className="text-sm text-ink/60">Select equipment in the view or equipment list to inspect its stored asset.</p>
                )}
              </aside>
            </div>
          ) : reviewVersion ? (
            <p className="line-review-empty" role="status">The selected saved version is not available for review.</p>
          ) : (
            <p className="line-review-empty">
              Save this line to create an immutable version for 3D review. Your draft is still editable in the 2D editor.
            </p>
          )}
        </section>
      )}

      {validation && (
        <section className={`line-validation ${validation.valid ? "line-validation-ok" : "line-validation-errors"}`} aria-live="polite">
          <h4 className="font-semibold">{validation.valid ? "Model validation passed" : `Model needs attention — ${validation.errors.length} issue(s)`}</h4>
          {validation.errors.map((item, index) => (
            <div className="line-validation-item" key={`${item.code}-${index}`}>
              <strong>{item.message}</strong>
              <p>{item.action}</p>
              <code>{item.path}</code>
            </div>
          ))}
          <details className="mt-3">
            <summary className="cursor-pointer font-mono text-xs">TRANSFER TIME ASSUMPTIONS</summary>
            <ul className="mt-2 space-y-1 text-xs">
              {validation.transfer_times.map((item) => <li key={item.edge_id}>{item.edge_id}: {item.seconds === null ? "unspecified" : `${item.seconds.toFixed(2)} s`} ({item.method.replaceAll("_", " ")})</li>)}
            </ul>
          </details>
        </section>
      )}
    </section>
  );
}

export function LineModelEditor({
  lineId,
  canEdit,
  onClose,
}: {
  lineId: string;
  canEdit: boolean;
  onClose: () => void;
}) {
  const [state, setState] = useState(EMPTY_STATE);
  const [revision, setRevision] = useState(0);
  const handleStateChange = useCallback((next: EditorState) => setState(next), []);
  const handleRevisionChange = useCallback((next: number) => setRevision(next), []);
  return (
    <ReactFlowProvider>
      <FlowCanvas
        canEdit={canEdit}
        lineId={lineId}
        onClose={onClose}
        onRevisionChange={handleRevisionChange}
        onStateChange={handleStateChange}
        revision={revision}
        state={state}
      />
    </ReactFlowProvider>
  );
}
