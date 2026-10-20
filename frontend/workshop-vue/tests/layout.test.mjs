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

test('MCPs have one chronological far-right column and all compatible-stock links', () => {
 const graph=[{id:'SO',children:[{id:'CUT',children:[{id:'STOCK1',item_type:'STOCK'},{id:'STOCK2',item_type:'STOCK'}]}]}];
 const plans=[{id:'mcp:B',name:'B',creation:'2026-10-18 12:00',stock_ids:['STOCK1','STOCK2','STOCK1'],docstatus:0},
              {id:'mcp:A',name:'A',creation:'2026-10-17 12:00',stock_ids:['STOCK2'],docstatus:1}];
 const scene=layout(graph,new Set(['SO','CUT']),false,plans);
 assert.deepEqual(scene.mcps.map(p=>p.name),['A','B']);
 assert.equal(scene.mcps[0].x,scene.mcps[1].x);
 assert(scene.mcps.every(p=>p.x>Math.max(...scene.nodes.map(n=>n.x))));
 assert.equal(scene.edges.filter(e=>e.mcp).length,3);
 assert.equal(scene.edges.filter(e=>e.to.name==='B').length,2);
 assert(scene.mcps[0].y<scene.mcps[1].y);
 assert(scene.width>scene.mcps[0].x+218);
});

test('collapsed stock branches retain the link from the visible command', () => {
 const scene=layout([{id:'SO',children:[{id:'STOCK',item_type:'STOCK'}]}],new Set(),false,
   [{id:'mcp:A',name:'A',creation:'2026-10-18',stock_ids:['STOCK']}]);
 assert.equal(scene.mcps.length,1);
 assert.equal(scene.edges.filter(e=>e.mcp).length,1);
 assert.equal(scene.edges.find(e=>e.mcp).from.id,'SO');
});


test('server stock paths preserve links when order children have not been loaded', () => {
 const plan={id:'mcp:A',name:'A',creation:'2026-10-18',stock_ids:['S1','S2'],
   stock_paths:{S1:['SO','CUT','S1'],S2:['SO','CUT','S2']}};
 let scene=layout([{id:'SO',children:[]}],new Set(),false,[plan]);
 assert.equal(scene.edges.filter(e=>e.mcp).length,1);
 assert.equal(scene.edges.find(e=>e.mcp).from.id,'SO');
 scene=layout([{id:'SO',children:[{id:'CUT',children:[]}]}],new Set(['SO']),false,[plan]);
 assert.equal(scene.edges.filter(e=>e.mcp).length,1);
 assert.equal(scene.edges.find(e=>e.mcp).from.id,'CUT');
});
