import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { useEffect, useRef, useState } from "react";
import { createReviewRenderer } from "./line3d-renderer";

export type ReviewMachine = {
  id: string;
  name: string;
  identity: string;
  machine_type: string;
  custom_type_name?: string;
};

export type ReviewNode = {
  id: string;
  type: "source" | "sink" | "machine" | "buffer";
  position: { x: number; y: number };
  data: {
    label: string;
    machine_id?: string;
    rotation: number;
    buffer_capacity?: number;
  };
};

export type ReviewEdge = {
  id: string;
  source: string;
  target: string;
  data?: { route_kind?: "normal" | "rework" };
};

type Props = {
  nodes: ReviewNode[];
  edges: ReviewEdge[];
  machines: ReviewMachine[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
};

type CameraMode = "isometric" | "top";

const IVORY = 0xf5f5ee;
const INK = 0x36382f;
const ORANGE = 0xf0441a;

function machineType(node: ReviewNode, machines: ReviewMachine[]): string {
  if (node.type !== "machine") return node.type;
  const asset = machines.find((machine) => machine.id === node.data.machine_id);
  return asset?.machine_type ?? "processing_station";
}

function outlinedBox(
  parent: THREE.Group,
  width: number,
  height: number,
  depth: number,
  position: THREE.Vector3,
  color = IVORY,
): THREE.Mesh {
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(width, height, depth),
    new THREE.MeshStandardMaterial({ color, roughness: 0.92 }),
  );
  mesh.position.copy(position);
  const outline = new THREE.LineSegments(
    new THREE.EdgesGeometry(mesh.geometry),
    new THREE.LineBasicMaterial({ color: INK }),
  );
  mesh.add(outline);
  parent.add(mesh);
  return mesh;
}

function outlinedCylinder(
  parent: THREE.Group,
  radius: number,
  height: number,
  position: THREE.Vector3,
  color = IVORY,
  radialSegments = 12,
): THREE.Mesh {
  const mesh = new THREE.Mesh(
    new THREE.CylinderGeometry(radius, radius, height, radialSegments),
    new THREE.MeshStandardMaterial({ color, roughness: 0.92 }),
  );
  mesh.position.copy(position);
  mesh.add(
    new THREE.LineSegments(
      new THREE.EdgesGeometry(mesh.geometry),
      new THREE.LineBasicMaterial({ color: INK }),
    ),
  );
  parent.add(mesh);
  return mesh;
}

