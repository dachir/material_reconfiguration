import { test } from "node:test";
import assert from "node:assert/strict";
import { layout, flatten, routeFor } from "../src/layout.js";
const roots = [
  {
    id: "SO-1",
    children: [{ id: "line-1", children: [{ id: "cut", children: [] }] }],
  },
  { id: "SO-2", children: [] },
];
test("compact view has one independent root per Sales Order", () => {
  const scene = layout(roots, new Set());
  assert.deepEqual(
    scene.nodes.map((n) => n.id),
    ["SO-1", "SO-2"]
  );
  assert.equal(scene.edges.length, 0);
});
test("expansion keeps parents left of children and orthogonal endpoints", () => {
  const scene = layout(roots, new Set(["SO-1", "line-1"]));
  for (const e of scene.edges) assert.ok(e.to.x > e.from.x);
  assert.equal(scene.edges.length, 2);
});
test("selection resolves stable branch identities after refresh", () => {
  assert.equal(flatten(structuredClone(roots)).get("line-1").id, "line-1");
  assert.equal(flatten([]).has("line-1"), false);
});
test("only a single prepared MCP automatically opens its usual form", () => {
  assert.deepEqual(routeFor({ action: "mcp", mcps: ["MCP-1"] }), [
    "Form",
    "Material Cutting Plan",
    "MCP-1",
  ]);
  assert.equal(routeFor({ action: "mcp", mcps: ["MCP-1", "MCP-2"] }), null);
  assert.equal(routeFor({ action: "repack", stock_entries: ["SE-1"] }), null);
});
