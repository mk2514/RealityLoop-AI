import { fireEvent, render, screen, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Line3DReview, type ReviewEdge, type ReviewMachine, type ReviewNode } from "./Line3DReview";

vi.mock("./line3d-renderer", () => ({
  createReviewRenderer: () => {
    throw new Error("WebGL context creation failed");
  },
}));

const machine: ReviewMachine = {
  id: "machine-1",
  name: "Assembly station",
  identity: "AS-01",
  machine_type: "assembly",
  custom_type_name: "",
};

const nodes: ReviewNode[] = [
  {
    id: "station-1",
    type: "machine",
    position: { x: 180, y: 120 },
    data: { label: "Assembly station", machine_id: machine.id, rotation: 0 },
  },
  {
    id: "buffer-1",
    type: "buffer",
    position: { x: 420, y: 120 },
    data: { label: "Buffer 1", rotation: 0, buffer_capacity: 24 },
  },
];

const edges: ReviewEdge[] = [
  { id: "edge-1", source: "station-1", target: "buffer-1", data: { route_kind: "normal" } },
];

afterEach(cleanup);

describe("3D line review without WebGL", () => {
  it("shows a useful static schematic and machine selection when renderer creation fails", async () => {
    const onSelectNode = vi.fn();
    render(
      <Line3DReview
        edges={edges}
        machines={[machine]}
        nodes={nodes}
        onSelectNode={onSelectNode}
        selectedNodeId={null}
      />,
    );

    expect((await screen.findByRole("status")).textContent).toMatch(/WebGL is unavailable/i);
    expect(screen.getByRole("group", { name: /static schematic of the saved line/i })).toBeTruthy();
    expect(screen.getByText("Illustrative material paths from the saved model only. No live or simulated job movement is shown.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "ZOOM IN" }).hasAttribute("disabled")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: /Assembly station.*AS-01/i }));
    expect(onSelectNode).toHaveBeenCalledWith("station-1");
    expect(screen.getByText("CAPACITY 24")).toBeTruthy();
  });

  it("supports keyboard selection from the schematic when WebGL is unavailable", async () => {
    const onSelectNode = vi.fn();
    const { rerender } = render(
      <Line3DReview
        edges={edges}
        machines={[machine]}
        nodes={nodes}
        onSelectNode={onSelectNode}
        selectedNodeId={null}
      />,
    );

    const schematicNode = await screen.findByRole("button", { name: "Select Assembly station" });
    schematicNode.focus();
    fireEvent.keyDown(schematicNode, { key: "Enter" });
    expect(onSelectNode).toHaveBeenCalledWith("station-1");
    rerender(
      <Line3DReview
        edges={edges}
        machines={[machine]}
        nodes={nodes}
        onSelectNode={onSelectNode}
        selectedNodeId="station-1"
      />,
    );
    expect(screen.getByRole("button", { name: /Assembly station.*AS-01/i }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Select Assembly station" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("rebuilds the review from updated saved-version nodes and connections", async () => {
    const updatedNodes: ReviewNode[] = [
      { ...nodes[0], data: { ...nodes[0].data, label: "CNC station" } },
      nodes[1],
      {
        id: "drill-1",
        type: "machine",
        position: { x: 660, y: 120 },
        data: { label: "Drill station", machine_id: "machine-2", rotation: 0 },
      },
    ];
    const updatedMachines = [
      machine,
      {
        id: "machine-2",
        name: "Drill press",
        identity: "DR-02",
        machine_type: "drilling",
        custom_type_name: "",
      },
    ];
    const { rerender, container } = render(
      <Line3DReview
        edges={edges}
        machines={[machine]}
        nodes={nodes}
        onSelectNode={vi.fn()}
        selectedNodeId={null}
      />,
    );

    expect(await screen.findByRole("button", { name: /Assembly station.*AS-01/i })).toBeTruthy();
    expect(container.querySelectorAll("path[marker-end]")).toHaveLength(1);
    rerender(
      <Line3DReview
        edges={[...edges, { id: "edge-2", source: "buffer-1", target: "drill-1" }]}
        machines={updatedMachines}
        nodes={updatedNodes}
        onSelectNode={vi.fn()}
        selectedNodeId={null}
      />,
    );

    expect(await screen.findByRole("button", { name: /Drill station.*DR-02/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Select CNC station" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Assembly station/i })).toBeNull();
    expect(container.querySelectorAll("path[marker-end]")).toHaveLength(2);
  });
});