function addEquipmentGeometry(group: THREE.Group, kind: string): THREE.Mesh {
  outlinedBox(group, 1.8, 0.14, 1.25, new THREE.Vector3(0, 0.08, 0), 0xe9e7dc);
  for (let index = 0; index < 4; index += 1) {
    const hatch = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(0.48 + index * 0.1, 0.157, 0.49),
      new THREE.Vector3(0.59 + index * 0.1, 0.157, 0.38),
    ]);
    group.add(new THREE.Line(hatch, new THREE.LineBasicMaterial({ color: 0xc3c1b6 })));
  }

  if (kind === "source" || kind === "sink") {
    const body = outlinedBox(group, 0.9, 0.78, 0.9, new THREE.Vector3(0, 0.55, 0), 0xe9e7dc);
    outlinedBox(group, 1.02, 0.12, 1.02, new THREE.Vector3(0, 0.98, 0), 0xe0ded2);
    return body;
  }

  if (kind === "buffer" || kind === "buffer_storage") {
    const body = outlinedBox(group, 1.42, 0.9, 0.96, new THREE.Vector3(0, 0.6, 0), 0xebe8d8);
    outlinedBox(group, 0.34, 0.35, 0.32, new THREE.Vector3(-0.4, 1.22, -0.15), 0xe0ded2);
    outlinedBox(group, 0.34, 0.35, 0.32, new THREE.Vector3(0, 1.22, -0.15), 0xe0ded2);
    outlinedBox(group, 0.34, 0.35, 0.32, new THREE.Vector3(0.4, 1.22, -0.15), 0xe0ded2);
    return body;
  }

  if (kind === "conveyor") {
    const body = outlinedBox(group, 1.7, 0.16, 0.82, new THREE.Vector3(0, 0.48, 0), 0xe3e1d6);
    for (const x of [-0.62, 0, 0.62]) {
      outlinedCylinder(group, 0.16, 0.82, new THREE.Vector3(x, 0.5, 0), 0xd5d3c7);
    }
    for (const x of [-0.62, 0.62]) {
      outlinedBox(group, 0.1, 0.42, 0.12, new THREE.Vector3(x, 0.26, 0), 0xd8d6ca);
    }
    return body;
  }

  if (kind === "cnc_cutting") {
    const cabinet = outlinedBox(group, 1.16, 1.18, 0.96, new THREE.Vector3(-0.18, 0.72, 0), 0xe5e3d8);
    outlinedBox(group, 0.34, 0.78, 0.12, new THREE.Vector3(0.44, 0.72, -0.52), 0xd8d6ca);
    outlinedBox(group, 0.48, 0.12, 0.44, new THREE.Vector3(0.34, 1.2, 0), 0xd8d6ca);
    outlinedCylinder(group, 0.08, 0.38, new THREE.Vector3(0.34, 0.95, 0), 0xcac8bc, 8);
    return cabinet;
  }

  if (kind === "drilling") {
    const base = outlinedBox(group, 1.24, 0.34, 0.98, new THREE.Vector3(0, 0.25, 0), 0xe4e2d7);
    outlinedBox(group, 0.24, 1.12, 0.3, new THREE.Vector3(-0.4, 0.88, 0), 0xd8d6ca);
    outlinedBox(group, 0.9, 0.18, 0.28, new THREE.Vector3(0.04, 1.38, 0), 0xe2e0d5);
    outlinedCylinder(group, 0.07, 0.42, new THREE.Vector3(0.34, 1.08, 0), 0xcac8bc, 8);
    return base;
  }

  if (kind === "inspection") {
    const base = outlinedBox(group, 1.24, 0.16, 0.96, new THREE.Vector3(0, 0.2, 0), 0xe4e2d7);
    for (const x of [-0.48, 0.48]) {
      outlinedBox(group, 0.14, 1.34, 0.16, new THREE.Vector3(x, 0.92, 0), 0xd8d6ca);
    }
    outlinedBox(group, 1.08, 0.16, 0.16, new THREE.Vector3(0, 1.56, 0), 0xe2e0d5);
    outlinedCylinder(group, 0.13, 0.24, new THREE.Vector3(0, 1.32, 0), 0xe5a77f, 10);
    return base;
  }

  if (kind === "assembly") {
    const table = outlinedBox(group, 1.52, 0.16, 1.02, new THREE.Vector3(0, 0.64, 0), 0xe3e1d6);
    for (const x of [-0.6, 0.6]) {
      for (const z of [-0.35, 0.35]) {
        outlinedBox(group, 0.1, 0.52, 0.1, new THREE.Vector3(x, 0.32, z), 0xd5d3c7);
      }
    }
    outlinedBox(group, 0.42, 0.26, 0.34, new THREE.Vector3(0, 0.86, 0), 0xe5e3d8);
    return table;
  }

  if (kind === "packaging") {
    const body = outlinedBox(group, 1.28, 1.12, 0.96, new THREE.Vector3(0, 0.7, 0), 0xe5e3d8);
    outlinedBox(group, 0.62, 0.44, 0.62, new THREE.Vector3(0, 1.48, 0), 0xe2dfd3);
    outlinedBox(group, 0.12, 0.18, 0.12, new THREE.Vector3(0, 1.26, -0.5), 0xd0cec2);
    return body;
  }

  const body = outlinedBox(group, 1.26, 1.12, 1.02, new THREE.Vector3(0, 0.7, 0), 0xe5e3d8);
  outlinedBox(group, 0.48, 0.32, 0.08, new THREE.Vector3(0, 0.84, -0.56), 0xd9d7cb);
  return body;
}

