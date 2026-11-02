import { describe, expect, it } from "vitest";
import { findHierarchyMachine } from "./MetroReplay";

describe("MetroReplay hierarchy fixture", () => {
  it("finds a compressor across a factory with two lines and nested components", () => {
    const machine = findHierarchyMachine([
      {
        id: "factory-1",
        name: "Pilot Factory",
        lines: [
          {
            id: "line-1",
            name: "Packaging",
            machines: [{ id: "machine-a", name: "Packaging conveyor", components: [] }],
          },
          {
            id: "line-2",
            name: "Utilities",
            machines: [{
              id: "machine-compressor",
              name: "Compressor",
              components: [{ sensors: [{ id: "sensor-tp3", name: "TP3 pressure" }] }],
            }],
          },
        ],
      },
    ], "machine-compressor");

    expect(machine?.name).toBe("Compressor");
    expect(machine?.components.flatMap((component) => component.sensors)[0]?.id).toBe("sensor-tp3");
  });

  it("returns an empty sensor mapping without claiming mappings were submitted", () => {
    const machine = findHierarchyMachine([
      { id: "factory-1", name: "Factory", lines: [{ id: "line-1", name: "Line", machines: [{ id: "machine-empty", name: "Unknown", components: [{ sensors: [] }] }] }] },
    ], "machine-empty");
    expect(machine?.components.flatMap((component) => component.sensors)).toEqual([]);
  });
});
