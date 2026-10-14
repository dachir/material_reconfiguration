(() => {
  var __defProp = Object.defineProperty;
  var __defProps = Object.defineProperties;
  var __getOwnPropDescs = Object.getOwnPropertyDescriptors;
  var __getOwnPropSymbols = Object.getOwnPropertySymbols;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __propIsEnum = Object.prototype.propertyIsEnumerable;
  var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: true, configurable: true, writable: true, value }) : obj[key] = value;
  var __spreadValues = (a, b) => {
    for (var prop in b || (b = {}))
      if (__hasOwnProp.call(b, prop))
        __defNormalProp(a, prop, b[prop]);
    if (__getOwnPropSymbols)
      for (var prop of __getOwnPropSymbols(b)) {
        if (__propIsEnum.call(b, prop))
          __defNormalProp(a, prop, b[prop]);
      }
    return a;
  };
  var __spreadProps = (a, b) => __defProps(a, __getOwnPropDescs(b));

  // ../mat_reco/mat_reco/public/js/mcp_ux20.bundle.js
  (function(root) {
    "use strict";
    const namespace = root.MatRecoMCPUX20 = root.MatRecoMCPUX20 || {};
    const INITIAL = Object.freeze({
      status: "idle",
      action: null,
      selectedSheet: null,
      sourceNodeId: null,
      targetNodeIds: [],
      preview: null,
      busy: false,
      error: null
    });
    function copy(value) {
      if (Array.isArray(value))
        return value.map(copy);
      if (value && typeof value === "object") {
        const object = {};
        Object.keys(value).forEach((key) => {
          object[key] = copy(value[key]);
        });
        return object;
      }
      return value;
    }
    function createStore(initial) {
      let state = copy(Object.assign({}, INITIAL, initial || {}));
      const subscribers = /* @__PURE__ */ new Set();
      let destroyed = false;
      return {
        getState: function() {
          return copy(state);
        },
        subscribe: function(listener) {
          if (destroyed)
            throw new Error("MCP UX state store destroyed");
          if (typeof listener !== "function")
            throw new TypeError("Expected listener");
          subscribers.add(listener);
          return () => subscribers.delete(listener);
        },
        update: function(changes) {
          if (destroyed)
            throw new Error("MCP UX state store destroyed");
          const next = typeof changes === "function" ? changes(copy(state)) : changes;
          if (!next || typeof next !== "object" || Array.isArray(next))
            throw new TypeError("Expected state changes");
          state = Object.assign({}, state, copy(next));
          const snapshot = copy(state);
          subscribers.forEach((listener) => listener(copy(snapshot)));
          return snapshot;
        },
        reset: function() {
          return this.update(copy(INITIAL));
        },
        destroy: function() {
          subscribers.clear();
          destroyed = true;
        }
      };
    }
    namespace.createStateStore = createStore;
    namespace.initialState = copy(INITIAL);
  })(typeof window !== "undefined" ? window : globalThis);
  (function(root) {
    "use strict";
    const namespace = root.MatRecoMCPUX20 = root.MatRecoMCPUX20 || {};
    const ACTIONS = Object.freeze(["Resize", "Destroy", "Move", "Merge", "Single"]);
    const TYPES = Object.freeze({
      Resize: ["finished_good", "leftover", "waste"],
      Destroy: ["finished_good", "leftover", "waste"],
      Move: ["finished_good"],
      Merge: ["leftover", "waste"],
      Single: ["leftover", "waste"]
    });
    function createController(store, options) {
      if (!store || typeof store.update !== "function")
        throw new TypeError("State store required");
      const allowed = options && options.canApplyAction;
      function permitted(action, type) {
        return ACTIONS.includes(action) && TYPES[action].includes(type) && (!allowed || Boolean(allowed(action, type)));
      }
      function select(node, sheet) {
        const state = store.getState();
        if (state.busy)
          return false;
        if (!node || !node.id)
          return false;
        if (state.status === "selecting_target")
          return this.addTarget(node);
        store.update({
          status: "selected",
          action: null,
          sourceNodeId: String(node.id),
          sourceNodeType: String(node.node_type || ""),
          selectedSheet: sheet || state.selectedSheet,
          targetNodeIds: [],
          preview: null,
          error: null
        });
        return true;
      }
      function begin(action) {
        const state = store.getState();
        if (state.busy || !state.sourceNodeId || !permitted(action, state.sourceNodeType))
          return false;
        store.update({ action, status: ["Move", "Merge", "Single"].includes(action) ? "selecting_target" : "action_active", targetNodeIds: [], preview: null, error: null });
        return true;
      }
      function addTarget(node) {
        const state = store.getState();
        if (state.status !== "selecting_target" || state.busy || !node || !node.id || String(node.id) === state.sourceNodeId || state.targetNodeIds.includes(String(node.id)))
          return false;
        store.update({ targetNodeIds: state.targetNodeIds.concat(String(node.id)), error: null });
        return true;
      }
      function showPreview(preview) {
        const state = store.getState();
        if (!state.action || state.busy)
          return false;
        store.update({ status: "preview", preview, error: null });
        return true;
      }
      function cancel() {
        if (store.getState().busy)
          return false;
        store.update({
          status: "idle",
          action: null,
          sourceNodeId: null,
          sourceNodeType: null,
          targetNodeIds: [],
          preview: null,
          error: null
        });
        return true;
      }
      function setError(error) {
        store.update({ status: "error", busy: false, error: String(error || "Unknown error") });
      }
      function setBusy(busy) {
        store.update({ busy: Boolean(busy) });
      }
      return {
        select,
        begin,
        addTarget,
        showPreview,
        cancel,
        setError,
        setBusy,
        canStart: permitted,
        actions: ACTIONS.slice()
      };
    }
    namespace.createInteractionController = createController;
  })(typeof window !== "undefined" ? window : globalThis);
  (function(root) {
    "use strict";
    const namespace = root.MatRecoMCPUX20 = root.MatRecoMCPUX20 || {};
    const instances = /* @__PURE__ */ new WeakMap();
    function createWorkspace(frm, options) {
      options = options || {};
      if (!frm || typeof frm !== "object" && typeof frm !== "function")
        throw new TypeError("Frappe form required");
      if (instances.has(frm))
        return instances.get(frm);
      if (!namespace.createStateStore || !namespace.createInteractionController) {
        throw new Error("Load mcp_state_store.js and mcp_interaction_controller.js first");
      }
      const store = namespace.createStateStore();
      const controller = namespace.createInteractionController(store, options);
      let active = false;
      let destroyed = false;
      const workspace = {
        store,
        controller,
        mount() {
          if (destroyed)
            throw new Error("Workspace destroyed");
          if (options.enabled !== true)
            return false;
          active = true;
          return true;
        },
        isMounted() {
          return active;
        },
        unmount() {
          active = false;
          controller.cancel();
        },
        destroy() {
          if (destroyed)
            return;
          this.unmount();
          store.destroy();
          instances.delete(frm);
          destroyed = true;
        }
      };
      instances.set(frm, workspace);
      return workspace;
    }
    namespace.createWorkspace = createWorkspace;
  })(typeof window !== "undefined" ? window : globalThis);
  (function(root) {
    "use strict";
    const ns = root.MatRecoMCPUX20 = root.MatRecoMCPUX20 || {};
    const SVG = "http://www.w3.org/2000/svg";
    function el(tag, attrs, text) {
      const e = document.createElementNS(SVG, tag);
      Object.keys(attrs || {}).forEach((k) => e.setAttribute(k, String(attrs[k])));
      if (text != null)
        e.textContent = String(text);
      return e;
    }
    function numValue(v) {
      return Number(v) || 0;
    }
    function valid(n) {
      return n && Number(n.length_mm) > 0 && Number(n.width_mm) > 0;
    }
    function sheetNodes(tree) {
      return (tree && Array.isArray(tree.nodes) ? tree.nodes : []).filter((n) => n && n.node_type === "input_serial" && valid(n));
    }
    function children(sheet) {
      return (Array.isArray(sheet.children) ? sheet.children : []).filter((n) => valid(n) && n.node_type !== "input_serial" && !n.is_preexisting_cutout && !n.is_single_cutout && !(n.node_type === "destroyed" && n.single_logical_cutout));
    }
    function color(type) {
      return type === "finished_good" ? "#dbeafe" : type === "leftover" ? "#e2e8f0" : type === "waste" ? "#fee2e2" : "#f1f5f9";
    }
    function createCanvas(container, onSelect) {
      if (!container || !container.appendChild)
        throw new TypeError("Container required");
      let current = [], selectedSheet = 0, selectedId = null;
      const host = document.createElement("div");
      host.className = "mcpux-canvas";
      host.style.cssText = "min-width:0;flex:1;overflow:auto;padding:14px 18px 22px;background:#fff;box-sizing:border-box;";
      const nav = document.createElement("div");
      nav.style.cssText = "display:flex;gap:10px;align-items:center;justify-content:space-between;margin-bottom:14px;flex-wrap:wrap";
      const prev = document.createElement("button"), next = document.createElement("button"), caption = document.createElement("span");
      prev.type = next.type = "button";
      prev.textContent = "\u2039 Pr\xE9c\xE9dente";
      next.textContent = "Suivante \u203A";
      const navControls = document.createElement("div");
      navControls.style.cssText = "display:flex;align-items:center;gap:8px;flex-wrap:wrap";
      const selector = document.createElement("select");
      selector.setAttribute("aria-label", "Choisir une plaque");
      selector.style.cssText = "max-width:240px;min-width:110px;padding:7px 10px;border:1px solid #cbd5e1;border-radius:7px;background:#fff;color:#334155;font-size:12px";
      for (const b of [prev, next])
        b.style.cssText = "border:1px solid #cbd5e1;border-radius:7px;background:#fff;color:#334155;padding:7px 10px;cursor:pointer;font-size:12px";
      caption.style.cssText = "color:#475569;font-size:12px;font-weight:500;overflow-wrap:anywhere";
      navControls.classList.add("mcpux-nav-controls");
      navControls.append(prev, selector, next);
      nav.append(caption, navControls);
      host.appendChild(nav);
      const drawing = document.createElement("div");
      drawing.style.cssText = "min-height:340px;display:flex;align-items:center;justify-content:center;border:1px solid #e2e8f0;border-radius:9px;background:#f8fafc;padding:16px;box-sizing:border-box;overflow:hidden";
      host.appendChild(drawing);
      container.appendChild(host);
      function redraw() {
        drawing.replaceChildren();
        if (!current.length) {
          drawing.textContent = "Aucune plaque \xE0 pr\xE9visualiser";
          caption.textContent = "0 / 0";
          prev.disabled = next.disabled = true;
          selector.replaceChildren();
          return;
        }
        selectedSheet = Math.max(0, Math.min(selectedSheet, current.length - 1));
        const s = current[selectedSheet];
        caption.textContent = `Plaque ${selectedSheet + 1}/${current.length} \xB7 ${s.serial_no || s.id || ""} \xB7 ${s.length_mm} \xD7 ${s.width_mm} mm`;
        prev.disabled = selectedSheet === 0;
        next.disabled = selectedSheet === current.length - 1;
        selector.value = String(selectedSheet);
        const w = Number(s.length_mm), h = Number(s.width_mm);
        const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, role: "img", "aria-label": `Plan de d\xE9coupe ${s.serial_no || s.id}`, style: "width:100%;max-height:600px;display:block;overflow:visible" });
        const defs = el("defs");
        const pattern = el("pattern", { id: "mcpux-hatch", patternUnits: "userSpaceOnUse", width: 16, height: 16, patternTransform: "rotate(45)" });
        pattern.appendChild(el("rect", { width: 16, height: 16, fill: "#f3f5f8" }));
        pattern.appendChild(el("line", { x1: 0, y1: 0, x2: 0, y2: 16, stroke: "#d4dbe6", "stroke-width": 5 }));
        defs.appendChild(pattern);
        svg.appendChild(defs);
        svg.append(el("rect", { x: 0, y: 0, width: w, height: h, fill: "#f8fbff", stroke: "#627a96", "stroke-width": Math.max(w, h) * 2e-3 }));
        for (const n of children(s)) {
          const x = Number(n.x) || 0, y = Number(n.y) || 0, nw = Number(n.effective_length_mm) || Number(n.length_mm), nh = Number(n.effective_width_mm) || Number(n.width_mm);
          const group = el("g", { "data-node-id": n.id || "", "data-node-type": n.node_type || "", tabindex: 0, role: "button", "aria-label": `${n.node_type} ${n.label || n.id}`, style: "cursor:pointer;outline:none" });
          const r = el("rect", { x, y, width: nw, height: nh, fill: n.node_type === "leftover" ? "url(#mcpux-hatch)" : color(n.node_type), stroke: n.id === selectedId ? "#2563eb" : "#94a3b8", "stroke-width": Math.max(w, h) * (n.id === selectedId ? 6e-3 : 2e-3) });
          if (Array.isArray(n.visual_regions) && n.visual_regions.length) {
            for (const region of n.visual_regions) {
              group.appendChild(el("rect", { x: numValue(region.x), y: numValue(region.y), width: numValue(region.length_mm), height: numValue(region.width_mm), fill: color("leftover"), stroke: "#94a3b8", "stroke-width": Math.max(w, h) * 2e-3 }));
            }
          } else
            group.appendChild(r);
          if (!n.visual_regions && nw > 140 && nh > 70) {
            group.appendChild(el("text", { x: x + nw / 2, y: y + nh / 2 - 18, "text-anchor": "middle", "dominant-baseline": "middle", "font-size": Math.min(48, Math.max(19, Math.min(nw / 12, nh / 5))), fill: "#23446b", "pointer-events": "none", "font-weight": "600" }, n.node_type === "leftover" ? "Chute" : n.label || n.id || n.node_type));
            group.appendChild(el("text", { x: x + nw / 2, y: y + nh / 2 + 38, "text-anchor": "middle", "dominant-baseline": "middle", "font-size": Math.min(35, Math.max(16, Math.min(nw / 17, nh / 7))), fill: "#64748b", "pointer-events": "none" }, `${nw} \xD7 ${nh} mm`));
          }
          group.addEventListener("click", () => {
            if (typeof onSelect === "function")
              onSelect(n, s);
          });
          group.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              if (onSelect)
                onSelect(n, s);
            }
          });
          svg.appendChild(group);
        }
        drawing.appendChild(svg);
      }
      function changeSheet(index) {
        selectedSheet = index;
        selectedId = null;
        redraw();
        if (typeof onSelect === "function")
          onSelect(null, current[selectedSheet]);
      }
      prev.addEventListener("click", () => changeSheet(selectedSheet - 1));
      next.addEventListener("click", () => changeSheet(selectedSheet + 1));
      selector.addEventListener("change", () => changeSheet(Number(selector.value)));
      return { setTree(tree) {
        const oldSerial = current[selectedSheet] && (current[selectedSheet].serial_no || current[selectedSheet].id);
        current = sheetNodes(tree);
        const keep = current.findIndex((x) => (x.serial_no || x.id) === oldSerial);
        selectedSheet = keep >= 0 ? keep : 0;
        selectedId = null;
        selector.replaceChildren();
        current.forEach((sheet, index) => {
          const option = document.createElement("option");
          option.value = String(index);
          option.textContent = `Plaque ${index + 1} \xB7 ${sheet.serial_no || sheet.id}`;
          selector.appendChild(option);
        });
        redraw();
      }, setSelection(id) {
        var _a;
        if (selectedId === id)
          return;
        selectedId = id;
        for (const g of drawing.querySelectorAll("svg [data-node-id]")) {
          const active = g.getAttribute("data-node-id") === String(id || "");
          const rect = g.querySelector("rect");
          if (!rect)
            continue;
          rect.setAttribute("stroke", active ? "#2563eb" : "#94a3b8");
          rect.setAttribute("stroke-width", Math.max(1, Number(((_a = current[selectedSheet]) == null ? void 0 : _a.length_mm) || 1e3)) * (active ? 6e-3 : 2e-3));
        }
      }, getSheets() {
        return current.slice();
      }, destroy() {
        host.remove();
      }, redraw };
    }
    ns.createCanvasRenderer = createCanvas;
    ns.getUX03Sheets = sheetNodes;
  })(typeof window !== "undefined" ? window : globalThis);
  (function(root) {
    "use strict";
    const ns = root.MatRecoMCPUX20 = root.MatRecoMCPUX20 || {};
    function createToolbar(host, controller, store) {
      const bar = document.createElement("div");
      bar.style.cssText = "display:none;flex-wrap:wrap;gap:6px;padding:10px;border:1px solid #e2e8f0;border-radius:10px;background:white;box-shadow:0 2px 8px #0001";
      bar.setAttribute("aria-label", "Actions de d\xE9coupe");
      host.appendChild(bar);
      const unsub = store.subscribe(render);
      function render(state) {
        bar.replaceChildren();
        bar.style.display = state.sourceNodeId ? "flex" : "none";
        if (!state.sourceNodeId)
          return;
        for (const action of controller.actions) {
          if (!controller.canStart(action, state.sourceNodeType))
            continue;
          const btn = document.createElement("button");
          btn.type = "button";
          btn.textContent = action;
          btn.disabled = state.busy;
          btn.style.cssText = "padding:6px 10px;border:1px solid #cbd5e1;border-radius:6px;background:" + (state.action === action ? "#dbeafe" : "white") + ";cursor:pointer";
          btn.addEventListener("click", () => controller.begin(action));
          bar.appendChild(btn);
        }
      }
      render(store.getState());
      return { destroy() {
        unsub();
        bar.remove();
      } };
    }
    ns.createContextToolbar = createToolbar;
  })(typeof window !== "undefined" ? window : globalThis);
  (function(root) {
    "use strict";
    const ns = root.MatRecoMCPUX20 = root.MatRecoMCPUX20 || {};
    function createPanel(host, store, controller) {
      const panel = document.createElement("aside");
      panel.style.cssText = "min-width:225px;max-width:275px;flex:0 0 245px;padding:15px;background:#f8fafc;border-left:1px solid #e2e8f0;overflow-wrap:anywhere";
      host.appendChild(panel);
      const unsub = store.subscribe(render);
      function render(s) {
        panel.replaceChildren();
        const title = document.createElement("strong");
        title.textContent = "Action en cours";
        panel.appendChild(title);
        const data = [["\xC9tat", s.status], ["Source", s.sourceNodeId || "\u2014"], ["Action", s.action || "\u2014"], ["Cibles", (s.targetNodeIds || []).join(", ") || "\u2014"]];
        for (const [label, val] of data) {
          const p = document.createElement("p");
          p.style.cssText = "font-size:12px;margin:12px 0";
          const b = document.createElement("b");
          b.textContent = label + " : ";
          p.append(b, document.createTextNode(val));
          panel.appendChild(p);
        }
        const hint = document.createElement("p");
        hint.style.cssText = "font-size:12px;color:#64748b";
        hint.textContent = s.status === "selecting_target" ? "Cliquez sur une autre zone. La validation m\xE9tier reste d\xE9sactiv\xE9e dans UX-03." : "S\xE9lectionnez une zone et choisissez une action. UX-03 est une pr\xE9visualisation sans sauvegarde.";
        panel.appendChild(hint);
        if (s.error) {
          const e = document.createElement("p");
          e.textContent = s.error;
          panel.appendChild(e);
        }
        const cancel = document.createElement("button");
        cancel.type = "button";
        cancel.textContent = "Annuler la s\xE9lection";
        cancel.addEventListener("click", () => controller.cancel());
        panel.appendChild(cancel);
      }
      render(store.getState());
      return { destroy() {
        unsub();
        panel.remove();
      } };
    }
    ns.createContextPanel = createPanel;
  })(typeof window !== "undefined" ? window : globalThis);
  (function(root) {
    "use strict";
    const ns = root.MatRecoMCPUX20 = root.MatRecoMCPUX20 || {};
    const num = (v) => Number(v) || 0;
    const TARGET_ACTIONS = /* @__PURE__ */ new Set(["Move", "Merge", "Single"]);
    const normalType = (n) => String(n && n.node_type || "").toLowerCase();
    function validPiece(n) {
      return n && n.id && !n.is_preexisting_cutout && !n.is_single_cutout && !n.single_logical_cutout && num(n.effective_length_mm || n.length_mm) > 0 && num(n.effective_width_mm || n.width_mm) > 0;
    }
    function candidate(source, target, action, sourceSheet, targetSheet) {
      if (!validPiece(source) || !validPiece(target) || String(source.id) === String(target.id))
        return false;
      if (action === "Move")
        return normalType(source) === "finished_good" && ["leftover", "waste"].includes(normalType(target));
      if (action === "Merge" || action === "Single")
        return ["leftover", "waste"].includes(normalType(source)) && ["leftover", "waste"].includes(normalType(target)) && String(sourceSheet) === String(targetSheet);
      return false;
    }
    function indexTree(tree) {
      const sheets = (tree && Array.isArray(tree.nodes) ? tree.nodes : []).filter((s) => s && s.node_type === "input_serial");
      const byId = /* @__PURE__ */ new Map();
      for (const sheet of sheets) {
        const key = String(sheet.serial_no || sheet.id);
        for (const child of sheet.children || [])
          if (child && child.id)
            byId.set(String(child.id), { node: child, sheet: key });
      }
      return { sheets, byId };
    }
    function description(action, source, targets, parameters) {
      const t = targets || [];
      const p = parameters || {};
      if (action === "Resize")
        return { title: "Redimensionnement \xE0 v\xE9rifier", detail: `${num(p.length_mm)} \xD7 ${num(p.width_mm)} mm demand\xE9s. Aucune g\xE9om\xE9trie n\u2019est encore recalcul\xE9e.`, ready: num(p.length_mm) > 0 && num(p.width_mm) > 0 && num(p.length_mm) <= num(source && source.effective_length_mm || source && source.length_mm) && num(p.width_mm) <= num(source && source.effective_width_mm || source && source.width_mm) };
      if (action === "Destroy")
        return { title: "Destruction envisag\xE9e", detail: "La pi\xE8ce s\xE9lectionn\xE9e sera propos\xE9e pour destruction apr\xE8s validation m\xE9tier.", ready: !!source };
      if (action === "Single")
        return { title: "Single envisag\xE9", detail: "Deux zones r\xE9siduelles candidates. L\u2019encoche, la surface et les collisions seront v\xE9rifi\xE9es c\xF4t\xE9 Python.", ready: t.length === 1 };
      if (action === "Merge")
        return { title: "Fusion envisag\xE9e", detail: "Zones r\xE9siduelles candidates. Adjacence et g\xE9om\xE9trie non valid\xE9es \xE0 ce stade.", ready: t.length >= 1 };
      if (action === "Move")
        return { title: "D\xE9placement envisag\xE9", detail: "Zone r\xE9ceptrice candidate. Placement pr\xE9cis, swap/swing et chevauchements non valid\xE9s.", ready: t.length === 1 };
      return { title: "S\xE9lection", detail: "Choisissez une action.", ready: false };
    }
    function createGuide(store, controller, tree) {
      let index = indexTree(tree);
      let params = {};
      function item(id) {
        return index.byId.get(String(id)) || null;
      }
      function candidates() {
        const s = store.getState();
        const source = item(s.sourceNodeId);
        if (!source || !TARGET_ACTIONS.has(s.action))
          return [];
        return [...index.byId.entries()].filter(([id, target]) => candidate(source.node, target.node, s.action, source.sheet, target.sheet)).map(([id]) => id);
      }
      function select(node, sheet) {
        const s = store.getState();
        if (s.status === "preview")
          return false;
        if (s.status === "selecting_target") {
          const source = item(s.sourceNodeId);
          const target = item(node && node.id);
          if (!source || !target || !candidate(source.node, target.node, s.action, source.sheet, target.sheet)) {
            store.update({ error: "Zone non candidate pour cette action." });
            return false;
          }
          if (s.action === "Move" || s.action === "Single") {
            if (s.targetNodeIds.length)
              return false;
            controller.addTarget(node);
            return buildPreview();
          }
          return controller.addTarget(node);
        }
        return controller.select(node, sheet && (sheet.serial_no || sheet.id) || null);
      }
      function begin(action) {
        params = {};
        return controller.begin(action);
      }
      function setResize(length, width) {
        params = { length_mm: num(length), width_mm: num(width) };
        return buildPreview();
      }
      function buildPreview() {
        const s = store.getState();
        if (!s.action)
          return false;
        const source = item(s.sourceNodeId);
        const targets = s.targetNodeIds.map(item).filter(Boolean).map((x) => x.node);
        const result = description(s.action, source && source.node, targets, params);
        if (!result.ready) {
          store.update({ error: "Param\xE8tres ou cibles insuffisants pour l\u2019aper\xE7u." });
          return false;
        }
        return controller.showPreview({ kind: "intention_only", action: s.action, sourceNodeId: s.sourceNodeId, targetNodeIds: s.targetNodeIds.slice(), parameters: Object.assign({}, params), title: result.title, detail: result.detail, verifiedByServer: false, committed: false });
      }
      function cancel() {
        params = {};
        return controller.cancel();
      }
      function refresh(treeNext) {
        index = indexTree(treeNext);
        params = {};
        controller.cancel();
      }
      function stateInfo() {
        const s = store.getState();
        const source = item(s.sourceNodeId);
        const targets = s.targetNodeIds.map(item).filter(Boolean).map((x) => x.node);
        return { candidateIds: candidates(), preview: s.preview, parameters: Object.assign({}, params), description: description(s.action, source && source.node, targets, params) };
      }
      return { select, begin, setResize, buildPreview, cancel, refresh, stateInfo, candidateIds: candidates, getItem: item };
    }
    ns.createUX04Guide = createGuide;
    ns.ux04Candidate = candidate;
    ns.ux04Description = description;
    ns.ux04IndexTree = indexTree;
  })(typeof window !== "undefined" ? window : globalThis);
  (function(root) {
    "use strict";
    const ns = root.MatRecoMCPUX20 = root.MatRecoMCPUX20 || {};
    function element(tag, text) {
      const x = document.createElement(tag);
      if (text != null)
        x.textContent = text;
      return x;
    }
    function mount(frm, mountAt, options) {
      if (!options || options.enabled !== true)
        return null;
      if (!frm || !frm.doc || !mountAt || !ns.createWorkspace || !ns.createCanvasRenderer || !ns.createUX04Guide)
        throw new Error("UX-02, UX-03 canvas, and UX-04 interactions must be loaded.");
      const ws = ns.createWorkspace(frm, { enabled: true });
      ws.mount();
      const section = element("section");
      section.setAttribute("data-mcp-ux04", "true");
      section.style.cssText = "margin:12px 0;border:1px solid #cbd5e1;border-radius:10px;overflow:hidden;background:white";
      const title = element("header", "MCP UX 2.0 \u2014 UX-04 \xB7 Pr\xE9visualisation uniquement (aucune modification enregistr\xE9e)");
      title.style.cssText = "padding:12px;background:#eef2ff;font-weight:600";
      section.appendChild(title);
      const toolbar = element("div");
      toolbar.style.cssText = "display:flex;flex-wrap:wrap;gap:7px;padding:10px";
      section.appendChild(toolbar);
      const body = element("div");
      body.style.cssText = "display:flex;min-height:360px;overflow:auto";
      section.appendChild(body);
      const aside = element("aside");
      aside.style.cssText = "width:260px;flex:0 0 260px;border-left:1px solid #e2e8f0;padding:12px;font-size:13px";
      body.appendChild(aside);
      mountAt.appendChild(section);
      let guide = null, disposed = false, tree = null;
      const canvasHost = element("div");
      canvasHost.style.cssText = "flex:1;min-width:0";
      body.insertBefore(canvasHost, aside);
      const canvas = ns.createCanvasRenderer(canvasHost, (node, sheet) => {
        if (!guide)
          return;
        if (node)
          guide.select(node, sheet);
        else
          guide.cancel();
      });
      function readTree() {
        const raw = frm.doc.mcp_mode === "Retour Terrain" ? frm.doc.effective_result_json || frm.doc.result_json : frm.doc.result_json || frm.doc.effective_result_json;
        const doc = typeof raw === "string" ? JSON.parse(raw || "{}") : raw || {};
        if (!Array.isArray(doc.nodes))
          throw new Error("MCP JSON: nodes manquant");
        return doc;
      }
      function highlight() {
        const state = ws.store.getState(), meta = guide && guide.stateInfo();
        const svg = section.querySelector("svg");
        if (!svg)
          return;
        const candidates = new Set(meta ? meta.candidateIds : []);
        const chosen = new Set(state.targetNodeIds || []);
        for (const group of svg.querySelectorAll("[data-node-id]")) {
          const id = group.getAttribute("data-node-id");
          const rect = group.querySelector("rect");
          if (!rect)
            continue;
          rect.setAttribute("stroke", id === state.sourceNodeId ? "#2563eb" : chosen.has(id) ? "#16a34a" : candidates.has(id) ? "#0d9488" : "#94a3b8");
          if (id === state.sourceNodeId || chosen.has(id) || candidates.has(id))
            rect.setAttribute("stroke-width", "9");
          rect.setAttribute("stroke-dasharray", candidates.has(id) && !chosen.has(id) ? "18 12" : "none");
          group.style.cursor = candidates.has(id) || state.status !== "selecting_target" ? "pointer" : "not-allowed";
        }
      }
      function render() {
        const s = ws.store.getState(), meta = guide && guide.stateInfo();
        canvas.setSelection(s.sourceNodeId);
        toolbar.replaceChildren();
        aside.replaceChildren();
        if (s.sourceNodeId) {
          for (const action of ws.controller.actions) {
            if (!ws.controller.canStart(action, s.sourceNodeType))
              continue;
            const b = element("button", action);
            b.type = "button";
            b.disabled = s.busy;
            b.style.cssText = "padding:6px 10px;border:1px solid #cbd5e1;border-radius:6px;background:" + (s.action === action ? "#dbeafe" : "white");
            b.addEventListener("click", () => guide.begin(action));
            toolbar.appendChild(b);
          }
        }
        const title2 = element("strong", "Action en cours");
        title2.style.cssText = "display:block;font-size:15px;color:#0f172a;padding-bottom:10px;border-bottom:1px solid #e2e8f0";
        aside.appendChild(title2);
        function text(t) {
          const p = element("p", t);
          p.style.cssText = "margin:9px 0";
          aside.appendChild(p);
        }
        text("\xC9tat : " + s.status);
        text("Source : " + (s.sourceNodeId || "\u2014"));
        text("Action : " + (s.action || "\u2014"));
        text("Cibles : " + (s.targetNodeIds.length ? s.targetNodeIds.join(", ") : "\u2014"));
        if (s.status === "selecting_target")
          text("Cibles candidates en turquoise. Compatibilit\xE9 g\xE9om\xE9trique NON valid\xE9e.");
        if (s.action === "Resize" && s.status !== "preview") {
          const info = guide.getItem(s.sourceNodeId);
          const dims = info && info.node || {};
          const l = element("input"), w = element("input");
          for (const [x, value, label] of [[l, dims.effective_length_mm || dims.length_mm, "Longueur (mm)"], [w, dims.effective_width_mm || dims.width_mm, "Largeur (mm)"]]) {
            x.type = "number";
            x.min = "1";
            x.step = "any";
            x.value = String(value || "");
            x.setAttribute("aria-label", label);
            x.style.cssText = "max-width:105px;margin:5px";
            text(label);
            aside.appendChild(x);
          }
          const p = element("button", "Pr\xE9visualiser Resize");
          p.type = "button";
          p.addEventListener("click", () => guide.setResize(l.value, w.value));
          aside.appendChild(p);
        }
        if (["Merge"].includes(s.action) && s.status === "selecting_target" && s.targetNodeIds.length) {
          const b = element("button", "Pr\xE9visualiser Merge");
          b.type = "button";
          b.addEventListener("click", () => guide.buildPreview());
          aside.appendChild(b);
        }
        if (s.action === "Destroy" && s.status === "action_active") {
          const b = element("button", "Pr\xE9visualiser Destroy");
          b.type = "button";
          b.addEventListener("click", () => guide.buildPreview());
          aside.appendChild(b);
        }
        if (s.preview) {
          text(s.preview.title);
          text(s.preview.detail);
          text("Aper\xE7u indicatif uniquement : aucune validation serveur, aucune application m\xE9tier.");
          const tag = element("strong", "NON ENREGISTR\xC9");
          tag.style.color = "#a16207";
          aside.appendChild(tag);
        }
        if (s.error)
          text("Erreur : " + s.error);
        const cancel = element("button", "Annuler");
        cancel.type = "button";
        cancel.style.cssText = "display:block;margin-top:15px";
        cancel.addEventListener("click", () => guide.cancel());
        aside.appendChild(cancel);
        highlight();
      }
      let unsub = null;
      function load() {
        const next = readTree();
        tree = next;
        canvas.setTree(tree);
        if (guide)
          guide.refresh(tree);
        else
          guide = ns.createUX04Guide(ws.store, ws.controller, tree);
        render();
        return canvas.getSheets().length;
      }
      load();
      unsub = ws.store.subscribe(render);
      const reposition = () => locateToolbar();
      window.addEventListener("resize", reposition);
      canvasHost.addEventListener("scroll", reposition, true);
      return { refresh: load, getState: () => ws.store.getState(), destroy() {
        if (disposed)
          return;
        disposed = true;
        if (unsub)
          unsub();
        window.removeEventListener("resize", reposition);
        canvasHost.removeEventListener("scroll", reposition, true);
        canvas.destroy();
        section.remove();
        ws.destroy();
      } };
    }
    ns.mountUX04Preview = mount;
  })(typeof window !== "undefined" ? window : globalThis);
  (function(root) {
    "use strict";
    const ns = root.MatRecoMCPUX20 = root.MatRecoMCPUX20 || {};
    const N = (v) => Number(v) || 0, EPS = 1e-6;
    const typ = (n) => String(n && n.node_type || "").toLowerCase();
    const free = (n) => ["leftover", "waste"].includes(typ(n)) && !n.is_preexisting_cutout && !n.is_single_cutout && !n.single_logical_cutout;
    const rect = (n) => {
      var _a, _b;
      return { x: N(n.x), y: N(n.y), length_mm: N((_a = n.effective_length_mm) != null ? _a : n.length_mm), width_mm: N((_b = n.effective_width_mm) != null ? _b : n.width_mm), node_type: typ(n) };
    };
    const area = (r) => r.length_mm * r.width_mm;
    function overlap(a, b) {
      return Math.min(a.x + a.length_mm, b.x + b.length_mm) - Math.max(a.x, b.x) > EPS && Math.min(a.y + a.width_mm, b.y + b.width_mm) - Math.max(a.y, b.y) > EPS;
    }
    function ensure(p, message) {
      if (!p)
        throw new Error(message);
    }
    function geometry(nodes, action, serial) {
      ensure(nodes.length > 1, action + " requires at least two regions");
      ensure(nodes.every(free), "Only available leftover/waste regions can be selected");
      ensure(nodes.some((n) => typ(n) === "leftover"), "At least one leftover is required");
      ensure(nodes.every((n) => String(n.source_serial_no || n.serial_no || serial) === String(serial)), "Regions must belong to one input Serial No");
      ensure(new Set(nodes.map((n) => String(n.id))).size === nodes.length, "Duplicate regions");
      const rs = nodes.map(rect);
      ensure(rs.every((r) => r.length_mm > 0 && r.width_mm > 0), "Invalid region dimensions");
      for (let i = 0; i < rs.length; i++)
        for (let j = i + 1; j < rs.length; j++)
          ensure(!overlap(rs[i], rs[j]), "Regions overlap");
      return rs;
    }
    function bounds(rs) {
      let x = Math.min(...rs.map((r) => r.x)), y = Math.min(...rs.map((r) => r.y));
      let X = Math.max(...rs.map((r) => r.x + r.length_mm)), Y = Math.max(...rs.map((r) => r.y + r.width_mm));
      return { x, y, length_mm: X - x, width_mm: Y - y };
    }
    function grid(rs) {
      const b = bounds(rs), xs = [...new Set(rs.flatMap((r) => [r.x, r.x + r.length_mm]))].sort((a, b2) => a - b2), ys = [...new Set(rs.flatMap((r) => [r.y, r.y + r.width_mm]))].sort((a, b2) => a - b2);
      const occupied = [];
      for (let j = 0; j < ys.length - 1; j++) {
        const row = [];
        for (let i = 0; i < xs.length - 1; i++) {
          const cx = (xs[i] + xs[i + 1]) / 2, cy = (ys[j] + ys[j + 1]) / 2;
          row.push(rs.some((r) => cx >= r.x - EPS && cx < r.x + r.length_mm - EPS && cy >= r.y - EPS && cy < r.y + r.width_mm - EPS));
        }
        occupied.push(row);
      }
      return { b, xs, ys, occupied };
    }
    function single(rs) {
      ensure(rs.length === 2, "Single needs exactly two regions");
      const b = bounds(rs), s = rs.reduce((v, r) => v + area(r), 0), missing = area(b) - s;
      ensure(missing > EPS, "Single needs a corner notch; use Merge for rectangles");
      const g = grid(rs);
      for (const hx of g.xs.slice(1, -1))
        for (const hy of g.ys.slice(1, -1)) {
          const hole = { x: b.x, y: b.y, length_mm: hx - b.x, width_mm: hy - b.y };
          if (Math.abs(area(hole) - missing) > EPS || rs.some((r) => overlap(r, hole)))
            continue;
          return __spreadProps(__spreadValues({}, b), { removed_length_mm: hole.length_mm, removed_width_mm: hole.width_mm, area_mm2: s });
        }
      throw new Error("Single requires one missing upper-left corner");
    }
    function merge(rs) {
      const g = grid(rs);
      let best = null;
      for (let y = 0; y < g.ys.length - 1; y++)
        for (let x = 0; x < g.xs.length - 1; x++) {
          if (!g.occupied[y][x])
            continue;
          for (let Y = y + 1; Y < g.ys.length; Y++)
            for (let X = x + 1; X < g.xs.length; X++) {
              let ok = true;
              for (let j = y; j < Y && ok; j++)
                for (let i = x; i < X; i++)
                  if (!g.occupied[j][i]) {
                    ok = false;
                    break;
                  }
              if (!ok)
                continue;
              const r = { x: g.xs[x], y: g.ys[y], length_mm: g.xs[X] - g.xs[x], width_mm: g.ys[Y] - g.ys[y] };
              if (!best || area(r) > area(best) + EPS)
                best = r;
            }
        }
      ensure(best, "No mergeable region");
      const residuals = [];
      const taken = g.occupied.map((row, j) => row.map((v, i) => v && g.xs[i] >= best.x - EPS && g.xs[i + 1] <= best.x + best.length_mm + EPS && g.ys[j] >= best.y - EPS && g.ys[j + 1] <= best.y + best.width_mm + EPS));
      for (let j = 0; j < g.ys.length - 1; j++)
        for (let i = 0; i < g.xs.length - 1; i++) {
          if (!g.occupied[j][i] || taken[j][i])
            continue;
          let end = i + 1;
          while (end < g.xs.length - 1 && g.occupied[j][end] && !taken[j][end])
            end++;
          let bottom = j + 1, can = true;
          while (bottom < g.ys.length - 1 && can) {
            for (let k = i; k < end; k++)
              if (!g.occupied[bottom][k] || taken[bottom][k])
                can = false;
            if (can)
              bottom++;
          }
          for (let yy = j; yy < bottom; yy++)
            for (let xx = i; xx < end; xx++)
              taken[yy][xx] = true;
          residuals.push({ x: g.xs[i], y: g.ys[j], length_mm: g.xs[end] - g.xs[i], width_mm: g.ys[bottom] - g.ys[j] });
        }
      return __spreadProps(__spreadValues({}, best), { residual_rects: residuals });
    }
    function build(action, source, targets, parameters, context) {
      var _a, _b;
      parameters = parameters || {};
      context = context || {};
      ensure(["Resize", "Destroy", "Merge", "Single"].includes(action), "Unsupported UX-05 action");
      ensure(source && source.id, "Source required");
      const serial = String(context.source_serial_no || source.source_serial_no || source.serial_no || "");
      ensure(serial, "Input Serial No required");
      const l = N((_a = source.effective_length_mm) != null ? _a : source.length_mm), w = N((_b = source.effective_width_mm) != null ? _b : source.width_mm);
      ensure(l > 0 && w > 0, "Invalid source dimensions");
      const originalArea = l * w;
      let payload = { plan_node_id: String(source.id), source_serial_no: serial, original_node_type: source.node_type, original_item_code: source.item_code || "", original_length_mm: l, original_width_mm: w, original_area_mm2: originalArea, incident_action: action, affected_node_ids_json: JSON.stringify([String(source.id)]), group_area_mm2: originalArea, new_node_type: source.node_type, new_item_code: source.item_code || "", new_length_mm: l, new_width_mm: w, new_area_mm2: originalArea, include_in_repack: 1, is_active: 1, remarks: parameters.remarks || "" };
      if (action === "Destroy") {
        payload.new_node_type = "destroyed";
        payload.new_length_mm = payload.new_width_mm = payload.new_area_mm2 = 0;
        payload.include_in_repack = 0;
        return payload;
      }
      if (action === "Resize") {
        const nl = N(parameters.length_mm), nw = N(parameters.width_mm);
        ensure(nl > 0 && nw > 0 && nl <= l + EPS && nw <= w + EPS, "Resize must reduce dimensions");
        payload.new_length_mm = nl;
        payload.new_width_mm = nw;
        payload.new_area_mm2 = nl * nw;
        payload.new_node_type = Math.min(nl, nw) < N(context.min_leftover_dimension_mm || 500) ? "waste" : "leftover";
        return payload;
      }
      const nodes = [source, ...targets || []];
      const rs = geometry(nodes, action, serial), ids = nodes.map((n) => String(n.id));
      payload.affected_node_ids_json = JSON.stringify(ids);
      payload.group_area_mm2 = rs.reduce((sum, r) => sum + area(r), 0);
      payload.original_length_mm = payload.original_width_mm = payload.original_area_mm2 = 0;
      payload.original_item_code = "";
      if (action === "Single") {
        const g = single(rs);
        Object.assign(payload, { new_node_type: "leftover", new_length_mm: g.length_mm, new_width_mm: g.width_mm, new_area_mm2: g.area_mm2, target_x_mm: g.x, target_y_mm: g.y, remarks: JSON.stringify({ removed_length_mm: g.removed_length_mm, removed_width_mm: g.removed_width_mm }) });
        return payload;
      }
      const m = merge(rs);
      Object.assign(payload, { new_node_type: Math.min(m.length_mm, m.width_mm) < N(context.min_leftover_dimension_mm || 500) ? "waste" : "leftover", new_length_mm: m.length_mm, new_width_mm: m.width_mm, new_area_mm2: area(m), target_x_mm: m.x, target_y_mm: m.y, remarks: JSON.stringify({ residual_rects: m.residual_rects }) });
      ensure(Math.abs(area(m) + m.residual_rects.reduce((s, r) => s + area(r), 0) - payload.group_area_mm2) < EPS, "Merge surface conservation failed");
      return payload;
    }
    ns.buildUX05Incident = build;
    ns.ux05Geometry = Object.freeze({ single, merge, rect, overlap });
  })(typeof window !== "undefined" ? window : globalThis);
  (function(root) {
    "use strict";
    const ns = root.MatRecoMCPUX20 = root.MatRecoMCPUX20 || {};
    function createBridge(options) {
      const drafts = [];
      const builder = ns.buildUX05Incident;
      if (typeof builder !== "function")
        throw new Error("Load mcp_ux05_action_adapter.js first");
      function prepare(preview, lookup, context) {
        if (!preview || !preview.action || !preview.sourceNodeId)
          throw new Error("Complete UX-04 preview required");
        if (!["Resize", "Destroy", "Single", "Merge"].includes(preview.action))
          throw new Error("Action not in UX-05");
        if (typeof lookup !== "function")
          throw new TypeError("Node lookup required");
        const source = lookup(preview.sourceNodeId);
        const targets = (preview.targetNodeIds || []).map((id) => {
          const n = lookup(id);
          if (!n)
            throw new Error("Unknown target node " + id);
          return n;
        });
        const payload = builder(preview.action, source, targets, preview.parameters, context);
        const draft = Object.freeze({ action: preview.action, payload: Object.freeze(__spreadValues({}, payload)), committed: false, serverVerified: false });
        return draft;
      }
      function stage(draft) {
        if (!draft || draft.committed !== false || draft.serverVerified !== false)
          throw new Error("Only uncommitted UX-05 drafts can be staged");
        drafts.push(draft);
        return drafts.length;
      }
      return { prepare, stage, list: () => drafts.slice(), clear: () => {
        drafts.length = 0;
      }, get stagedCount() {
        return drafts.length;
      }, get enabledForWrites() {
        return false;
      } };
    }
    ns.createUX05DraftBridge = createBridge;
  })(typeof window !== "undefined" ? window : globalThis);
  (function(root) {
    "use strict";
    const ns = root.MatRecoMCPUX20 = root.MatRecoMCPUX20 || {};
    const EPS = 1e-6;
    function num(x) {
      return Number(x) || 0;
    }
    function ensure(ok, message) {
      if (!ok)
        throw new Error(message);
    }
    function kind(n) {
      return String(n && n.node_type || "").trim().toLowerCase();
    }
    function size(n) {
      var _a, _b;
      return { length_mm: num(n && ((_a = n.effective_length_mm) != null ? _a : n.length_mm)), width_mm: num(n && ((_b = n.effective_width_mm) != null ? _b : n.width_mm)) };
    }
    function box(n) {
      const s = size(n);
      return __spreadValues({ x: num(n && n.x), y: num(n && n.y) }, s);
    }
    function overlap(a, b) {
      return Math.min(a.x + a.length_mm, b.x + b.length_mm) - Math.max(a.x, b.x) > EPS && Math.min(a.y + a.width_mm, b.y + b.width_mm) - Math.max(a.y, b.y) > EPS;
    }
    function contains(outer, inner) {
      return inner.x >= outer.x - EPS && inner.y >= outer.y - EPS && inner.x + inner.length_mm <= outer.x + outer.length_mm + EPS && inner.y + inner.width_mm <= outer.y + outer.width_mm + EPS;
    }
    function excluded(n) {
      return !!(n && (n.is_preexisting_cutout || n.is_single_cutout || n.single_logical_cutout));
    }
    function isFree(n) {
      return ["leftover", "waste"].includes(kind(n)) && !excluded(n);
    }
    function targetSheet(tree, serial) {
      return (tree && tree.nodes || []).find((n) => String(n.serial_no || n.id) === String(serial));
    }
    function findPiece(tree, id) {
      for (const sheet of tree && tree.nodes || []) {
        const node = (sheet.children || []).find((n) => String(n.id) === String(id));
        if (node)
          return { node, sheet };
      }
      return null;
    }
    function plan(input) {
      input = input || {};
      const tree = input.tree, sourceId = String(input.sourceNodeId || ""), targetSerial = String(input.targetSerialNo || "");
      const found = findPiece(tree, sourceId);
      ensure(found, "Source piece not present in current cutting tree");
      const source = found.node;
      ensure(kind(source) === "finished_good", "Move requires a finished_good source");
      const sourceSerial = String(found.sheet.serial_no || found.sheet.id);
      const sheet = targetSheet(tree, targetSerial);
      ensure(sheet, "Target Serial No not found in cutting tree");
      const sourceSize = size(source);
      ensure(sourceSize.length_mm > 0 && sourceSize.width_mm > 0, "Source dimensions must be positive");
      const desired = __spreadValues({ x: num(input.targetX), y: num(input.targetY) }, sourceSize);
      ensure(Number.isFinite(Number(input.targetX)) && Number.isFinite(Number(input.targetY)), "Target coordinates required");
      const sheetDimensions = size(sheet);
      ensure(contains(__spreadValues({ x: 0, y: 0 }, sheetDimensions), desired), "Target placement is outside sheet bounds");
      const zoneId = String(input.targetZoneId || "");
      const zones = (sheet.children || []).filter(isFree).filter((n) => !zoneId || String(n.id) === zoneId);
      const zone = zones.find((n) => contains(box(n), desired));
      ensure(zone, "Target position must fit entirely inside a free region");
      const exact = Math.abs(size(zone).length_mm - sourceSize.length_mm) < EPS && Math.abs(size(zone).width_mm - sourceSize.width_mm) < EPS;
      const moveCase = exact ? "swap" : "swing";
      for (const child of sheet.children || []) {
        if (String(child.id) === sourceId)
          continue;
        if (isFree(child) && !excluded(child))
          continue;
        if (kind(child) !== "finished_good" && kind(child) !== "destroyed" && kind(child) !== "destroy" && !excluded(child))
          continue;
        const occupied = box(child);
        if (occupied.length_mm > 0 && occupied.width_mm > 0)
          ensure(!overlap(occupied, desired), "Move overlaps an occupied or excluded region");
      }
      const samePosition = sourceSerial === targetSerial && Math.abs(num(source.x) - desired.x) < EPS && Math.abs(num(source.y) - desired.y) < EPS;
      ensure(!samePosition, "Source already occupies this position");
      const dimensions = sourceSize, area = dimensions.length_mm * dimensions.width_mm;
      const payload = { plan_node_id: sourceId, source_serial_no: sourceSerial, original_node_type: "finished_good", original_item_code: source.piece_item_code || source.item_code || "", original_length_mm: dimensions.length_mm, original_width_mm: dimensions.width_mm, original_area_mm2: area, incident_action: "Move", affected_node_ids_json: JSON.stringify([sourceId]), group_area_mm2: area, new_node_type: "finished_good", new_item_code: source.piece_item_code || source.item_code || "", new_length_mm: dimensions.length_mm, new_width_mm: dimensions.width_mm, new_area_mm2: area, target_serial_no: targetSerial, target_zone_id: zoneId || String(zone.id), target_x_mm: desired.x, target_y_mm: desired.y, move_case: moveCase, include_in_repack: 1, is_active: 1, remarks: "" };
      return Object.freeze({ payload: Object.freeze(payload), case: moveCase, sourceSerial, targetSerial, targetZoneId: String(zone.id), preview: Object.freeze({ kind: "move_intention", verifiedByServer: false, source: box(source), target: desired, case: moveCase }), committed: false, serverVerified: false });
    }
    ns.createUX06MoveDraft = plan;
    ns.ux06MoveGeometry = Object.freeze({ box, contains, overlap, isFree });
  })(typeof window !== "undefined" ? window : globalThis);
  (function(root) {
    "use strict";
    const ns = root.MatRecoMCPUX20 = root.MatRecoMCPUX20 || {};
    function createBridge() {
      const drafts = [];
      function prepare(preview, tree) {
        if (typeof ns.createUX06MoveDraft !== "function")
          throw new Error("Load mcp_ux06_move_adapter.js first");
        if (!preview || preview.action !== "Move")
          throw new Error("Move preview required");
        const target = preview.parameters || {};
        return ns.createUX06MoveDraft({ tree, sourceNodeId: preview.sourceNodeId, targetSerialNo: target.target_serial_no, targetZoneId: target.target_zone_id, targetX: target.target_x_mm, targetY: target.target_y_mm });
      }
      function stage(draft) {
        if (!draft || draft.committed !== false || draft.serverVerified !== false)
          throw new Error("Only local uncommitted Move drafts can be staged");
        drafts.push(draft);
        return drafts.length;
      }
      return Object.freeze({ prepare, stage, list: () => drafts.slice(), clear: () => {
        drafts.length = 0;
      }, get stagedCount() {
        return drafts.length;
      }, get enabledForWrites() {
        return false;
      } });
    }
    ns.createUX06MoveBridge = createBridge;
  })(typeof window !== "undefined" ? window : globalThis);
  (function(root) {
    "use strict";
    const ns = root.MatRecoMCPUX20 = root.MatRecoMCPUX20 || {};
    const LABEL = { Move: "D\xE9placer", Merge: "Fusionner", Single: "Chute en L", Resize: "Redimensionner", Destroy: "D\xE9truire" };
    const SYMBOL = { Move: "\u2197", Merge: "\u229E", Single: "\u231E", Resize: "\u2922", Destroy: "\xD7" };
    const el = (tag, txt, cls) => {
      const n = document.createElement(tag);
      if (txt !== void 0 && txt !== null)
        n.textContent = txt;
      if (cls)
        n.className = cls;
      return n;
    };
    const style = `
.mcp20-editor{--b:#dce4ef;font-family:inherit;border:1px solid var(--b);border-radius:12px;background:#fff;margin:10px 0;overflow:hidden;color:#1e293b}
.mcp20-editor *{box-sizing:border-box}
.mcp20-head{display:flex;justify-content:space-between;align-items:center;padding:13px 17px;background:#f8fafc;border-bottom:1px solid var(--b);gap:12px;flex-wrap:wrap}
.mcp20-head strong{font-size:15px;color:#16315b}.mcp20-head small{color:#64748b}
.mcp20-grid{display:grid;grid-template-columns:minmax(0,1fr) 300px;min-height:560px}
.mcp20-main{position:relative;min-width:0;background:#fff}
.mcp20-main .mcpux-canvas{padding:12px 16px 22px!important;min-height:540px}
.mcp20-main .mcpux-canvas>div:nth-child(2){min-height:475px!important}
.mcp20-side{border-left:1px solid var(--b);background:#fbfcff;padding:17px;font-size:13px;min-width:0}
.mcp20-side h4{font-size:15px;margin:0 0 12px;color:#1d3557;font-weight:700}
.mcp20-line{margin:9px 0;word-break:break-word}.mcp20-k{display:block;color:#64748b;font-size:11px;margin-bottom:3px}
.mcp20-actions{display:none;position:absolute;z-index:30;gap:4px;flex-wrap:wrap;padding:6px;border-radius:11px;border:1px solid #d7e3f4;background:#fff;box-shadow:0 10px 28px #1e293b24;max-width:min(96%,600px)}
.mcp20-actions button{border:0;border-radius:7px;background:transparent;padding:7px 8px;color:#1e293b;font-size:12px;cursor:pointer;white-space:nowrap}
.mcp20-actions button:hover,.mcp20-actions button[data-current=true]{background:#e8f0ff;color:#175aca}.mcp20-actions button:last-child{color:#b91c1c}.mcp20-actions button:disabled{opacity:.4;cursor:not-allowed}.mcp20-selected{border:1px solid #dbeafe;background:#eff6ff;border-radius:8px;padding:10px;margin:12px 0}.mcp20-status{display:inline-block;padding:4px 8px;border-radius:99px;background:#e2e8f0;color:#334155;font-size:11px;font-weight:600}.mcp20-foot{padding:9px 16px;border-top:1px solid var(--b);font-size:11px;color:#64748b;background:#f8fafc}
.mcp20-action-icon{font-size:15px;margin-right:5px}
.mcp20-primary{background:#2563eb;color:white;border:0;border-radius:7px;padding:9px 12px;cursor:pointer;font-weight:600;margin-top:12px}
.mcp20-primary:disabled{opacity:.5;cursor:not-allowed}
.mcp20-secondary{background:white;color:#334155;border:1px solid #cbd5e1;border-radius:7px;padding:7px 12px;cursor:pointer;margin:10px 8px 0 0}
.mcp20-note{background:#eff6ff;padding:10px;border-radius:8px;color:#334155;line-height:1.5;margin-top:10px}
.mcp20-error{color:#b91c1c;padding:8px;background:#fef2f2;border-radius:6px}
.mcp20-field{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.mcp20-field label{font-size:11px;color:#64748b;flex:1;min-width:90px}.mcp20-field input{display:block;width:100%;border:1px solid #cbd5e1;border-radius:6px;padding:7px;color:#0f172a}
.mcp20-editor{box-shadow:0 6px 25px rgba(17,37,70,.08)}
.mcp20-head{padding:16px 22px;background:#fff}.mcp20-head strong{font-size:19px;letter-spacing:-.35px}
.mcp20-grid{grid-template-columns:minmax(0,1fr) 320px;min-height:670px}
.mcp20-main{background:#f9fbfe}.mcp20-main .mcpux-canvas{padding:22px!important;min-height:650px}
.mcp20-main .mcpux-canvas>div:nth-child(2){min-height:555px!important;background:#fff!important;border:1px solid #e0e8f2!important;box-shadow:0 2px 7px #2637500b}
.mcp20-side{padding:22px;background:#fff}.mcp20-side h4{font-size:16px}
.mcp20-actions{width:max-content;max-width:calc(100% - 16px);flex-wrap:nowrap;overflow-x:auto;box-shadow:0 13px 28px #172b4b30;border-radius:10px}
.mcp20-actions button{font-size:12px;padding:9px 10px}.mcp20-actions button:hover{background:#dbeafe}
.mcp20-selected{background:#f2f7ff}.mcp20-note{background:#eff6ff;border:1px solid #d9e8fe}
.mcp20-foot{padding:12px 20px;background:#fafbfd}
.mcp20-nav-business{border:1px solid #bfdbfe!important;border-radius:7px;background:#eff6ff!important;color:#1d4ed8!important;padding:7px 10px!important;cursor:pointer;font-size:12px;font-weight:600;white-space:nowrap}
.mcp20-nav-business:hover{background:#dbeafe!important}
.mcp20-main .mcpux-canvas>div:first-child{gap:6px!important}
.mcp20-main .mcpux-nav-controls{gap:6px!important}
.mcp20-reset-warning{border:1px solid #f59e0b!important;border-radius:7px;background:#fff7ed!important;color:#9a3412!important;padding:7px 10px!important;cursor:pointer;font-size:12px;font-weight:600}
.mcp20-reset-warning:hover{background:#ffedd5!important;border-color:#ea580c!important}
@media(max-width:800px){.mcp20-grid{grid-template-columns:1fr}.mcp20-side{border-left:0;border-top:1px solid var(--b)}.mcp20-actions{position:sticky;top:4px;left:5px!important;margin:5px}}
`;
    function mount(frm, mountAt, opts) {
      if (!opts || opts.enabled !== true)
        return null;
      if (!ns.createWorkspace || !ns.createCanvasRenderer || !ns.createUX04Guide)
        throw new Error("Modules MCP UX-02 \xE0 UX-04 non charg\xE9s");
      const ws = ns.createWorkspace(frm, { enabled: true });
      ws.mount();
      let disposed = false, guide = null, tree = null;
      const section = el("section", null, "mcp20-editor");
      const css = el("style");
      css.textContent = style;
      section.appendChild(css);
      const grid = el("div", null, "mcp20-grid"), main = el("div", null, "mcp20-main"), side = el("aside", null, "mcp20-side"), actions = el("div", null, "mcp20-actions");
      actions.setAttribute("aria-label", "Actions de d\xE9coupe");
      main.appendChild(actions);
      grid.append(main, side);
      section.appendChild(grid);
      const foot = el("div", "Simulation locale \xB7 Aucun incident, Stock Entry ou Serial No ne sera modifi\xE9", "mcp20-foot");
      section.appendChild(foot);
      mountAt.appendChild(section);
      const canvas = ns.createCanvasRenderer(main, (node, sheet) => {
        if (!guide)
          return;
        if (node)
          guide.select(node, sheet);
        else
          guide.cancel();
      });
      const navControls = main.querySelector(".mcpux-nav-controls");
      if (navControls) {
        if (typeof opts.onReset === "function") {
          const reset = el("button", "R\xE9initialiser", "mcp20-reset-warning");
          reset.type = "button";
          reset.title = "Attention : annule toutes les modifications locales de la simulation";
          reset.addEventListener("click", () => opts.onReset());
          navControls.appendChild(reset);
        }
      }
      function parse() {
        const raw = typeof opts.getTree === "function" ? opts.getTree() : frm.doc.mcp_mode === "Retour Terrain" ? frm.doc.effective_result_json || frm.doc.result_json : frm.doc.result_json || frm.doc.effective_result_json;
        const value = typeof raw === "string" ? JSON.parse(raw || "{}") : raw || {};
        if (!Array.isArray(value.nodes))
          throw new Error("R\xE9sultat MCP indisponible");
        return value;
      }
      function line(key, value) {
        const r = el("div", null, "mcp20-line");
        r.append(el("span", key, "mcp20-k"), el("span", value == null ? "\u2014" : String(value)));
        side.appendChild(r);
      }
      function button(text, fn, cls) {
        const b = el("button", text, cls || "mcp20-secondary");
        b.type = "button";
        b.addEventListener("click", fn);
        side.appendChild(b);
        return b;
      }
      function locate() {
        const state = ws.store.getState();
        if (!state.sourceNodeId || !actions.children.length) {
          actions.style.display = "none";
          return;
        }
        const group = [...main.querySelectorAll("svg [data-node-id]")].find((n) => n.getAttribute("data-node-id") === state.sourceNodeId);
        const bounds = main.getBoundingClientRect();
        if (!group || !bounds.width) {
          actions.style.display = "none";
          return;
        }
        const b = group.getBoundingClientRect();
        actions.style.display = "flex";
        const width = actions.offsetWidth || 430;
        const left = Math.max(6, Math.min((b.left + b.right) / 2 - bounds.left - width / 2, Math.max(6, bounds.width - width - 6)));
        const proposed = b.top - bounds.top - actions.offsetHeight - 12;
        const below = b.bottom - bounds.top + 12;
        const top = proposed >= 6 ? proposed : Math.min(below, Math.max(6, bounds.height - actions.offsetHeight - 6));
        actions.style.left = left + "px";
        actions.style.top = top + "px";
      }
      function highlight() {
        const state = ws.store.getState();
        const meta = guide && guide.stateInfo();
        const candidates = new Set(meta ? meta.candidateIds : []), targets = new Set(state.targetNodeIds || []);
        for (const group of main.querySelectorAll("svg [data-node-id]")) {
          const id = group.getAttribute("data-node-id"), rect = group.querySelector("rect");
          if (!rect)
            continue;
          const chosen = id === state.sourceNodeId || targets.has(id), suggested = candidates.has(id);
          rect.setAttribute("stroke", id === state.sourceNodeId ? "#2563eb" : targets.has(id) ? "#16a34a" : suggested ? "#0d9488" : "#94a3b8");
          rect.setAttribute("stroke-width", chosen || suggested ? "9" : "5");
          rect.setAttribute("stroke-dasharray", suggested && !targets.has(id) ? "16 10" : "none");
          group.style.cursor = state.status === "selecting_target" && !suggested ? "not-allowed" : "pointer";
        }
      }
      function render() {
        if (disposed)
          return;
        const s = ws.store.getState();
        canvas.setSelection(s.sourceNodeId);
        actions.replaceChildren();
        side.replaceChildren();
        side.appendChild(el("h4", "Action en cours"));
        const status = el("span", s.busy ? "Enregistrement\u2026" : s.preview ? "Aper\xE7u \xE0 valider" : s.status === "selecting_target" ? "Choisir une cible" : s.sourceNodeId ? "Zone s\xE9lectionn\xE9e" : "En attente", "mcp20-status");
        side.appendChild(status);
        if (s.sourceNodeId) {
          for (const name of ws.controller.actions) {
            if (!ws.controller.canStart(name, s.sourceNodeType))
              continue;
            const b = el("button");
            const sym = el("span", SYMBOL[name] || "\xB7", "mcp20-action-icon");
            b.append(sym, document.createTextNode(LABEL[name] || name));
            b.type = "button";
            b.disabled = s.busy;
            b.dataset.current = String(s.action === name);
            b.addEventListener("click", () => guide.begin(name));
            actions.appendChild(b);
          }
        }
        if (!s.sourceNodeId) {
          side.appendChild(el("div", "1. Cliquez sur une pi\xE8ce ou une chute pour afficher les actions disponibles.", "mcp20-note"));
        } else {
          const selected = el("div", null, "mcp20-selected");
          const src = guide.getItem(s.sourceNodeId);
          const n = src && src.node || {};
          selected.append(el("span", "S\xE9lection actuelle", "mcp20-k"), el("strong", n.label || s.sourceNodeId));
          if (n.length_mm && n.width_mm)
            selected.append(el("div", `${n.length_mm} \xD7 ${n.width_mm} mm`));
          side.appendChild(selected);
          line("Action", LABEL[s.action] || "Choisissez une action sur la plaque");
          if (s.targetNodeIds.length)
            line("Cibles", s.targetNodeIds.map((id) => {
              const entry = guide.getItem(id);
              return entry && entry.node.label || id;
            }).join(", "));
        }
        if (s.status === "selecting_target")
          side.appendChild(el("div", "2. Cliquez sur une cible indiqu\xE9e par un contour turquoise. La compatibilit\xE9 g\xE9om\xE9trique sera contr\xF4l\xE9e avant enregistrement.", "mcp20-note"));
        if (s.action === "Resize" && s.status === "action_active") {
          const info = guide.getItem(s.sourceNodeId), n = info && info.node || {};
          const container = el("div", null, "mcp20-field");
          let inputs = [];
          for (const [label, value] of [["Longueur (mm)", n.effective_length_mm || n.length_mm], ["Largeur (mm)", n.effective_width_mm || n.width_mm]]) {
            const l = el("label", label), input = el("input");
            input.type = "number";
            input.min = "1";
            input.step = "any";
            input.value = String(value || "");
            l.appendChild(input);
            container.appendChild(l);
            inputs.push(input);
          }
          side.appendChild(container);
          button("Pr\xE9visualiser", () => guide.setResize(inputs[0].value, inputs[1].value), "mcp20-primary");
        }
        if (s.action === "Merge" && s.status === "selecting_target" && s.targetNodeIds.length)
          button("Pr\xE9visualiser la fusion", () => guide.buildPreview(), "mcp20-primary");
        if (s.action === "Destroy" && s.status === "action_active")
          button("Pr\xE9visualiser la destruction", () => guide.buildPreview(), "mcp20-primary");
        if (s.preview) {
          side.appendChild(el("div", (LABEL[s.preview.action] || s.preview.action) + " \xB7 " + s.preview.title, "mcp20-note"));
          side.appendChild(el("p", s.preview.detail));
          side.appendChild(el("p", "Simulation graphique locale, non valid\xE9e par Python."));
          const apply = button("Appliquer \xE0 l\u2019aper\xE7u", async () => {
            if (typeof opts.onApply !== "function")
              return;
            apply.disabled = true;
            try {
              await opts.onApply({ preview: s.preview, guide, tree, workspace: ws });
            } catch (e) {
              ws.controller.setError(String(e.message || e));
            } finally {
              apply.disabled = false;
            }
          }, "mcp20-primary");
          apply.disabled = !!s.busy || typeof opts.onApply !== "function";
        }
        if (s.error)
          side.appendChild(el("div", s.error, "mcp20-error"));
        if (s.sourceNodeId)
          button("Annuler la s\xE9lection", () => guide.cancel());
        highlight();
        locate();
      }
      function load() {
        tree = parse();
        canvas.setTree(tree);
        if (guide)
          guide.refresh(tree);
        else
          guide = ns.createUX04Guide(ws.store, ws.controller, tree);
        render();
        return canvas.getSheets().length;
      }
      const onKey = (e) => {
        if (e.key === "Escape" && !disposed && ws.store.getState().sourceNodeId) {
          guide.cancel();
        }
      };
      section.addEventListener("keydown", onKey);
      const unsub = ws.store.subscribe(render);
      const update = () => locate();
      window.addEventListener("resize", update);
      main.addEventListener("scroll", update, true);
      load();
      return { refresh: load, getState: () => ws.store.getState(), destroy() {
        if (disposed)
          return;
        disposed = true;
        unsub();
        window.removeEventListener("resize", update);
        main.removeEventListener("scroll", update, true);
        section.removeEventListener("keydown", onKey);
        canvas.destroy();
        section.remove();
        ws.destroy();
      } };
    }
    ns.mountUX20Editor = mount;
  })(typeof window !== "undefined" ? window : globalThis);
  (function(root) {
    "use strict";
    const ns = root.MatRecoMCPUX20 = root.MatRecoMCPUX20 || {};
    const clone = (v) => JSON.parse(JSON.stringify(v));
    const num = (v) => Number(v) || 0;
    function originalTree(frm) {
      const raw = frm.doc.mcp_mode === "Retour Terrain" ? frm.doc.effective_result_json || frm.doc.result_json : frm.doc.result_json || frm.doc.effective_result_json;
      const value = typeof raw === "string" ? JSON.parse(raw || "{}") : clone(raw || {});
      if (!Array.isArray(value.nodes))
        throw new Error("Aucun plan de d\xE9coupe disponible pour cette simulation.");
      return clone(value);
    }
    function nodeIn(tree, id) {
      for (const sheet of tree.nodes || []) {
        const index = (sheet.children || []).findIndex((n) => String(n.id) === String(id));
        if (index >= 0)
          return { sheet, index, node: sheet.children[index] };
      }
      return null;
    }
    function updateSimulation(tree, preview) {
      var _a, _b;
      const next = clone(tree), src = nodeIn(next, preview.sourceNodeId);
      if (!src)
        throw new Error("La zone s\xE9lectionn\xE9e est introuvable.");
      const action = preview.action, targets = (preview.targetNodeIds || []).map((id) => nodeIn(next, id));
      if (["Single", "Merge", "Move"].includes(action) && targets.some((x) => !x))
        throw new Error("Cible introuvable.");
      if (action === "Destroy") {
        src.node.node_type = "destroyed";
        src.node.effective_length_mm = 0;
        src.node.effective_width_mm = 0;
      } else if (action === "Resize") {
        const l = num((_a = preview.parameters) == null ? void 0 : _a.length_mm), w = num((_b = preview.parameters) == null ? void 0 : _b.width_mm);
        if (l <= 0 || w <= 0 || l > num(src.node.length_mm) || w > num(src.node.width_mm))
          throw new Error("Dimensions de redimensionnement invalides.");
        src.node.effective_length_mm = l;
        src.node.effective_width_mm = w;
        src.node.area_mm2 = l * w;
      } else if (action === "Single") {
        const t = targets[0];
        if (!t || t.sheet !== src.sheet)
          throw new Error("Chute en L : s\xE9lectionnez deux r\xE9gions de la m\xEAme plaque.");
        const a = src.node, b = t.node, x = Math.min(num(a.x), num(b.x)), y = Math.min(num(a.y), num(b.y));
        const right = Math.max(num(a.x) + num(a.length_mm), num(b.x) + num(b.length_mm));
        const bottom = Math.max(num(a.y) + num(a.width_mm), num(b.y) + num(b.width_mm));
        const area = num(a.length_mm) * num(a.width_mm) + num(b.length_mm) * num(b.width_mm);
        const bounds = (right - x) * (bottom - y), removed = bounds - area;
        if (removed <= 0 || num(a.length_mm) * num(a.width_mm) + num(b.length_mm) * num(b.width_mm) > bounds)
          throw new Error("Les deux zones ne d\xE9finissent pas une chute en L.");
        src.sheet.children = src.sheet.children.filter((n) => n !== a && n !== b);
        src.sheet.children.push({ id: String(a.id) + "::UX20L", node_type: "leftover", geometry_type: "single", label: "Chute en L (simulation)", item_code: a.item_code || b.item_code, x, y, length_mm: right - x, width_mm: bottom - y, removed_area_mm2: removed, area_mm2: area, source_serial_no: src.sheet.serial_no, visual_regions: [{ x: num(a.x), y: num(a.y), length_mm: num(a.length_mm), width_mm: num(a.width_mm) }, { x: num(b.x), y: num(b.y), length_mm: num(b.length_mm), width_mm: num(b.width_mm) }], visual_simulation: true });
      } else if (action === "Merge") {
        const t = targets[0];
        if (!t || t.sheet !== src.sheet)
          throw new Error("Fusion : les zones doivent appartenir \xE0 la m\xEAme plaque.");
        const a = src.node, b = t.node, x = Math.min(num(a.x), num(b.x)), y = Math.min(num(a.y), num(b.y));
        const right = Math.max(num(a.x) + num(a.length_mm), num(b.x) + num(b.length_mm));
        const bottom = Math.max(num(a.y) + num(a.width_mm), num(b.y) + num(b.width_mm));
        const area = num(a.length_mm) * num(a.width_mm) + num(b.length_mm) * num(b.width_mm);
        if (Math.abs((right - x) * (bottom - y) - area) > 0.01)
          throw new Error("Fusion rectangulaire impossible dans la simulation.");
        src.sheet.children = src.sheet.children.filter((n) => n !== a && n !== b);
        src.sheet.children.push({ id: String(a.id) + "::UX20M", node_type: "leftover", label: "Chute fusionn\xE9e", x, y, length_mm: right - x, width_mm: bottom - y, area_mm2: area, visual_simulation: true });
      } else if (action === "Move") {
        const t = targets[0];
        if (!t || !["leftover", "waste"].includes(String(t.node.node_type)))
          throw new Error("D\xE9placement : zone cible invalide.");
        if (num(src.node.length_mm) > num(t.node.length_mm) || num(src.node.width_mm) > num(t.node.width_mm))
          throw new Error("La pi\xE8ce ne tient pas dans la cible.");
        const x = num(t.node.x), y = num(t.node.y), oldX = num(src.node.x), oldY = num(src.node.y), oldSheet = src.sheet;
        oldSheet.children.splice(src.index, 1);
        t.sheet.children.push(__spreadProps(__spreadValues({}, src.node), { x, y, id: src.node.id, visual_simulation: true }));
        oldSheet.children.push({ id: String(src.node.id) + "::UX20FREE", node_type: "leftover", label: "Zone lib\xE9r\xE9e (simulation)", x: oldX, y: oldY, length_mm: num(src.node.length_mm), width_mm: num(src.node.width_mm), visual_simulation: true });
        t.node.node_type = "waste";
        t.node.label = "Zone cible (simulation)";
      } else
        throw new Error("Action inconnue : " + action);
      return next;
    }
    function renderReadOnly(frm) {
      var _a, _b;
      const data = frm.__mcp_ux20_visual, field = (_a = frm.fields_dict) == null ? void 0 : _a.cutting_plan_preview;
      if (!data || !((_b = field == null ? void 0 : field.$wrapper) == null ? void 0 : _b.length))
        return false;
      const wrapper = field.$wrapper[0];
      wrapper.replaceChildren();
      const block = document.createElement("div");
      block.className = "mcp20-readonly";
      block.style.cssText = "border:1px solid #dbe4f0;border-radius:10px;background:white;padding:15px;";
      const heading = document.createElement("div");
      heading.textContent = "Aper\xE7u UX 2.0 \xB7 Simulation visuelle (non enregistr\xE9e)";
      heading.style.cssText = "color:#334155;font-weight:600;margin-bottom:12px";
      block.appendChild(heading);
      wrapper.appendChild(block);
      const renderer = ns.createCanvasRenderer(block, null);
      renderer.setTree(data);
      block.querySelectorAll("[data-node-id]").forEach((el) => {
        el.style.pointerEvents = "none";
        el.removeAttribute("tabindex");
        el.removeAttribute("role");
      });
      return true;
    }
    const vueJS = "/assets/mat_reco/js/mcp_vue_dist/mcp_vue.iife.js";
    const vueCSS = "/assets/mat_reco/js/mcp_vue_dist/mat-reco-mcp-ux20-vue.css";
    let vueAssetsPromise = null;
    function loadVueAssets() {
      var _a;
      if (typeof ((_a = root.MatRecoMCPVue) == null ? void 0 : _a.mount) === "function")
        return Promise.resolve();
      if (vueAssetsPromise)
        return vueAssetsPromise;
      vueAssetsPromise = new Promise((resolve, reject) => {
        if (!document.querySelector("link[data-mcp-vue-style]")) {
          const css = document.createElement("link");
          css.rel = "stylesheet";
          css.href = vueCSS;
          css.dataset.mcpVueStyle = "1";
          document.head.appendChild(css);
        }
        const script = document.createElement("script");
        script.src = vueJS + "?ux20_vue=20261013_2";
        script.async = true;
        script.onload = () => {
          var _a2;
          return typeof ((_a2 = root.MatRecoMCPVue) == null ? void 0 : _a2.mount) === "function" ? resolve() : reject(new Error("Le fichier Vue est charg\xE9 mais MatRecoMCPVue.mount est absent. Reconstruire le bundle Vite."));
        };
        script.onerror = () => reject(new Error("Bundle Vue inaccessible : " + vueJS + " (404 ou CSP)."));
        document.head.appendChild(script);
      }).catch((error) => {
        vueAssetsPromise = null;
        throw error;
      });
      return vueAssetsPromise;
    }
    function openModal(frm) {
      var _a, _b;
      console.info("[MCP UX20] Ouverture modal Vue \u2014 build 20261013_2");
      if ((_b = (_a = frm.__mcp_ux20_modal) == null ? void 0 : _a.$wrapper) == null ? void 0 : _b.is(":visible"))
        return frm.__mcp_ux20_modal;
      const state = { base: originalTree(frm), tree: null, vue: null, editor: null, closed: false };
      state.tree = clone(state.base);
      const dlg = new frappe.ui.Dialog({ title: "Material Cutting Plan \xB7 UX 2.0", size: "extra-large", fields: [{ fieldtype: "HTML", fieldname: "ux20_editor" }], primary_action_label: "Appliquer \xE0 cutting plan preview", primary_action() {
        frm.__mcp_ux20_visual = clone(state.tree);
        renderReadOnly(frm);
        frappe.show_alert({ message: "Aper\xE7u visuel actualis\xE9. Aucun changement m\xE9tier enregistr\xE9.", indicator: "blue" });
        dlg.hide();
      } });
      frm.__mcp_ux20_modal = dlg;
      dlg.show();
      const wrapper = dlg.fields_dict.ux20_editor.$wrapper[0];
      const css = document.createElement("style");
      css.textContent = `
 .modal-dialog:has(.mcp20-modal-inner){width:70vw!important;max-width:70vw!important;margin:2vh auto!important}
 .modal:has(.mcp20-modal-inner) .modal-body{padding:0!important;max-height:calc(70vh - 110px)!important;overflow:auto}
 .modal:has(.mcp20-modal-inner) .modal-content{height:70vh!important}
 .mcp20-modal-inner{min-height:300px}
 .mcp20-modal-inner .mcpv-grid{min-height:350px}
 .mcp20-modal-inner .mcpv-canvas svg{height:min(48vh,530px)}
 `;
      wrapper.appendChild(css);
      const host = document.createElement("div");
      host.className = "mcp20-modal-inner";
      wrapper.appendChild(host);
      const message = document.createElement("div");
      message.style.cssText = "padding:24px;color:#64748b";
      message.textContent = "Chargement de Vue 3 + Pinia\u2026";
      host.appendChild(message);
      dlg.$wrapper.on("hidden.bs.modal.mcpUX20", () => {
        var _a2, _b2;
        state.closed = true;
        try {
          (_a2 = state.vue) == null ? void 0 : _a2.unmount();
        } catch (err) {
          console.warn("[MCP Vue] unmount", err);
        }
        try {
          (_b2 = state.editor) == null ? void 0 : _b2.destroy();
        } catch (err) {
          console.warn("[MCP UX legacy] destroy", err);
        }
        state.vue = null;
        state.editor = null;
        frm.__mcp_ux20_modal = null;
        dlg.$wrapper.off("hidden.bs.modal.mcpUX20");
      });
      loadVueAssets().then(() => {
        if (state.closed)
          return;
        host.replaceChildren();
        const vueHost = document.createElement("div");
        vueHost.id = "mcp-ux20-vue-root";
        host.appendChild(vueHost);
        state.vue = root.MatRecoMCPVue.mount(vueHost, {
          tree: clone(state.tree),
          onReset: () => {
            state.tree = clone(state.base);
          },
          onApplyPreview: async (preview) => {
            var _a2, _b2, _c, _d;
            const next = updateSimulation(state.tree, preview);
            state.tree = next;
            if ((_b2 = (_a2 = state.vue) == null ? void 0 : _a2.store) == null ? void 0 : _b2.setWorking)
              state.vue.store.setWorking(clone(next));
            else
              (_d = (_c = state.vue) == null ? void 0 : _c.store) == null ? void 0 : _d.load(clone(next));
            frappe.show_alert({ message: "Simulation locale actualis\xE9e (non enregistr\xE9e).", indicator: "blue" });
          }
        });
        if (!vueHost.hasAttribute("data-v-app"))
          throw new Error("Vue mount() a \xE9t\xE9 appel\xE9 mais aucun composant Vue n\u2019est mont\xE9.");
        const status = document.createElement("span");
        status.textContent = "Vue 3 + Pinia actif";
        status.style.cssText = "position:absolute;top:12px;right:52px;font-size:11px;color:#166534;background:#dcfce7;padding:2px 8px;border-radius:12px;z-index:2;";
        host.style.position = "relative";
        host.appendChild(status);
      }).catch((error) => {
        console.error("[MCP UX 2.0 Vue]", error);
        if (state.closed)
          return;
        host.replaceChildren();
        const warning = document.createElement("div");
        warning.className = "alert alert-warning";
        warning.textContent = "Interface classique (secours) : Vue n\u2019a pas pu d\xE9marrer. " + String(error.message || error);
        host.appendChild(warning);
        const legacy = document.createElement("div");
        host.appendChild(legacy);
        state.editor = ns.mountUX20Editor(frm, legacy, { enabled: true, getTree: () => state.tree, onReset: () => {
          state.tree = clone(state.base);
          state.editor.refresh();
        }, onApply: async ({ preview }) => {
          state.tree = updateSimulation(state.tree, preview);
          state.editor.refresh();
        } });
      });
      return dlg;
    }
    ns.openUX20Modal = openModal;
    ns.renderUX20ReadOnly = renderReadOnly;
    ns.simulateUX20Operation = updateSimulation;
  })(typeof window !== "undefined" ? window : globalThis);
})();
//# sourceMappingURL=mcp_ux20.bundle.KRKEMVEB.js.map