function makeLabel(text: string): THREE.Sprite {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 96;
  const context = canvas.getContext("2d");
  if (context) {
    context.fillStyle = "#f5f5ee";
    context.fillRect(1, 1, 510, 94);
    context.strokeStyle = "#36382f";
    context.lineWidth = 3;
    context.strokeRect(1, 1, 510, 94);
    context.fillStyle = "#191b17";
    context.font = "28px Arial";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(text.slice(0, 34), 256, 48, 480);
  }
  const texture = new THREE.CanvasTexture(canvas);
  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false }),
  );
  sprite.scale.set(2.4, 0.45, 1);
  return sprite;
}

function disposeScene(scene: THREE.Scene) {
  scene.traverse((object) => {
    if (!(object instanceof THREE.Mesh || object instanceof THREE.Line || object instanceof THREE.Sprite)) return;
    object.geometry?.dispose();
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    for (const material of materials) {
      if ("map" in material && material.map) material.map.dispose();
      material.dispose();
    }
  });
}

function SvgEquipment({
  node,
  kind,
  x,
  y,
  selected,
  onSelect,
}: {
  node: ReviewNode;
  kind: string;
  x: number;
  y: number;
  selected: boolean;
  onSelect: () => void;
}) {
  const stroke = selected ? "#f0441a" : "#36382f";
  const fill = kind === "buffer" || kind === "buffer_storage" ? "#eeebdc" : "#f5f5ee";
  return (
    <g
      aria-label={`Select ${node.data.label}`}
      aria-pressed={selected}
      className="line-3d-svg-node"
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
      role="button"
      tabIndex={0}
      transform={`translate(${x} ${y})`}
    >
      {kind === "conveyor" ? (
        <>
          <rect fill={fill} height="48" stroke={stroke} strokeWidth="2" width="118" x="-59" y="-24" />
          <circle cx="-33" cy="0" fill="#e1dfd4" r="13" stroke={stroke} />
          <circle cx="0" cy="0" fill="#e1dfd4" r="13" stroke={stroke} />
          <circle cx="33" cy="0" fill="#e1dfd4" r="13" stroke={stroke} />
        </>
      ) : kind === "drilling" || kind === "inspection" ? (
        <>
          <rect fill={fill} height="36" stroke={stroke} strokeWidth="2" width="108" x="-54" y="12" />
          <path d="M-34 12 V-45 H34 V12" fill="none" stroke={stroke} strokeWidth="5" />
          <path d="M8 -42 V-12" fill="none" stroke={stroke} strokeWidth="4" />
        </>
      ) : kind === "buffer" || kind === "buffer_storage" ? (
        <>
          <rect fill={fill} height="68" stroke={stroke} strokeDasharray="5 3" strokeWidth="2" width="112" x="-56" y="-34" />
          <path d="M-36 -14 H36 M-36 8 H36" stroke={stroke} />
        </>
      ) : kind === "cnc_cutting" ? (
        <>
          <rect fill={fill} height="76" stroke={stroke} strokeWidth="2" width="96" x="-48" y="-38" />
          <rect fill="#dedcd0" height="46" stroke={stroke} width="20" x="30" y="-23" />
          <path d="M-22 -8 H8 M-8 -22 V8" stroke={stroke} strokeWidth="2" />
        </>
      ) : kind === "assembly" ? (
        <>
          <path d="M-60 -16 H60 L48 34 H-48 Z" fill={fill} stroke={stroke} strokeWidth="2" />
          <path d="M-43 34 V49 M43 34 V49 M-25 -16 V-32 M25 -16 V-32" stroke={stroke} strokeWidth="2" />
        </>
      ) : (
        <>
          <rect fill={fill} height="70" stroke={stroke} strokeWidth="2" width="98" x="-49" y="-35" />
          <rect fill="#e4e2d7" height="20" stroke={stroke} width="42" x="-21" y="-12" />
        </>
      )}
      <text className="line-3d-svg-label" textAnchor="middle" x="0" y="70">{node.data.label.slice(0, 28)}</text>
      {typeof node.data.buffer_capacity === "number" && (
        <text className="line-3d-svg-capacity" textAnchor="middle" x="0" y="88">
          CAPACITY {node.data.buffer_capacity}
        </text>
      )}
    </g>
  );
}

