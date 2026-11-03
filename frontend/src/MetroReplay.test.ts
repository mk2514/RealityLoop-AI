import { describe, expect, it } from "vitest";
import { findHierarchyMachine, windowCsv } from "./MetroReplay";

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

describe("windowCsv", () => {
  it("serialises exactly the selected rows, keeping the source index and timestamp columns", () => {
    const headers = ["", "timestamp", "TP3", "COMP"];
    const rows = [
      { "": "1400", timestamp: "2020-02-01 00:23:08", TP3: "8.068", COMP: "0.0" },
      { "": "1410", timestamp: "2020-02-01 00:23:17", TP3: "8.086", COMP: "0.0" },
    ];
    expect(windowCsv(headers, rows.slice(1))).toBe(",timestamp,TP3,COMP\n1410,2020-02-01 00:23:17,8.086,0.0\n");
    expect(windowCsv(headers, [])).toBe(",timestamp,TP3,COMP\n");
  });
});