function SchematicFallback({
  nodes,
  edges,
  machines,
  selectedNodeId,
  onSelectNode,
}: Props) {
  const positions = new Map(nodes.map((node) => [node.id, node.position]));
  const minX = Math.min(0, ...nodes.map((node) => node.position.x));
  const minY = Math.min(0, ...nodes.map((node) => node.position.y));
  const maxX = Math.max(800, ...nodes.map((node) => node.position.x));
  const maxY = Math.max(400, ...nodes.map((node) => node.position.y));
  const scale = Math.min(1, 700 / Math.max(1, maxX - minX), 300 / Math.max(1, maxY - minY));
  const offset = (node: ReviewNode) => ({
    x: 70 + (node.position.x - minX) * scale,
    y: 80 + (node.position.y - minY) * scale,
  });
  const width = Math.max(800, 140 + (maxX - minX) * scale);
  const height = Math.max(400, 150 + (maxY - minY) * scale);

  return (
    <svg
      aria-label="Static schematic of the saved line; WebGL is unavailable"
      className="line-3d-schematic"
      role="group"
      viewBox={`0 0 ${width} ${height}`}
    >
      <defs>
        <pattern height="12" id="line-3d-grid" patternUnits="userSpaceOnUse" width="12">
          <path d="M12 0H0V12" fill="none" stroke="#36382f" strokeOpacity="0.08" strokeWidth="0.6" />
        </pattern>
        <marker id="line-3d-arrow" markerHeight="7" markerWidth="7" orient="auto" refX="6" refY="3.5">
          <path d="M0 0L7 3.5L0 7Z" fill="#55574d" />
        </marker>
        <marker id="line-3d-rework-arrow" markerHeight="7" markerWidth="7" orient="auto" refX="6" refY="3.5">
          <path d="M0 0L7 3.5L0 7Z" fill="#b94a28" />
        </marker>
      </defs>
      <rect fill="#f5f5ee" height="100%" width="100%" />
      <rect fill="url(#line-3d-grid)" height="100%" width="100%" />
      {edges.map((edge) => {
        const source = positions.get(edge.source);
        const target = positions.get(edge.target);
        if (!source || !target) return null;
        const start = offset({ ...nodes.find((node) => node.id === edge.source)!, position: source });
        const end = offset({ ...nodes.find((node) => node.id === edge.target)!, position: target });
        const rework = edge.data?.route_kind === "rework";
        return (
          <path
            d={`M${start.x} ${start.y} L${end.x} ${end.y}`}
            fill="none"
            key={edge.id}
            markerEnd={`url(#line-3d-${rework ? "rework-" : ""}arrow)`}
            stroke={rework ? "#b94a28" : "#55574d"}
            strokeDasharray={rework ? "7 5" : undefined}
            strokeWidth="3"
          />
        );
      })}
      {nodes.map((node) => {
        const position = offset(node);
        return (
          <SvgEquipment
            key={node.id}
            kind={machineType(node, machines)}
            node={node}
            onSelect={() => onSelectNode(node.id)}
            selected={selectedNodeId === node.id}
            x={position.x}
            y={position.y}
          />
        );
      })}
    </svg>
  );
}

export function Line3DReview(props: Props) {
  const { nodes, edges, machines, selectedNodeId, onSelectNode } = props;
  const mountRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const cameraRef = useRef<THREE.OrthographicCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const nodeGroupsRef = useRef(new Map<string, THREE.Group>());
  const outlineRef = useRef(new Map<string, THREE.LineSegments[]>());
  const selectedRef = useRef(selectedNodeId);
  const onSelectRef = useRef(onSelectNode);
  const [unavailable, setUnavailable] = useState("");
  const [cameraMode, setCameraMode] = useState<CameraMode>("isometric");
  const [resetCount, setResetCount] = useState(0);

  selectedRef.current = selectedNodeId;
  onSelectRef.current = onSelectNode;

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = createReviewRenderer();
    } catch {
      setUnavailable("WebGL is unavailable in this browser or device.");
      return;
    }

    setUnavailable("");
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(IVORY);
    const camera = new THREE.OrthographicCamera(-9, 9, 6, -6, 0.1, 300);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = false;
    controls.enablePan = true;
    controls.enableRotate = true;
    controls.enableZoom = true;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(IVORY, 1);
    renderer.domElement.setAttribute("aria-label", "Interactive 3D review of the saved production line");
    renderer.domElement.setAttribute("role", "img");
    renderer.domElement.tabIndex = 0;
    mount.replaceChildren(renderer.domElement);
    scene.add(new THREE.AmbientLight(0xffffff, 2));
    const keyLight = new THREE.DirectionalLight(0xffffff, 2.2);
    keyLight.position.set(12, 20, 10);
    scene.add(keyLight);

    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(200, 200),
      new THREE.MeshStandardMaterial({ color: IVORY, roughness: 1 }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.04;
    scene.add(floor);
    const grid = new THREE.GridHelper(80, 80, 0xc3c1b6, 0xe0dfd6);
    grid.position.y = -0.025;
    scene.add(grid);

    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const groups = new Map<string, THREE.Group>();
    const outlines = new Map<string, THREE.LineSegments[]>();
    const worldPosition = (node: ReviewNode) =>
      new THREE.Vector3(node.position.x / 100, 0, node.position.y / 100);

    for (const node of nodes) {
      const position = worldPosition(node);
      const guide = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(position.x - 1.15, 0, position.z),
        new THREE.Vector3(position.x + 1.15, 0, position.z),
        new THREE.Vector3(position.x, 0, position.z - 0.8),
        new THREE.Vector3(position.x, 0, position.z + 0.8),
      ]);
      const guides = new THREE.LineSegments(
        guide,
        new THREE.LineDashedMaterial({
          color: 0xb9b8ad,
          dashSize: 0.12,
          gapSize: 0.1,
          transparent: true,
          opacity: 0.55,
        }),
      );
      guides.computeLineDistances();
      guides.position.y = -0.005;
      scene.add(guides);
    }

    for (const edge of edges) {
      const source = nodeById.get(edge.source);
      const target = nodeById.get(edge.target);
      if (!source || !target) continue;
      const start = worldPosition(source);
      const end = worldPosition(target);
      const direction = new THREE.Vector3().subVectors(end, start);
      const distance = direction.length();
      if (distance < 0.15) continue;
      const midpoint = new THREE.Vector3().addVectors(start, end).multiplyScalar(0.5);
      midpoint.y = 0.16;
      const rework = edge.data?.route_kind === "rework";
      const connection = new THREE.Mesh(
        new THREE.BoxGeometry(distance, 0.07, rework ? 0.25 : 0.34),
        new THREE.MeshStandardMaterial({
          color: rework ? 0xe2c3b4 : 0xe3e1d6,
          roughness: 0.95,
        }),
      );
      connection.position.copy(midpoint);
      connection.rotation.y = -Math.atan2(direction.z, direction.x);
      connection.add(
        new THREE.LineSegments(
          new THREE.EdgesGeometry(connection.geometry),
          new THREE.LineBasicMaterial({ color: rework ? 0xb94a28 : INK }),
        ),
      );
      scene.add(connection);

      const arrow = new THREE.Mesh(
        new THREE.ConeGeometry(0.13, 0.34, 4),
        new THREE.MeshStandardMaterial({ color: rework ? 0xb94a28 : 0x77786d }),
      );
      const arrowDirection = direction.normalize();
      arrow.position.set(end.x - arrowDirection.x * 0.12, 0.26, end.z - arrowDirection.z * 0.12);
      arrow.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), arrowDirection);
      scene.add(arrow);
    }

    for (const node of nodes) {
      const group = new THREE.Group();
      const location = worldPosition(node);
      group.position.copy(location);
      group.rotation.y = -(node.data.rotation * Math.PI) / 180;
      addEquipmentGeometry(group, machineType(node, machines));
      const labelText = node.type === "buffer" && typeof node.data.buffer_capacity === "number"
        ? `${node.data.label} · CAP ${node.data.buffer_capacity}`
        : node.data.label;
      const label = makeLabel(labelText);
      label.position.set(0, 2.05, 0);
      group.add(label);
      group.userData.nodeId = node.id;
      const nodeLines: THREE.LineSegments[] = [];
      group.traverse((object) => {
        if (object instanceof THREE.LineSegments && object.parent !== group) {
          object.userData.nodeId = node.id;
          nodeLines.push(object);
        }
      });
      groups.set(node.id, group);
      outlines.set(node.id, nodeLines);
      scene.add(group);
    }

    const minX = Math.min(0, ...nodes.map((node) => node.position.x / 100));
    const maxX = Math.max(8, ...nodes.map((node) => node.position.x / 100));
    const minZ = Math.min(0, ...nodes.map((node) => node.position.y / 100));
    const maxZ = Math.max(5, ...nodes.map((node) => node.position.y / 100));
    const center = new THREE.Vector3((minX + maxX) / 2, 0, (minZ + maxZ) / 2);
    controls.target.copy(center);
    const horizontalExtent = Math.max(8, maxX - minX) * 0.55;
    const verticalExtent = Math.max(5, maxZ - minZ) * 0.8;
    camera.position.set(center.x + 14, 16, center.z + 14);
    camera.lookAt(center);

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const pick = (event: PointerEvent) => {
      const bounds = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1;
      pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const intersections = raycaster.intersectObjects([...groups.values()], true);
      const nodeId = intersections
        .map((intersection) => {
          let object: THREE.Object3D | null = intersection.object;
          while (object && typeof object.userData.nodeId !== "string") object = object.parent;
          return object?.userData.nodeId as string | undefined;
        })
        .find((id): id is string => Boolean(id));
      if (nodeId) onSelectRef.current(nodeId);
    };
    renderer.domElement.addEventListener("pointerup", pick);
    const draw = () => renderer.render(scene, camera);
    controls.addEventListener("change", draw);
    const resize = () => {
      const width = Math.max(1, mount.clientWidth);
      const height = Math.max(1, mount.clientHeight);
      const aspect = width / height;
      const halfHeight = Math.max(4, horizontalExtent / aspect, verticalExtent);
      camera.left = -halfHeight * aspect;
      camera.right = halfHeight * aspect;
      camera.top = halfHeight;
      camera.bottom = -halfHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
      draw();
    };
    const observer = typeof ResizeObserver === "undefined"
      ? null
      : new ResizeObserver(resize);
    observer?.observe(mount);
    window.addEventListener("resize", resize);
    controls.update();
    resize();

    rendererRef.current = renderer;
    cameraRef.current = camera;
    controlsRef.current = controls;
    sceneRef.current = scene;
    nodeGroupsRef.current = groups;
    outlineRef.current = outlines;

    if (cameraMode === "top") {
      camera.up.set(0, 0, -1);
      camera.position.set(center.x, center.y + 35, center.z);
      camera.lookAt(center);
      controls.update();
      draw();
    }

    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", resize);
      renderer.domElement.removeEventListener("pointerup", pick);
      controls.removeEventListener("change", draw);
      controls.dispose();
      disposeScene(scene);
      renderer.dispose();
      mount.replaceChildren();
      rendererRef.current = null;
      cameraRef.current = null;
      controlsRef.current = null;
      sceneRef.current = null;
      nodeGroupsRef.current.clear();
      outlineRef.current.clear();
    };
  }, [nodes, edges, machines, cameraMode, resetCount]);

  useEffect(() => {
    for (const [nodeId, lineSegments] of outlineRef.current) {
      for (const line of lineSegments) {
        const material = line.material as THREE.LineBasicMaterial;
        material.color.set(nodeId === selectedNodeId ? ORANGE : INK);
      }
    }
    if (sceneRef.current && rendererRef.current && cameraRef.current) {
      rendererRef.current.render(sceneRef.current, cameraRef.current);
    }
  }, [selectedNodeId]);

  function resetView() {
    setCameraMode("isometric");
    setResetCount((count) => count + 1);
  }

  function zoomBy(factor: number) {
    const camera = controlsRef.current?.object;
    if (!(camera instanceof THREE.OrthographicCamera)) return;
    camera.zoom = THREE.MathUtils.clamp(camera.zoom * factor, 0.35, 3.5);
    camera.updateProjectionMatrix();
    if (sceneRef.current && rendererRef.current) {
      rendererRef.current.render(sceneRef.current, camera);
    }
  }

  const selectableNodes = nodes.filter((node) => node.type === "machine");

  return (
    <div className="line-3d-review" aria-label="Saved line 3D review">
      <div className="line-3d-toolbar">
        <label className="form-field">
          <span>Camera view</span>
          <select
            className="registry-select"
            disabled={Boolean(unavailable)}
            onChange={(event) => setCameraMode(event.target.value === "top" ? "top" : "isometric")}
            value={cameraMode}
          >
            <option value="isometric">Orthographic / isometric</option>
            <option value="top">Top</option>
          </select>
        </label>
        <div className="line-3d-controls" aria-label="3D camera controls">
          <button className="secondary-button" disabled={Boolean(unavailable)} onClick={() => zoomBy(1.2)} title={unavailable || undefined} type="button">ZOOM IN</button>
          <button className="secondary-button" disabled={Boolean(unavailable)} onClick={() => zoomBy(1 / 1.2)} title={unavailable || undefined} type="button">ZOOM OUT</button>
          <button className="secondary-button" disabled={Boolean(unavailable)} onClick={resetView} title={unavailable || undefined} type="button">RESET VIEW</button>
        </div>
      </div>
      {unavailable ? (
        <>
          <p className="line-3d-fallback-message" role="status">
            {unavailable} A static schematic is shown instead. The 2D editor and stored asset inspection remain available; no operating animation is displayed.
          </p>
          <SchematicFallback {...props} />
        </>
      ) : (
        <div className="line-3d-viewport" ref={mountRef} />
      )}
      <p className="line-3d-caption">
        Illustrative material paths from the saved model only. No live or simulated job movement is shown.
      </p>
      <div className="line-3d-equipment" aria-label="Select machine in 3D review">
        <p className="line-panel-label">EQUIPMENT SELECTION</p>
        {selectableNodes.length === 0 ? (
          <p className="text-sm text-ink/60">This saved version has no machine assets.</p>
        ) : selectableNodes.map((node) => {
          const asset = machines.find((machine) => machine.id === node.data.machine_id);
          return (
            <button
              aria-pressed={selectedNodeId === node.id}
              className={`line-3d-equipment-item ${selectedNodeId === node.id ? "line-3d-equipment-selected" : ""}`}
              key={node.id}
              onClick={() => onSelectNode(node.id)}
              type="button"
            >
              <span>{node.data.label}</span>
              <small>{asset ? `${asset.name} · ${asset.identity}` : "No linked machine asset"}</small>
            </button>
          );
        })}
      </div>
    </div>
  );
}
