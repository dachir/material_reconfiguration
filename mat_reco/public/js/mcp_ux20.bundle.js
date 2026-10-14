/* MCP UX 2.0 — bundle final, source modules below. */
/* MCP UX 2.0 / UX-02. No mutation of Frappe documents. */
(function (root) {
    'use strict';
    const namespace = root.MatRecoMCPUX20 = root.MatRecoMCPUX20 || {};
    const INITIAL = Object.freeze({
        status: 'idle', action: null, selectedSheet: null,
        sourceNodeId: null, targetNodeIds: [], preview: null,
        busy: false, error: null
    });
    function copy(value) {
        if (Array.isArray(value)) return value.map(copy);
        if (value && typeof value === 'object') {
            const object = {};
            Object.keys(value).forEach(key => { object[key] = copy(value[key]); });
            return object;
        }
        return value;
    }
    function createStore(initial) {
        let state = copy(Object.assign({}, INITIAL, initial || {}));
        const subscribers = new Set();
        let destroyed = false;
        return {
            getState: function () { return copy(state); },
            subscribe: function (listener) {
                if (destroyed) throw new Error('MCP UX state store destroyed');
                if (typeof listener !== 'function') throw new TypeError('Expected listener');
                subscribers.add(listener);
                return () => subscribers.delete(listener);
            },
            update: function (changes) {
                if (destroyed) throw new Error('MCP UX state store destroyed');
                const next = typeof changes === 'function' ? changes(copy(state)) : changes;
                if (!next || typeof next !== 'object' || Array.isArray(next)) throw new TypeError('Expected state changes');
                state = Object.assign({}, state, copy(next));
                const snapshot = copy(state);
                subscribers.forEach(listener => listener(copy(snapshot)));
                return snapshot;
            },
            reset: function () { return this.update(copy(INITIAL)); },
            destroy: function () { subscribers.clear(); destroyed = true; }
        };
    }
    namespace.createStateStore = createStore;
    namespace.initialState = copy(INITIAL);
})(typeof window !== 'undefined' ? window : globalThis);

/* MCP UX 2.0 / UX-02. Interaction state only; no incidents or Python calls. */
(function (root) {
    'use strict';
    const namespace = root.MatRecoMCPUX20 = root.MatRecoMCPUX20 || {};
    const ACTIONS = Object.freeze(['Resize', 'Destroy', 'Move', 'Merge', 'Single']);
    const TYPES = Object.freeze({
        Resize: ['finished_good', 'leftover', 'waste'],
        Destroy: ['finished_good', 'leftover', 'waste'],
        Move: ['finished_good'],
        Merge: ['leftover', 'waste'],
        Single: ['leftover', 'waste']
    });
    function createController(store, options) {
        if (!store || typeof store.update !== 'function') throw new TypeError('State store required');
        const allowed = options && options.canApplyAction;
        function permitted(action, type) {
            return ACTIONS.includes(action) && TYPES[action].includes(type) &&
                (!allowed || Boolean(allowed(action, type)));
        }
        function select(node, sheet) {
            const state = store.getState();
            if (state.busy) return false;
            if (!node || !node.id) return false;
            if (state.status === 'selecting_target') return this.addTarget(node);
            store.update({ status: 'selected', action: null, sourceNodeId: String(node.id),
                sourceNodeType: String(node.node_type || ''), selectedSheet: sheet || state.selectedSheet,
                targetNodeIds: [], preview: null, error: null });
            return true;
        }
        function begin(action) {
            const state = store.getState();
            if (state.busy || !state.sourceNodeId || !permitted(action, state.sourceNodeType)) return false;
            store.update({ action, status: ['Move', 'Merge', 'Single'].includes(action)
                ? 'selecting_target' : 'action_active', targetNodeIds: [], preview: null, error: null });
            return true;
        }
        function addTarget(node) {
            const state = store.getState();
            if (state.status !== 'selecting_target' || state.busy || !node || !node.id ||
                String(node.id) === state.sourceNodeId || state.targetNodeIds.includes(String(node.id))) return false;
            store.update({ targetNodeIds: state.targetNodeIds.concat(String(node.id)), error: null });
            return true;
        }
        function showPreview(preview) {
            const state = store.getState();
            if (!state.action || state.busy) return false;
            store.update({ status: 'preview', preview, error: null });
            return true;
        }
        function cancel() {
            if (store.getState().busy) return false;
            store.update({ status: 'idle', action: null, sourceNodeId: null,
                sourceNodeType: null, targetNodeIds: [], preview: null, error: null });
            return true;
        }
        function setError(error) {
            store.update({ status: 'error', busy: false, error: String(error || 'Unknown error') });
        }
        function setBusy(busy) { store.update({ busy: Boolean(busy) }); }
        return { select, begin, addTarget, showPreview, cancel, setError, setBusy,
            canStart: permitted, actions: ACTIONS.slice() };
    }
    namespace.createInteractionController = createController;
})(typeof window !== 'undefined' ? window : globalThis);

/* MCP UX 2.0 / UX-02. Disabled unless explicitly opted in. */
(function (root) {
    'use strict';
    const namespace = root.MatRecoMCPUX20 = root.MatRecoMCPUX20 || {};
    const instances = new WeakMap();
    function createWorkspace(frm, options) {
        options = options || {};
        if (!frm || (typeof frm !== 'object' && typeof frm !== 'function')) throw new TypeError('Frappe form required');
        if (instances.has(frm)) return instances.get(frm);
        if (!namespace.createStateStore || !namespace.createInteractionController) {
            throw new Error('Load mcp_state_store.js and mcp_interaction_controller.js first');
        }
        const store = namespace.createStateStore();
        const controller = namespace.createInteractionController(store, options);
        let active = false;
        let destroyed = false;
        const workspace = {
            store, controller,
            mount() {
                if (destroyed) throw new Error('Workspace destroyed');
                // UX-02 is strictly headless: no DOM listeners, no Frappe mutations.
                if (options.enabled !== true) return false;
                active = true;
                return true;
            },
            isMounted() { return active; },
            unmount() { active = false; controller.cancel(); },
            destroy() {
                if (destroyed) return;
                this.unmount(); store.destroy(); instances.delete(frm); destroyed = true;
            }
        };
        instances.set(frm, workspace);
        return workspace;
    }
    namespace.createWorkspace = createWorkspace;
})(typeof window !== 'undefined' ? window : globalThis);

/* MCP UX-03: read-only SVG rendering. No ERPNext mutation. */
(function(root){
'use strict';
const ns=root.MatRecoMCPUX20=root.MatRecoMCPUX20||{};
const SVG='http://www.w3.org/2000/svg';
function el(tag,attrs,text){const e=document.createElementNS(SVG,tag);Object.keys(attrs||{}).forEach(k=>e.setAttribute(k,String(attrs[k])));if(text!=null)e.textContent=String(text);return e;}
function numValue(v){return Number(v)||0;}
function valid(n){return n&&Number(n.length_mm)>0&&Number(n.width_mm)>0;}
function sheetNodes(tree){return (tree&&Array.isArray(tree.nodes)?tree.nodes:[]).filter(n=>n&&n.node_type==='input_serial'&&valid(n));}
function children(sheet){return (Array.isArray(sheet.children)?sheet.children:[]).filter(n=>valid(n)&&n.node_type!=='input_serial'&&!n.is_preexisting_cutout&&!n.is_single_cutout&&!(n.node_type==='destroyed'&&n.single_logical_cutout));}
function color(type){return type==='finished_good'?'#dbeafe':type==='leftover'?'#e2e8f0':type==='waste'?'#fee2e2':'#f1f5f9';}
function createCanvas(container,onSelect){if(!container||!container.appendChild)throw new TypeError('Container required');let current=[],selectedSheet=0,selectedId=null;
const host=document.createElement('div');host.className='mcpux-canvas';host.style.cssText='min-width:0;flex:1;overflow:auto;padding:14px 18px 22px;background:#fff;box-sizing:border-box;';
const nav=document.createElement('div');nav.style.cssText='display:flex;gap:10px;align-items:center;justify-content:space-between;margin-bottom:14px;flex-wrap:wrap';const prev=document.createElement('button'),next=document.createElement('button'),caption=document.createElement('span');prev.type=next.type='button';prev.textContent='‹ Précédente';next.textContent='Suivante ›';const navControls=document.createElement('div');navControls.style.cssText='display:flex;align-items:center;gap:8px;flex-wrap:wrap';const selector=document.createElement('select');selector.setAttribute('aria-label','Choisir une plaque');selector.style.cssText='max-width:240px;min-width:110px;padding:7px 10px;border:1px solid #cbd5e1;border-radius:7px;background:#fff;color:#334155;font-size:12px';for(const b of [prev,next])b.style.cssText='border:1px solid #cbd5e1;border-radius:7px;background:#fff;color:#334155;padding:7px 10px;cursor:pointer;font-size:12px';caption.style.cssText='color:#475569;font-size:12px;font-weight:500;overflow-wrap:anywhere';navControls.classList.add('mcpux-nav-controls');navControls.append(prev,selector,next);nav.append(caption,navControls);host.appendChild(nav);
const drawing=document.createElement('div');drawing.style.cssText='min-height:340px;display:flex;align-items:center;justify-content:center;border:1px solid #e2e8f0;border-radius:9px;background:#f8fafc;padding:16px;box-sizing:border-box;overflow:hidden';host.appendChild(drawing);container.appendChild(host);
function redraw(){drawing.replaceChildren();if(!current.length){drawing.textContent='Aucune plaque à prévisualiser';caption.textContent='0 / 0';prev.disabled=next.disabled=true;selector.replaceChildren();return;}
selectedSheet=Math.max(0,Math.min(selectedSheet,current.length-1));const s=current[selectedSheet];caption.textContent=`Plaque ${selectedSheet+1}/${current.length} · ${s.serial_no||s.id||''} · ${s.length_mm} × ${s.width_mm} mm`;prev.disabled=selectedSheet===0;next.disabled=selectedSheet===current.length-1;selector.value=String(selectedSheet);
const w=Number(s.length_mm),h=Number(s.width_mm);const svg=el('svg',{viewBox:`0 0 ${w} ${h}`,role:'img','aria-label':`Plan de découpe ${s.serial_no||s.id}`,style:'width:100%;max-height:600px;display:block;overflow:visible'});
const defs=el('defs');const pattern=el('pattern',{id:'mcpux-hatch',patternUnits:'userSpaceOnUse',width:16,height:16,patternTransform:'rotate(45)'});pattern.appendChild(el('rect',{width:16,height:16,fill:'#f3f5f8'}));pattern.appendChild(el('line',{x1:0,y1:0,x2:0,y2:16,stroke:'#d4dbe6','stroke-width':5}));defs.appendChild(pattern);svg.appendChild(defs);
svg.append(el('rect',{x:0,y:0,width:w,height:h,fill:'#f8fbff',stroke:'#627a96','stroke-width':Math.max(w,h)*.002}));
for(const n of children(s)){const x=Number(n.x)||0,y=Number(n.y)||0,nw=Number(n.effective_length_mm)||Number(n.length_mm),nh=Number(n.effective_width_mm)||Number(n.width_mm);const group=el('g',{'data-node-id':n.id||'','data-node-type':n.node_type||'',tabindex:0,role:'button','aria-label':`${n.node_type} ${n.label||n.id}`,style:'cursor:pointer;outline:none'});
const r=el('rect',{x,y,width:nw,height:nh,fill:n.node_type==='leftover'?'url(#mcpux-hatch)':color(n.node_type),stroke:n.id===selectedId?'#2563eb':'#94a3b8','stroke-width':Math.max(w,h)*(n.id===selectedId?.006:.002)});if(Array.isArray(n.visual_regions)&&n.visual_regions.length){for(const region of n.visual_regions){group.appendChild(el('rect',{x:numValue(region.x),y:numValue(region.y),width:numValue(region.length_mm),height:numValue(region.width_mm),fill:color('leftover'),stroke:'#94a3b8','stroke-width':Math.max(w,h)*.002}));}}else group.appendChild(r);if(!n.visual_regions&&nw>140&&nh>70){group.appendChild(el('text',{x:x+nw/2,y:y+nh/2-18,'text-anchor':'middle','dominant-baseline':'middle','font-size':Math.min(48,Math.max(19,Math.min(nw/12,nh/5))),fill:'#23446b','pointer-events':'none','font-weight':'600'},n.node_type==='leftover'?'Chute':n.label||n.id||n.node_type));group.appendChild(el('text',{x:x+nw/2,y:y+nh/2+38,'text-anchor':'middle','dominant-baseline':'middle','font-size':Math.min(35,Math.max(16,Math.min(nw/17,nh/7))),fill:'#64748b','pointer-events':'none'},`${nw} × ${nh} mm`));}
// The historical/single cutout is not painted; rendering never mutates geometry.
group.addEventListener('click',()=>{if(typeof onSelect==='function')onSelect(n,s);});group.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();if(onSelect)onSelect(n,s);}});svg.appendChild(group);}
drawing.appendChild(svg);}
function changeSheet(index){selectedSheet=index;selectedId=null;redraw();if(typeof onSelect==='function')onSelect(null,current[selectedSheet]);}prev.addEventListener('click',()=>changeSheet(selectedSheet-1));next.addEventListener('click',()=>changeSheet(selectedSheet+1));selector.addEventListener('change',()=>changeSheet(Number(selector.value)));
return {setTree(tree){const oldSerial=current[selectedSheet]&&(current[selectedSheet].serial_no||current[selectedSheet].id);current=sheetNodes(tree);const keep=current.findIndex(x=>(x.serial_no||x.id)===oldSerial);selectedSheet=keep>=0?keep:0;selectedId=null;selector.replaceChildren();current.forEach((sheet,index)=>{const option=document.createElement('option');option.value=String(index);option.textContent=`Plaque ${index+1} · ${sheet.serial_no||sheet.id}`;selector.appendChild(option);});redraw();},setSelection(id){if(selectedId===id)return;selectedId=id;
// Avoid full SVG replacement on selection: preserve focus and popup anchor.
for(const g of drawing.querySelectorAll('svg [data-node-id]')){const active=g.getAttribute('data-node-id')===String(id||'');const rect=g.querySelector('rect');if(!rect)continue;rect.setAttribute('stroke',active?'#2563eb':'#94a3b8');rect.setAttribute('stroke-width',Math.max(1,Number(current[selectedSheet]?.length_mm||1000))*(active?.006:.002));}},getSheets(){return current.slice();},destroy(){host.remove();},redraw};}
ns.createCanvasRenderer=createCanvas;ns.getUX03Sheets=sheetNodes;
})(typeof window!=='undefined'?window:globalThis);

/* MCP UX-03: non-committing contextual toolbar. */
(function(root){'use strict';const ns=root.MatRecoMCPUX20=root.MatRecoMCPUX20||{};
function createToolbar(host,controller,store){const bar=document.createElement('div');bar.style.cssText='display:none;flex-wrap:wrap;gap:6px;padding:10px;border:1px solid #e2e8f0;border-radius:10px;background:white;box-shadow:0 2px 8px #0001';bar.setAttribute('aria-label','Actions de découpe');host.appendChild(bar);
const unsub=store.subscribe(render);function render(state){bar.replaceChildren();bar.style.display=state.sourceNodeId?'flex':'none';if(!state.sourceNodeId)return;for(const action of controller.actions){if(!controller.canStart(action,state.sourceNodeType))continue;const btn=document.createElement('button');btn.type='button';btn.textContent=action;btn.disabled=state.busy;btn.style.cssText='padding:6px 10px;border:1px solid #cbd5e1;border-radius:6px;background:'+(state.action===action?'#dbeafe':'white')+';cursor:pointer';btn.addEventListener('click',()=>controller.begin(action));bar.appendChild(btn);}}
render(store.getState());return {destroy(){unsub();bar.remove();}};}
ns.createContextToolbar=createToolbar;
})(typeof window!=='undefined'?window:globalThis);

/* MCP UX-03: display-only interaction guidance. */
(function(root){'use strict';const ns=root.MatRecoMCPUX20=root.MatRecoMCPUX20||{};
function createPanel(host,store,controller){const panel=document.createElement('aside');panel.style.cssText='min-width:225px;max-width:275px;flex:0 0 245px;padding:15px;background:#f8fafc;border-left:1px solid #e2e8f0;overflow-wrap:anywhere';host.appendChild(panel);
const unsub=store.subscribe(render);function render(s){panel.replaceChildren();const title=document.createElement('strong');title.textContent='Action en cours';panel.appendChild(title);const data=[['État',s.status],['Source',s.sourceNodeId||'—'],['Action',s.action||'—'],['Cibles',(s.targetNodeIds||[]).join(', ')||'—']];for(const [label,val] of data){const p=document.createElement('p');p.style.cssText='font-size:12px;margin:12px 0';const b=document.createElement('b');b.textContent=label+' : ';p.append(b,document.createTextNode(val));panel.appendChild(p);}const hint=document.createElement('p');hint.style.cssText='font-size:12px;color:#64748b';hint.textContent=s.status==='selecting_target'?'Cliquez sur une autre zone. La validation métier reste désactivée dans UX-03.':'Sélectionnez une zone et choisissez une action. UX-03 est une prévisualisation sans sauvegarde.';panel.appendChild(hint);if(s.error){const e=document.createElement('p');e.textContent=s.error;panel.appendChild(e);}const cancel=document.createElement('button');cancel.type='button';cancel.textContent='Annuler la sélection';cancel.addEventListener('click',()=>controller.cancel());panel.appendChild(cancel);}
render(store.getState());return {destroy(){unsub();panel.remove();}};}
ns.createContextPanel=createPanel;
})(typeof window!=='undefined'?window:globalThis);

/* MCP UX-04 — advisory candidates and immutable intention previews; no ERPNext writes. */
(function(root){'use strict';
const ns=root.MatRecoMCPUX20=root.MatRecoMCPUX20||{};
const num=v=>Number(v)||0;
const TARGET_ACTIONS=new Set(['Move','Merge','Single']);
const normalType=n=>String(n&&n.node_type||'').toLowerCase();
function validPiece(n){return n&&n.id&&!n.is_preexisting_cutout&&!n.is_single_cutout&&!n.single_logical_cutout&&num(n.effective_length_mm||n.length_mm)>0&&num(n.effective_width_mm||n.width_mm)>0;}
function candidate(source,target,action,sourceSheet,targetSheet){
 if(!validPiece(source)||!validPiece(target)||String(source.id)===String(target.id))return false;
 if(action==='Move')return normalType(source)==='finished_good'&&['leftover','waste'].includes(normalType(target));
 if(action==='Merge'||action==='Single')return ['leftover','waste'].includes(normalType(source))&&['leftover','waste'].includes(normalType(target))&&String(sourceSheet)===String(targetSheet);
 return false;
}
function indexTree(tree){const sheets=(tree&&Array.isArray(tree.nodes)?tree.nodes:[]).filter(s=>s&&s.node_type==='input_serial');const byId=new Map();for(const sheet of sheets){const key=String(sheet.serial_no||sheet.id);for(const child of sheet.children||[])if(child&&child.id)byId.set(String(child.id),{node:child,sheet:key});}return {sheets,byId};}
function description(action,source,targets,parameters){const t=targets||[];const p=parameters||{};if(action==='Resize')return {title:'Redimensionnement à vérifier',detail:`${num(p.length_mm)} × ${num(p.width_mm)} mm demandés. Aucune géométrie n’est encore recalculée.`,ready:num(p.length_mm)>0&&num(p.width_mm)>0&&num(p.length_mm)<=num(source&&source.effective_length_mm||source&&source.length_mm)&&num(p.width_mm)<=num(source&&source.effective_width_mm||source&&source.width_mm)};
if(action==='Destroy')return {title:'Destruction envisagée',detail:'La pièce sélectionnée sera proposée pour destruction après validation métier.',ready:!!source};
if(action==='Single')return {title:'Single envisagé',detail:'Deux zones résiduelles candidates. L’encoche, la surface et les collisions seront vérifiées côté Python.',ready:t.length===1};
if(action==='Merge')return {title:'Fusion envisagée',detail:'Zones résiduelles candidates. Adjacence et géométrie non validées à ce stade.',ready:t.length>=1};
if(action==='Move')return {title:'Déplacement envisagé',detail:'Zone réceptrice candidate. Placement précis, swap/swing et chevauchements non validés.',ready:t.length===1};
return {title:'Sélection',detail:'Choisissez une action.',ready:false};}
function createGuide(store,controller,tree){let index=indexTree(tree);let params={};function item(id){return index.byId.get(String(id))||null;}
 function candidates(){const s=store.getState();const source=item(s.sourceNodeId);if(!source||!TARGET_ACTIONS.has(s.action))return [];
 return [...index.byId.entries()].filter(([id,target])=>candidate(source.node,target.node,s.action,source.sheet,target.sheet)).map(([id])=>id);}
 function select(node,sheet){const s=store.getState();if(s.status==='preview')return false;if(s.status==='selecting_target'){
 const source=item(s.sourceNodeId);const target=item(node&&node.id);if(!source||!target||!candidate(source.node,target.node,s.action,source.sheet,target.sheet)){store.update({error:'Zone non candidate pour cette action.'});return false;}
 if(s.action==='Move'||s.action==='Single'){if(s.targetNodeIds.length)return false;controller.addTarget(node);return buildPreview();}
 return controller.addTarget(node);
 }return controller.select(node,sheet&& (sheet.serial_no||sheet.id)||null);}
 function begin(action){params={};return controller.begin(action);}
 function setResize(length,width){params={length_mm:num(length),width_mm:num(width)};return buildPreview();}
 function buildPreview(){const s=store.getState();if(!s.action)return false;const source=item(s.sourceNodeId);const targets=s.targetNodeIds.map(item).filter(Boolean).map(x=>x.node);const result=description(s.action,source&&source.node,targets,params);if(!result.ready){store.update({error:'Paramètres ou cibles insuffisants pour l’aperçu.'});return false;}
 return controller.showPreview({kind:'intention_only',action:s.action,sourceNodeId:s.sourceNodeId,targetNodeIds:s.targetNodeIds.slice(),parameters:Object.assign({},params),title:result.title,detail:result.detail,verifiedByServer:false,committed:false});}
 function cancel(){params={};return controller.cancel();}
 function refresh(treeNext){index=indexTree(treeNext);params={};controller.cancel();}
 function stateInfo(){const s=store.getState();const source=item(s.sourceNodeId);const targets=s.targetNodeIds.map(item).filter(Boolean).map(x=>x.node);return {candidateIds:candidates(),preview:s.preview,parameters:Object.assign({},params),description:description(s.action,source&&source.node,targets,params)};}
 return {select,begin,setResize,buildPreview,cancel,refresh,stateInfo,candidateIds:candidates,getItem:item};}
ns.createUX04Guide=createGuide;ns.ux04Candidate=candidate;ns.ux04Description=description;ns.ux04IndexTree=indexTree;
})(typeof window!=='undefined'?window:globalThis);

/* MCP UX-04 opt-in pilot, isolated DOM, zero form mutation and zero Frappe calls. */
(function(root){'use strict';const ns=root.MatRecoMCPUX20=root.MatRecoMCPUX20||{};
function element(tag,text){const x=document.createElement(tag);if(text!=null)x.textContent=text;return x;}
function mount(frm,mountAt,options){if(!options||options.enabled!==true)return null;if(!frm||!frm.doc||!mountAt||!ns.createWorkspace||!ns.createCanvasRenderer||!ns.createUX04Guide)throw new Error('UX-02, UX-03 canvas, and UX-04 interactions must be loaded.');
const ws=ns.createWorkspace(frm,{enabled:true});ws.mount();const section=element('section');section.setAttribute('data-mcp-ux04','true');section.style.cssText='margin:12px 0;border:1px solid #cbd5e1;border-radius:10px;overflow:hidden;background:white';const title=element('header','MCP UX 2.0 — UX-04 · Prévisualisation uniquement (aucune modification enregistrée)');title.style.cssText='padding:12px;background:#eef2ff;font-weight:600';section.appendChild(title);const toolbar=element('div');toolbar.style.cssText='display:flex;flex-wrap:wrap;gap:7px;padding:10px';section.appendChild(toolbar);const body=element('div');body.style.cssText='display:flex;min-height:360px;overflow:auto';section.appendChild(body);const aside=element('aside');aside.style.cssText='width:260px;flex:0 0 260px;border-left:1px solid #e2e8f0;padding:12px;font-size:13px';body.appendChild(aside);mountAt.appendChild(section);
let guide=null,disposed=false,tree=null;
const canvasHost=element('div');canvasHost.style.cssText='flex:1;min-width:0';body.insertBefore(canvasHost,aside);
const canvas=ns.createCanvasRenderer(canvasHost,(node,sheet)=>{if(!guide)return;if(node)guide.select(node,sheet);else guide.cancel();});
function readTree(){const raw=frm.doc.mcp_mode==='Retour Terrain'?(frm.doc.effective_result_json||frm.doc.result_json):(frm.doc.result_json||frm.doc.effective_result_json);const doc=typeof raw==='string'?JSON.parse(raw||'{}'):raw||{};if(!Array.isArray(doc.nodes))throw new Error('MCP JSON: nodes manquant');return doc;}
function highlight(){const state=ws.store.getState(),meta=guide&&guide.stateInfo();const svg=section.querySelector('svg');if(!svg)return;const candidates=new Set(meta?meta.candidateIds:[]);const chosen=new Set(state.targetNodeIds||[]);for(const group of svg.querySelectorAll('[data-node-id]')){const id=group.getAttribute('data-node-id');const rect=group.querySelector('rect');if(!rect)continue;rect.setAttribute('stroke',id===state.sourceNodeId?'#2563eb':chosen.has(id)?'#16a34a':candidates.has(id)?'#0d9488':'#94a3b8');if(id===state.sourceNodeId||chosen.has(id)||candidates.has(id))rect.setAttribute('stroke-width','9');rect.setAttribute('stroke-dasharray',candidates.has(id)&&!chosen.has(id)?'18 12':'none');group.style.cursor=candidates.has(id)||state.status!=='selecting_target'?'pointer':'not-allowed';}}
function render(){const s=ws.store.getState(),meta=guide&&guide.stateInfo();canvas.setSelection(s.sourceNodeId);toolbar.replaceChildren();aside.replaceChildren();
if(s.sourceNodeId){for(const action of ws.controller.actions){if(!ws.controller.canStart(action,s.sourceNodeType))continue;const b=element('button',action);b.type='button';b.disabled=s.busy;b.style.cssText='padding:6px 10px;border:1px solid #cbd5e1;border-radius:6px;background:'+(s.action===action?'#dbeafe':'white');b.addEventListener('click',()=>guide.begin(action));toolbar.appendChild(b);}}
const title2=element('strong','Action en cours');title2.style.cssText='display:block;font-size:15px;color:#0f172a;padding-bottom:10px;border-bottom:1px solid #e2e8f0';aside.appendChild(title2);function text(t){const p=element('p',t);p.style.cssText='margin:9px 0';aside.appendChild(p);}text('État : '+s.status);text('Source : '+(s.sourceNodeId||'—'));text('Action : '+(s.action||'—'));text('Cibles : '+(s.targetNodeIds.length?s.targetNodeIds.join(', '):'—'));
if(s.status==='selecting_target')text('Cibles candidates en turquoise. Compatibilité géométrique NON validée.');
if(s.action==='Resize'&&s.status!=='preview'){const info=guide.getItem(s.sourceNodeId);const dims=info&&info.node||{};const l=element('input'),w=element('input');for(const [x,value,label] of [[l,dims.effective_length_mm||dims.length_mm,'Longueur (mm)'],[w,dims.effective_width_mm||dims.width_mm,'Largeur (mm)']]){x.type='number';x.min='1';x.step='any';x.value=String(value||'');x.setAttribute('aria-label',label);x.style.cssText='max-width:105px;margin:5px';text(label);aside.appendChild(x);}const p=element('button','Prévisualiser Resize');p.type='button';p.addEventListener('click',()=>guide.setResize(l.value,w.value));aside.appendChild(p);}
if(['Merge'].includes(s.action)&&s.status==='selecting_target'&&s.targetNodeIds.length){const b=element('button','Prévisualiser Merge');b.type='button';b.addEventListener('click',()=>guide.buildPreview());aside.appendChild(b);}
if(s.action==='Destroy'&&s.status==='action_active'){const b=element('button','Prévisualiser Destroy');b.type='button';b.addEventListener('click',()=>guide.buildPreview());aside.appendChild(b);}
if(s.preview){text(s.preview.title);text(s.preview.detail);text('Aperçu indicatif uniquement : aucune validation serveur, aucune application métier.');const tag=element('strong','NON ENREGISTRÉ');tag.style.color='#a16207';aside.appendChild(tag);}
if(s.error)text('Erreur : '+s.error);const cancel=element('button','Annuler');cancel.type='button';cancel.style.cssText='display:block;margin-top:15px';cancel.addEventListener('click',()=>guide.cancel());aside.appendChild(cancel);
// DOM paint is complete synchronously. Candidates are advisory only.
highlight();}
let unsub=null;function load(){const next=readTree();tree=next;canvas.setTree(tree);if(guide)guide.refresh(tree);else guide=ns.createUX04Guide(ws.store,ws.controller,tree);render();return canvas.getSheets().length;}
load();unsub=ws.store.subscribe(render);const reposition=()=>locateToolbar();window.addEventListener('resize',reposition);canvasHost.addEventListener('scroll',reposition,true);
return {refresh:load,getState:()=>ws.store.getState(),destroy(){if(disposed)return;disposed=true;if(unsub)unsub();window.removeEventListener('resize',reposition);canvasHost.removeEventListener('scroll',reposition,true);canvas.destroy();section.remove();ws.destroy();}};
}
ns.mountUX04Preview=mount;
})(typeof window!=='undefined'?window:globalThis);

/* UX-05: deterministic incident payloads, no Frappe calls, no mutations. */
(function(root){'use strict';
const ns=root.MatRecoMCPUX20=root.MatRecoMCPUX20||{};
const N=v=>Number(v)||0, EPS=1e-6;
const typ=n=>String(n&&n.node_type||'').toLowerCase();
const free=n=>['leftover','waste'].includes(typ(n))&&!n.is_preexisting_cutout&&!n.is_single_cutout&&!n.single_logical_cutout;
const rect=n=>({x:N(n.x),y:N(n.y),length_mm:N(n.effective_length_mm??n.length_mm),width_mm:N(n.effective_width_mm??n.width_mm),node_type:typ(n)});
const area=r=>r.length_mm*r.width_mm;
function overlap(a,b){return Math.min(a.x+a.length_mm,b.x+b.length_mm)-Math.max(a.x,b.x)>EPS&&Math.min(a.y+a.width_mm,b.y+b.width_mm)-Math.max(a.y,b.y)>EPS;}
function ensure(p,message){if(!p)throw new Error(message);}
function geometry(nodes,action,serial){ensure(nodes.length>1,action+' requires at least two regions');ensure(nodes.every(free),'Only available leftover/waste regions can be selected');ensure(nodes.some(n=>typ(n)==='leftover'),'At least one leftover is required');ensure(nodes.every(n=>String(n.source_serial_no||n.serial_no||serial)===String(serial)),'Regions must belong to one input Serial No');ensure(new Set(nodes.map(n=>String(n.id))).size===nodes.length,'Duplicate regions');const rs=nodes.map(rect);ensure(rs.every(r=>r.length_mm>0&&r.width_mm>0),'Invalid region dimensions');for(let i=0;i<rs.length;i++)for(let j=i+1;j<rs.length;j++)ensure(!overlap(rs[i],rs[j]),'Regions overlap');return rs;}
function bounds(rs){let x=Math.min(...rs.map(r=>r.x)),y=Math.min(...rs.map(r=>r.y));let X=Math.max(...rs.map(r=>r.x+r.length_mm)),Y=Math.max(...rs.map(r=>r.y+r.width_mm));return {x,y,length_mm:X-x,width_mm:Y-y};}
function grid(rs){const b=bounds(rs),xs=[...new Set(rs.flatMap(r=>[r.x,r.x+r.length_mm]))].sort((a,b)=>a-b),ys=[...new Set(rs.flatMap(r=>[r.y,r.y+r.width_mm]))].sort((a,b)=>a-b);const occupied=[];for(let j=0;j<ys.length-1;j++){const row=[];for(let i=0;i<xs.length-1;i++){const cx=(xs[i]+xs[i+1])/2,cy=(ys[j]+ys[j+1])/2;row.push(rs.some(r=>cx>=r.x-EPS&&cx<r.x+r.length_mm-EPS&&cy>=r.y-EPS&&cy<r.y+r.width_mm-EPS));}occupied.push(row);}return {b,xs,ys,occupied};}
function single(rs){ensure(rs.length===2,'Single needs exactly two regions');const b=bounds(rs),s=rs.reduce((v,r)=>v+area(r),0),missing=area(b)-s;ensure(missing>EPS,'Single needs a corner notch; use Merge for rectangles');const g=grid(rs);for(const hx of g.xs.slice(1,-1))for(const hy of g.ys.slice(1,-1)){const hole={x:b.x,y:b.y,length_mm:hx-b.x,width_mm:hy-b.y};if(Math.abs(area(hole)-missing)>EPS||rs.some(r=>overlap(r,hole)))continue;return {...b,removed_length_mm:hole.length_mm,removed_width_mm:hole.width_mm,area_mm2:s};}throw new Error('Single requires one missing upper-left corner');}
function merge(rs){const g=grid(rs);let best=null;for(let y=0;y<g.ys.length-1;y++)for(let x=0;x<g.xs.length-1;x++){if(!g.occupied[y][x])continue;for(let Y=y+1;Y<g.ys.length;Y++)for(let X=x+1;X<g.xs.length;X++){let ok=true;for(let j=y;j<Y&&ok;j++)for(let i=x;i<X;i++)if(!g.occupied[j][i]){ok=false;break;}if(!ok)continue;const r={x:g.xs[x],y:g.ys[y],length_mm:g.xs[X]-g.xs[x],width_mm:g.ys[Y]-g.ys[y]};if(!best||area(r)>area(best)+EPS)best=r;}}
ensure(best,'No mergeable region');const residuals=[];const taken=g.occupied.map((row,j)=>row.map((v,i)=>v&&g.xs[i]>=best.x-EPS&&g.xs[i+1]<=best.x+best.length_mm+EPS&&g.ys[j]>=best.y-EPS&&g.ys[j+1]<=best.y+best.width_mm+EPS));for(let j=0;j<g.ys.length-1;j++)for(let i=0;i<g.xs.length-1;i++){if(!g.occupied[j][i]||taken[j][i])continue;let end=i+1;while(end<g.xs.length-1&&g.occupied[j][end]&&!taken[j][end])end++;let bottom=j+1,can=true;while(bottom<g.ys.length-1&&can){for(let k=i;k<end;k++)if(!g.occupied[bottom][k]||taken[bottom][k])can=false;if(can)bottom++;}for(let yy=j;yy<bottom;yy++)for(let xx=i;xx<end;xx++)taken[yy][xx]=true;residuals.push({x:g.xs[i],y:g.ys[j],length_mm:g.xs[end]-g.xs[i],width_mm:g.ys[bottom]-g.ys[j]});}return {...best,residual_rects:residuals};}
function build(action,source,targets,parameters,context){parameters=parameters||{};context=context||{};ensure(['Resize','Destroy','Merge','Single'].includes(action),'Unsupported UX-05 action');ensure(source&&source.id,'Source required');const serial=String(context.source_serial_no||source.source_serial_no||source.serial_no||'');ensure(serial,'Input Serial No required');const l=N(source.effective_length_mm??source.length_mm),w=N(source.effective_width_mm??source.width_mm);ensure(l>0&&w>0,'Invalid source dimensions');const originalArea=l*w;
let payload={plan_node_id:String(source.id),source_serial_no:serial,original_node_type:source.node_type,original_item_code:source.item_code||'',original_length_mm:l,original_width_mm:w,original_area_mm2:originalArea,incident_action:action,affected_node_ids_json:JSON.stringify([String(source.id)]),group_area_mm2:originalArea,new_node_type:source.node_type,new_item_code:source.item_code||'',new_length_mm:l,new_width_mm:w,new_area_mm2:originalArea,include_in_repack:1,is_active:1,remarks:parameters.remarks||''};
if(action==='Destroy'){payload.new_node_type='destroyed';payload.new_length_mm=payload.new_width_mm=payload.new_area_mm2=0;payload.include_in_repack=0;return payload;}
if(action==='Resize'){const nl=N(parameters.length_mm),nw=N(parameters.width_mm);ensure(nl>0&&nw>0&&nl<=l+EPS&&nw<=w+EPS,'Resize must reduce dimensions');payload.new_length_mm=nl;payload.new_width_mm=nw;payload.new_area_mm2=nl*nw;payload.new_node_type=Math.min(nl,nw)<N(context.min_leftover_dimension_mm||500)?'waste':'leftover';return payload;}
const nodes=[source,...(targets||[])];const rs=geometry(nodes,action,serial),ids=nodes.map(n=>String(n.id));payload.affected_node_ids_json=JSON.stringify(ids);payload.group_area_mm2=rs.reduce((sum,r)=>sum+area(r),0);payload.original_length_mm=payload.original_width_mm=payload.original_area_mm2=0;payload.original_item_code='';
if(action==='Single'){const g=single(rs);Object.assign(payload,{new_node_type:'leftover',new_length_mm:g.length_mm,new_width_mm:g.width_mm,new_area_mm2:g.area_mm2,target_x_mm:g.x,target_y_mm:g.y,remarks:JSON.stringify({removed_length_mm:g.removed_length_mm,removed_width_mm:g.removed_width_mm})});return payload;}
const m=merge(rs);Object.assign(payload,{new_node_type:Math.min(m.length_mm,m.width_mm)<N(context.min_leftover_dimension_mm||500)?'waste':'leftover',new_length_mm:m.length_mm,new_width_mm:m.width_mm,new_area_mm2:area(m),target_x_mm:m.x,target_y_mm:m.y,remarks:JSON.stringify({residual_rects:m.residual_rects})});ensure(Math.abs(area(m)+m.residual_rects.reduce((s,r)=>s+area(r),0)-payload.group_area_mm2)<EPS,'Merge surface conservation failed');return payload;}
ns.buildUX05Incident=build;ns.ux05Geometry=Object.freeze({single,merge,rect,overlap});
})(typeof window!=='undefined'?window:globalThis);

/* UX-05: Explicitly staged drafts; does not insert rows or touch frm.doc. */
(function(root){'use strict';const ns=root.MatRecoMCPUX20=root.MatRecoMCPUX20||{};
function createBridge(options){const drafts=[];const builder=ns.buildUX05Incident;if(typeof builder!=='function')throw new Error('Load mcp_ux05_action_adapter.js first');
function prepare(preview,lookup,context){if(!preview||!preview.action||!preview.sourceNodeId)throw new Error('Complete UX-04 preview required');if(!['Resize','Destroy','Single','Merge'].includes(preview.action))throw new Error('Action not in UX-05');if(typeof lookup!=='function')throw new TypeError('Node lookup required');const source=lookup(preview.sourceNodeId);const targets=(preview.targetNodeIds||[]).map(id=>{const n=lookup(id);if(!n)throw new Error('Unknown target node '+id);return n;});const payload=builder(preview.action,source,targets,preview.parameters,context);const draft=Object.freeze({action:preview.action,payload:Object.freeze({...payload}),committed:false,serverVerified:false});return draft;}
function stage(draft){if(!draft||draft.committed!==false||draft.serverVerified!==false)throw new Error('Only uncommitted UX-05 drafts can be staged');drafts.push(draft);return drafts.length;}
return {prepare,stage,list:()=>drafts.slice(),clear:()=>{drafts.length=0;},get stagedCount(){return drafts.length;},get enabledForWrites(){return false;}};}
ns.createUX05DraftBridge=createBridge;
})(typeof window!=='undefined'?window:globalThis);

/* UX-06: pure Move intent + Frappe incident payload; NO document writes. */
(function(root){'use strict';
const ns=root.MatRecoMCPUX20=root.MatRecoMCPUX20||{};
const EPS=1e-6;
function num(x){return Number(x)||0;}
function ensure(ok,message){if(!ok)throw new Error(message);}
function kind(n){return String(n&&n.node_type||'').trim().toLowerCase();}
function size(n){return {length_mm:num(n&& (n.effective_length_mm??n.length_mm)),width_mm:num(n&&(n.effective_width_mm??n.width_mm))};}
function box(n){const s=size(n);return {x:num(n&&n.x),y:num(n&&n.y),...s};}
function overlap(a,b){return Math.min(a.x+a.length_mm,b.x+b.length_mm)-Math.max(a.x,b.x)>EPS&&Math.min(a.y+a.width_mm,b.y+b.width_mm)-Math.max(a.y,b.y)>EPS;}
function contains(outer,inner){return inner.x>=outer.x-EPS&&inner.y>=outer.y-EPS&&inner.x+inner.length_mm<=outer.x+outer.length_mm+EPS&&inner.y+inner.width_mm<=outer.y+outer.width_mm+EPS;}
function excluded(n){return !!(n&&(n.is_preexisting_cutout||n.is_single_cutout||n.single_logical_cutout));}
function isFree(n){return ['leftover','waste'].includes(kind(n))&&!excluded(n);}
function targetSheet(tree,serial){return (tree&&tree.nodes||[]).find(n=>String(n.serial_no||n.id)===String(serial));}
function findPiece(tree,id){for(const sheet of tree&&tree.nodes||[]){const node=(sheet.children||[]).find(n=>String(n.id)===String(id));if(node)return {node,sheet};}return null;}
function plan(input){input=input||{};
 const tree=input.tree, sourceId=String(input.sourceNodeId||''),targetSerial=String(input.targetSerialNo||'');
 const found=findPiece(tree,sourceId);ensure(found,'Source piece not present in current cutting tree');
 const source=found.node;ensure(kind(source)==='finished_good','Move requires a finished_good source');
 const sourceSerial=String(found.sheet.serial_no||found.sheet.id);const sheet=targetSheet(tree,targetSerial);
 ensure(sheet,'Target Serial No not found in cutting tree');
 const sourceSize=size(source);ensure(sourceSize.length_mm>0&&sourceSize.width_mm>0,'Source dimensions must be positive');
 const desired={x:num(input.targetX),y:num(input.targetY),...sourceSize};
 ensure(Number.isFinite(Number(input.targetX))&&Number.isFinite(Number(input.targetY)),'Target coordinates required');
 const sheetDimensions=size(sheet);ensure(contains({x:0,y:0,...sheetDimensions},desired),'Target placement is outside sheet bounds');
 const zoneId=String(input.targetZoneId||'');
 const zones=(sheet.children||[]).filter(isFree).filter(n=>!zoneId||String(n.id)===zoneId);
 const zone=zones.find(n=>contains(box(n),desired));
 ensure(zone,'Target position must fit entirely inside a free region');
 const exact=Math.abs(size(zone).length_mm-sourceSize.length_mm)<EPS&&Math.abs(size(zone).width_mm-sourceSize.width_mm)<EPS;
 const moveCase=exact?'swap':'swing';
 for(const child of sheet.children||[]){if(String(child.id)===sourceId)continue;
   if(isFree(child)&&!excluded(child))continue;
   if(kind(child)!=='finished_good'&&kind(child)!=='destroyed'&&kind(child)!=='destroy'&&!excluded(child))continue;
   // Historical cutout geometry is a blocker even if not visually rendered.
   const occupied=box(child);if(occupied.length_mm>0&&occupied.width_mm>0)ensure(!overlap(occupied,desired),'Move overlaps an occupied or excluded region');
 }
 const samePosition=sourceSerial===targetSerial&&Math.abs(num(source.x)-desired.x)<EPS&&Math.abs(num(source.y)-desired.y)<EPS;
 ensure(!samePosition,'Source already occupies this position');
 const dimensions=sourceSize,area=dimensions.length_mm*dimensions.width_mm;
 const payload={plan_node_id:sourceId,source_serial_no:sourceSerial,original_node_type:'finished_good',original_item_code:source.piece_item_code||source.item_code||'',original_length_mm:dimensions.length_mm,original_width_mm:dimensions.width_mm,original_area_mm2:area,incident_action:'Move',affected_node_ids_json:JSON.stringify([sourceId]),group_area_mm2:area,new_node_type:'finished_good',new_item_code:source.piece_item_code||source.item_code||'',new_length_mm:dimensions.length_mm,new_width_mm:dimensions.width_mm,new_area_mm2:area,target_serial_no:targetSerial,target_zone_id:zoneId||String(zone.id),target_x_mm:desired.x,target_y_mm:desired.y,move_case:moveCase,include_in_repack:1,is_active:1,remarks:''};
 return Object.freeze({payload:Object.freeze(payload),case:moveCase,sourceSerial,targetSerial,targetZoneId:String(zone.id),preview:Object.freeze({kind:'move_intention',verifiedByServer:false,source:box(source),target:desired,case:moveCase}),committed:false,serverVerified:false});
}
ns.createUX06MoveDraft=plan;
ns.ux06MoveGeometry=Object.freeze({box,contains,overlap,isFree});
})(typeof window!=='undefined'?window:globalThis);

/* UX-06 staging bridge. No Frappe writes until UX-07 explicit integration. */
(function(root){'use strict';
 const ns=root.MatRecoMCPUX20=root.MatRecoMCPUX20||{};
 function createBridge(){const drafts=[];
 function prepare(preview,tree){if(typeof ns.createUX06MoveDraft!=='function')throw new Error('Load mcp_ux06_move_adapter.js first');
 if(!preview||preview.action!=='Move')throw new Error('Move preview required');
 const target=preview.parameters||{};
 return ns.createUX06MoveDraft({tree,sourceNodeId:preview.sourceNodeId,targetSerialNo:target.target_serial_no,targetZoneId:target.target_zone_id,targetX:target.target_x_mm,targetY:target.target_y_mm});}
 function stage(draft){if(!draft||draft.committed!==false||draft.serverVerified!==false)throw new Error('Only local uncommitted Move drafts can be staged');drafts.push(draft);return drafts.length;}
 return Object.freeze({prepare,stage,list:()=>drafts.slice(),clear:()=>{drafts.length=0;},get stagedCount(){return drafts.length;},get enabledForWrites(){return false;}});}
 ns.createUX06MoveBridge=createBridge;
})(typeof window!=='undefined'?window:globalThis);

/* MCP UX 2.0 — real contextual editor. Geometry remains under existing Python authority. */
(function(root){'use strict';
const ns=root.MatRecoMCPUX20=root.MatRecoMCPUX20||{};
const LABEL={Move:'Déplacer',Merge:'Fusionner',Single:'Chute en L',Resize:'Redimensionner',Destroy:'Détruire'};
const SYMBOL={Move:'↗',Merge:'⊞',Single:'⌞',Resize:'⤢',Destroy:'×'};
const el=(tag,txt,cls)=>{const n=document.createElement(tag);if(txt!==undefined&&txt!==null)n.textContent=txt;if(cls)n.className=cls;return n;};
const style=`
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
function mount(frm,mountAt,opts){
 if(!opts||opts.enabled!==true)return null;
 if(!ns.createWorkspace||!ns.createCanvasRenderer||!ns.createUX04Guide)throw new Error('Modules MCP UX-02 à UX-04 non chargés');
 const ws=ns.createWorkspace(frm,{enabled:true});ws.mount();let disposed=false,guide=null,tree=null;
 const section=el('section',null,'mcp20-editor');const css=el('style');css.textContent=style;section.appendChild(css);
 // Le titre est déjà présent dans l'en-tête natif de frappe.ui.Dialog.

 const grid=el('div',null,'mcp20-grid'),main=el('div',null,'mcp20-main'),side=el('aside',null,'mcp20-side'),actions=el('div',null,'mcp20-actions');
 actions.setAttribute('aria-label','Actions de découpe');main.appendChild(actions);grid.append(main,side);section.appendChild(grid);const foot=el('div','Simulation locale · Aucun incident, Stock Entry ou Serial No ne sera modifié','mcp20-foot');section.appendChild(foot);mountAt.appendChild(section);
 const canvas=ns.createCanvasRenderer(main,(node,sheet)=>{if(!guide)return; if(node)guide.select(node,sheet);else guide.cancel();});
 const navControls=main.querySelector('.mcpux-nav-controls');
 if(navControls){
  if(typeof opts.onReset==='function'){
   const reset=el('button','Réinitialiser','mcp20-reset-warning');reset.type='button';
   reset.title='Attention : annule toutes les modifications locales de la simulation';
   reset.addEventListener('click',()=>opts.onReset());navControls.appendChild(reset);
  }
 }
 function parse(){const raw=typeof opts.getTree==='function'?opts.getTree():(frm.doc.mcp_mode==='Retour Terrain'?(frm.doc.effective_result_json||frm.doc.result_json):(frm.doc.result_json||frm.doc.effective_result_json));const value=typeof raw==='string'?JSON.parse(raw||'{}'):(raw||{});if(!Array.isArray(value.nodes))throw new Error('Résultat MCP indisponible');return value;}
 function line(key,value){const r=el('div',null,'mcp20-line');r.append(el('span',key,'mcp20-k'),el('span',value==null?'—':String(value)));side.appendChild(r);}
 function button(text,fn,cls){const b=el('button',text,cls||'mcp20-secondary');b.type='button';b.addEventListener('click',fn);side.appendChild(b);return b;}
 function locate(){const state=ws.store.getState();if(!state.sourceNodeId||!actions.children.length){actions.style.display='none';return;}const group=[...main.querySelectorAll('svg [data-node-id]')].find(n=>n.getAttribute('data-node-id')===state.sourceNodeId);const bounds=main.getBoundingClientRect();if(!group||!bounds.width){actions.style.display='none';return;}const b=group.getBoundingClientRect();actions.style.display='flex';const width=actions.offsetWidth||430;const left=Math.max(6,Math.min((b.left+b.right)/2-bounds.left-width/2,Math.max(6,bounds.width-width-6)));const proposed=b.top-bounds.top-actions.offsetHeight-12;const below=b.bottom-bounds.top+12;const top=proposed>=6?proposed:Math.min(below,Math.max(6,bounds.height-actions.offsetHeight-6));actions.style.left=left+'px';actions.style.top=top+'px';}
 function highlight(){const state=ws.store.getState();const meta=guide&&guide.stateInfo();const candidates=new Set(meta?meta.candidateIds:[]),targets=new Set(state.targetNodeIds||[]);for(const group of main.querySelectorAll('svg [data-node-id]')){const id=group.getAttribute('data-node-id'),rect=group.querySelector('rect');if(!rect)continue;const chosen=id===state.sourceNodeId||targets.has(id),suggested=candidates.has(id);rect.setAttribute('stroke',id===state.sourceNodeId?'#2563eb':targets.has(id)?'#16a34a':suggested?'#0d9488':'#94a3b8');rect.setAttribute('stroke-width',chosen||suggested?'9':'5');rect.setAttribute('stroke-dasharray',suggested&&!targets.has(id)?'16 10':'none');group.style.cursor=state.status==='selecting_target'&&!suggested?'not-allowed':'pointer';}}
 function render(){if(disposed)return;const s=ws.store.getState();canvas.setSelection(s.sourceNodeId);actions.replaceChildren();side.replaceChildren();
 side.appendChild(el('h4','Action en cours'));const status=el('span',s.busy?'Enregistrement…':s.preview?'Aperçu à valider':s.status==='selecting_target'?'Choisir une cible':s.sourceNodeId?'Zone sélectionnée':'En attente','mcp20-status');side.appendChild(status);
 if(s.sourceNodeId){for(const name of ws.controller.actions){if(!ws.controller.canStart(name,s.sourceNodeType))continue;const b=el('button');const sym=el('span',SYMBOL[name]||'·','mcp20-action-icon');b.append(sym,document.createTextNode(LABEL[name]||name));b.type='button';b.disabled=s.busy;b.dataset.current=String(s.action===name);b.addEventListener('click',()=>guide.begin(name));actions.appendChild(b);}}
 if(!s.sourceNodeId){side.appendChild(el('div','1. Cliquez sur une pièce ou une chute pour afficher les actions disponibles.','mcp20-note'));}
 else {const selected=el('div',null,'mcp20-selected');const src=guide.getItem(s.sourceNodeId);const n=src&&src.node||{};selected.append(el('span','Sélection actuelle','mcp20-k'),el('strong',n.label||s.sourceNodeId));if(n.length_mm&&n.width_mm)selected.append(el('div',`${n.length_mm} × ${n.width_mm} mm`));side.appendChild(selected);line('Action',LABEL[s.action]||'Choisissez une action sur la plaque');if(s.targetNodeIds.length)line('Cibles',s.targetNodeIds.map(id=>{const entry=guide.getItem(id);return entry&&entry.node.label||id;}).join(', '));}
 if(s.status==='selecting_target')side.appendChild(el('div','2. Cliquez sur une cible indiquée par un contour turquoise. La compatibilité géométrique sera contrôlée avant enregistrement.','mcp20-note'));
 if(s.action==='Resize'&&s.status==='action_active'){
  const info=guide.getItem(s.sourceNodeId),n=info&&info.node||{};const container=el('div',null,'mcp20-field');let inputs=[];
  for(const [label,value] of [['Longueur (mm)',n.effective_length_mm||n.length_mm],['Largeur (mm)',n.effective_width_mm||n.width_mm]]){const l=el('label',label),input=el('input');input.type='number';input.min='1';input.step='any';input.value=String(value||'');l.appendChild(input);container.appendChild(l);inputs.push(input);}side.appendChild(container);button('Prévisualiser',()=>guide.setResize(inputs[0].value,inputs[1].value),'mcp20-primary');
 }
 if(s.action==='Merge'&&s.status==='selecting_target'&&s.targetNodeIds.length)button('Prévisualiser la fusion',()=>guide.buildPreview(),'mcp20-primary');
 if(s.action==='Destroy'&&s.status==='action_active')button('Prévisualiser la destruction',()=>guide.buildPreview(),'mcp20-primary');
 if(s.preview){side.appendChild(el('div',(LABEL[s.preview.action]||s.preview.action)+' · '+s.preview.title,'mcp20-note'));side.appendChild(el('p',s.preview.detail));side.appendChild(el('p','Simulation graphique locale, non validée par Python.'));const apply=button('Appliquer à l’aperçu',async()=>{if(typeof opts.onApply!=='function')return;apply.disabled=true;try{await opts.onApply({preview:s.preview,guide,tree,workspace:ws});}catch(e){ws.controller.setError(String(e.message||e));}finally{apply.disabled=false;}},'mcp20-primary');apply.disabled=!!s.busy||typeof opts.onApply!=='function';}
 if(s.error)side.appendChild(el('div',s.error,'mcp20-error'));
 if(s.sourceNodeId)button('Annuler la sélection',()=>guide.cancel());
 highlight();locate();
 }
 function load(){tree=parse();canvas.setTree(tree);if(guide)guide.refresh(tree);else guide=ns.createUX04Guide(ws.store,ws.controller,tree);render();return canvas.getSheets().length;}
 const onKey=e=>{if(e.key==='Escape'&&!disposed&&ws.store.getState().sourceNodeId){guide.cancel();}};section.addEventListener('keydown',onKey);
 const unsub=ws.store.subscribe(render);const update=()=>locate();window.addEventListener('resize',update);main.addEventListener('scroll',update,true);load();
 return {refresh:load,getState:()=>ws.store.getState(),destroy(){if(disposed)return;disposed=true;unsub();window.removeEventListener('resize',update);main.removeEventListener('scroll',update,true);section.removeEventListener('keydown',onKey);canvas.destroy();section.remove();ws.destroy();}};
}
ns.mountUX20Editor=mount;
})(typeof window!=='undefined'?window:globalThis);

/* UX 2.0 modal integration */
/* UX 2.0 modal: browser-only simulation, NO Frappe document mutation. */
(function(root){'use strict';
const ns=root.MatRecoMCPUX20=root.MatRecoMCPUX20||{};
const clone=v=>JSON.parse(JSON.stringify(v));
const num=v=>Number(v)||0;
function originalTree(frm){
 const raw=frm.doc.mcp_mode==='Retour Terrain'?(frm.doc.effective_result_json||frm.doc.result_json):(frm.doc.result_json||frm.doc.effective_result_json);
 const value=typeof raw==='string'?JSON.parse(raw||'{}'):clone(raw||{});
 if(!Array.isArray(value.nodes))throw new Error('Aucun plan de découpe disponible pour cette simulation.');
 return clone(value);
}
function updateSimulation(tree,preview){
 if(!root.MatRecoMCPVue?.simulate)throw new Error('Aperçu non disponible : moteur de simulation Vue inaccessible.');
 return root.MatRecoMCPVue.simulate(tree,preview);
}
async function loadBackend(frm){
 if(typeof frappe.call!=='function')return null;
 const client=root.MatRecoMCPVue.createFrappeClient(frappe,frm.doc.name);
 const loaded=await client.load();
 frm.__mcp_ux20_backend={client,loaded};return loaded;
}
function serverOptions(frm){
 const backend=frm.__mcp_ux20_backend;
 return backend?{baseTree:clone(backend.loaded.effective_tree),documentVersion:backend.loaded.document_version,allowRotation:!!backend.loaded.allow_rotation,previewAction:payload=>backend.client.preview(payload),
  resetPlan:async payload=>{
   if(frm.is_dirty?.())throw new Error('Enregistrez les modifications du formulaire avant de réinitialiser.');
   if(frm.__mcp_ux20_saving)throw new Error('Un enregistrement est déjà en cours.');
   frm.__mcp_ux20_saving=true;
   try{
    const result=await backend.client.reset(payload);
    if(!result.reset)throw new Error('Réinitialisation non confirmée par Python.');
    backend.loaded=result;frm.__mcp_ux20_visual=clone(result.effective_tree);
    frm.__mcp_ux20_base_signature=JSON.stringify(result.effective_tree);
    const modal=frm.__mcp_ux20_modal_state;
    if(modal){modal.tree=clone(result.effective_tree);modal.base=clone(result.effective_tree);}
    try{await frm.reload_doc();}catch(error){frappe.show_alert({message:'Réinitialisation enregistrée. Rechargez le formulaire pour actualiser son affichage.',indicator:'orange'});}
    if(modal)renderPreviewField(frm,{useCurrent:false});
    frappe.show_alert({message:'Incidents supprimés. Planification initiale restaurée.',indicator:'green'});
    return result;
   }finally{frm.__mcp_ux20_saving=false;}
  },
  compensationLoad:()=>backend.client.compensationLoad(),compensationPreview:payload=>backend.client.compensationPreview(payload),
  compensationApply:async payload=>{
   if(frm.is_dirty?.())throw new Error('Enregistrez les modifications du formulaire avant de confirmer.');
   if(frm.__mcp_ux20_saving)throw new Error('Un enregistrement est déjà en cours.');
   frm.__mcp_ux20_saving=true;
   try{
    const result=await backend.client.compensationApply(payload);
    if(!result.applied)throw new Error('Application non confirmée par Python.');
    backend.loaded=result;frm.__mcp_ux20_visual=clone(result.effective_tree);
    frm.__mcp_ux20_base_signature=JSON.stringify(result.effective_tree);
    const modal=frm.__mcp_ux20_modal_state;
    if(modal){modal.tree=clone(result.effective_tree);modal.base=clone(result.effective_tree);}
    // The form refresh must keep the current modal mounted. The active store
    // returns to the workshop only after this confirmed response resolves.
    try{await frm.reload_doc();}catch(error){frappe.show_alert({message:'Compensation enregistrée. Rechargez le formulaire pour actualiser son affichage.',indicator:'orange'});}
    if(!frm.__mcp_ux20_preview_instance?.store?.compensationOpen)renderPreviewField(frm,{useCurrent:false});
    return result;
   }finally{frm.__mcp_ux20_saving=false;}
  }}:null;
}
async function savePending(frm,tree,session){
 if(Number(frm.doc.docstatus||0)!==0)throw new Error('Document soumis : modification impossible.');
 const backend=frm.__mcp_ux20_backend;
 if(!backend){frm.__mcp_ux20_visual=clone(tree);return null;}
 if(frm.__mcp_ux20_saving)throw new Error('Un enregistrement est déjà en cours.');
 if(frm.is_dirty?.())throw new Error('Enregistrez d’abord les autres modifications du formulaire, puis rechargez l’éditeur.');
 if(!session?.pendingIncidents?.length){const saved=await backend.client.load();backend.loaded=saved;frm.__mcp_ux20_visual=clone(saved.effective_tree);return saved;}
 frm.__mcp_ux20_saving=true;
 const previous=clone(frm.doc.material_plan_incidents||[]);
 const wasUnsaved=frm.doc.__unsaved;let persisted=false;
 try{
  const prepared=await backend.client.prepare({pending_incidents:session.pendingIncidents,document_version:session.documentVersion});
  for(const payload of prepared.incidents){const row=frm.add_child('material_plan_incidents');Object.assign(row,payload);}
  frm.refresh_field('material_plan_incidents');
  await frm.save();
  if(frm.is_dirty?.())throw new Error('La sauvegarde du MCP n’a pas été confirmée.');
  persisted=true;
  const saved=await backend.client.load();
  backend.loaded=saved;frm.__mcp_ux20_visual=clone(saved.effective_tree);frm.__mcp_ux20_base_signature=JSON.stringify(originalTree(frm));
  frappe.show_alert({message:'Incidents enregistrés. Résultat Python rechargé.',indicator:'green'});
  return saved;
 }catch(error){
  if(!persisted){frm.doc.material_plan_incidents=previous;frm.doc.__unsaved=wasUnsaved;frm.refresh_field('material_plan_incidents');}
  else throw new Error('Les incidents sont enregistrés, mais le résultat n’a pas pu être rechargé. Rechargez le formulaire avant de poursuivre.');
  throw error;
 }finally{frm.__mcp_ux20_saving=false;}
}
function renderPreviewField(frm,{useCurrent=true}={}){
 const data=(useCurrent?frm.__mcp_ux20_preview_instance?.store?.simulationTree:null)||frm.__mcp_ux20_visual,field=frm.fields_dict?.cutting_plan_preview;
 if(!data||!field?.$wrapper?.length)return false;
 const wrapper=field.$wrapper[0];
 const priorStore=useCurrent?frm.__mcp_ux20_preview_instance?.store:null;
 const session=priorStore?{tree:clone(priorStore.simulationTree),pendingIncidents:clone(priorStore.pendingIncidents||[]),documentVersion:priorStore.documentVersion}:null;
 frm.__mcp_ux20_preview_instance?.unmount();
 if(root.MatRecoMCPVue?.renderPreview){
   frm.__mcp_ux20_preview_instance=root.MatRecoMCPVue.renderPreview(wrapper,clone(data),{
     server:serverOptions(frm),session,
     readonly:Number(frm.doc.docstatus||0)!==0||!!(frm.__mcp_ux20_backend&&!frm.__mcp_ux20_backend.loaded.editable),submitted:Number(frm.doc.docstatus||0)!==0,
     context:{reference:frm.doc.name,material:frm.doc.source_item||''},
     onToggleExpand:()=>openModal(frm),
     onApplyPreview:async (tree,session)=>{
       const saved=await savePending(frm,tree,session);
       if(!saved)frappe.show_alert({message:'Aperçu actualisé.',indicator:'blue'});
       return saved;
     },
   });
 }else{
   wrapper.replaceChildren();const heading=document.createElement('p');heading.textContent='Simulation locale · Non enregistrée · Non validée par Python';wrapper.appendChild(heading);
   const renderer=ns.createCanvasRenderer(wrapper,null);renderer.setTree(data);
 }

 return true;
}
const vueJS='/assets/mat_reco/js/mcp_vue_dist/mcp_vue.iife.js';
const vueCSS='/assets/mat_reco/js/mcp_vue_dist/mat-reco-mcp-ux20-vue.css';
let vueAssetsPromise=null;
function loadVueAssets(){
 if(typeof root.MatRecoMCPVue?.mount==='function'&&root.MatRecoMCPVue.version==='20261014_terrain_rotation_1')return Promise.resolve();
 if(vueAssetsPromise)return vueAssetsPromise;
 vueAssetsPromise=new Promise((resolve,reject)=>{
   const existingStyle=document.querySelector('link[data-mcp-vue-style]');
   if(existingStyle)existingStyle.href=vueCSS+'?ux20_vue=20261014_terrain_rotation_1';
   if(!existingStyle){
     const css=document.createElement('link');css.rel='stylesheet';css.href=vueCSS+'?ux20_vue=20261014_terrain_rotation_1';css.dataset.mcpVueStyle='1';document.head.appendChild(css);
   }
   const script=document.createElement('script');
   // Bypass intermediary and browser caches during the current migration.
   script.src=vueJS+'?ux20_vue=20261014_terrain_rotation_1';script.async=true;
   script.onload=()=>typeof root.MatRecoMCPVue?.mount==='function'?resolve():reject(new Error('Le fichier Vue est chargé mais MatRecoMCPVue.mount est absent. Reconstruire le bundle Vite.'));
   script.onerror=()=>reject(new Error('Bundle Vue inaccessible : '+vueJS+' (404 ou CSP).'));
   document.head.appendChild(script);
 }).catch(error=>{vueAssetsPromise=null;throw error;});
 return vueAssetsPromise;
}
function openModal(frm){
 console.info('[MCP UX20] Ouverture modal Vue — build 20261014_terrain_rotation_1');
 if(frm.__mcp_ux20_modal?.$wrapper?.is(':visible'))return frm.__mcp_ux20_modal;
 const latest=frm.__mcp_ux20_preview_instance?.store?.simulationTree||frm.__mcp_ux20_visual||originalTree(frm);
 const priorStore=frm.__mcp_ux20_preview_instance?.store;
 const session=priorStore?{tree:clone(priorStore.simulationTree),pendingIncidents:clone(priorStore.pendingIncidents||[]),documentVersion:priorStore.documentVersion}:null;
 const state={base:clone(latest),tree:null,vue:null,editor:null,closed:false};state.tree=clone(state.base);
 const dlg=new frappe.ui.Dialog({title:'Atelier de découpe',size:'extra-large',fields:[{fieldtype:'HTML',fieldname:'ux20_editor'}]});
 frm.__mcp_ux20_modal=dlg;frm.__mcp_ux20_modal_state=state;dlg.show();
 const wrapper=dlg.fields_dict.ux20_editor.$wrapper[0];
 const css=document.createElement('style');css.textContent=`
 .modal-dialog:has(.mcp20-modal-inner){width:70vw!important;max-width:70vw!important;margin:2vh auto!important}
 .modal:has(.mcp20-modal-inner) .modal-body{padding:0!important;max-height:calc(90vh - 30px)!important;overflow:auto}
 .modal:has(.mcp20-modal-inner) .modal-content{max-height:90vh!important}
 .modal:has(.mcp20-modal-inner) .modal-header,.modal:has(.mcp20-modal-inner) .modal-footer{display:none!important}
 .modal-dialog.mcp20-expanded{width:96vw!important;max-width:96vw!important}
 @media(max-width:900px){.modal-dialog:has(.mcp20-modal-inner){width:96vw!important;max-width:96vw!important}}
 .mcp20-modal-inner{min-height:300px}
 .mcp20-modal-inner .mcpv-grid{min-height:350px}
 .mcp20-modal-inner .mcpv-canvas svg{height:min(48vh,530px)}
 `;wrapper.appendChild(css);
 const host=document.createElement('div');host.className='mcp20-modal-inner';wrapper.appendChild(host);
 const close=document.createElement('button');close.type='button';close.textContent='×';close.setAttribute('aria-label','Fermer l’atelier');close.style.cssText='position:absolute;right:8px;top:4px;z-index:3;background:transparent;border:0;color:#aaa';close.onclick=()=>dlg.hide();wrapper.style.position='relative';wrapper.appendChild(close);
 const message=document.createElement('div');message.style.cssText='padding:24px;color:#64748b';message.textContent='Chargement de Vue 3 + Pinia…';host.appendChild(message);
 dlg.$wrapper.on('hidden.bs.modal.mcpUX20',()=>{
   state.closed=true;
   try{state.vue?.unmount();}catch(err){console.warn('[MCP Vue] unmount',err);}
   try{state.editor?.destroy();}catch(err){console.warn('[MCP UX legacy] destroy',err);}
   state.vue=null;state.editor=null;frm.__mcp_ux20_modal=null;frm.__mcp_ux20_modal_state=null;
   dlg.$wrapper.off('hidden.bs.modal.mcpUX20');
 });
 loadVueAssets().then(async()=>{
   if(!frm.__mcp_ux20_backend)await loadBackend(frm);
   if(state.closed)return;
   host.replaceChildren();
   const vueHost=document.createElement('div');vueHost.id='mcp-ux20-vue-root';host.appendChild(vueHost);
   state.vue=root.MatRecoMCPVue.mount(vueHost,{
      tree:clone(state.tree),
      readonly:Number(frm.doc.docstatus||0)!==0||!!(frm.__mcp_ux20_backend&&!frm.__mcp_ux20_backend.loaded.editable),
      server:serverOptions(frm),session,
      onReset:()=>{state.tree=clone(state.base);},
      context:{reference:frm.doc.name,material:frm.doc.source_item||frm.doc.material_name||frm.doc.item_name||frm.doc.item_code||''},
      onToggleExpand:()=>dlg.$wrapper.find('.modal-dialog').toggleClass('mcp20-expanded'),
      onApplyPreview:async (tree,session)=>{
        const saved=await savePending(frm,tree,session);
        state.tree=clone(saved?.effective_tree||tree);state.base=clone(state.tree);
        frm.__mcp_ux20_visual=clone(state.tree);renderPreviewField(frm,{useCurrent:false});
        if(!saved)frappe.show_alert({message:'Aperçu actualisé.',indicator:'blue'});
        return saved;
      },
   });
   if(!vueHost.hasAttribute('data-v-app'))throw new Error('Vue mount() a été appelé mais aucun composant Vue n’est monté.');

 }).catch(error=>{
   state.vue?.unmount();state.vue=null;
   console.error('[MCP UX 2.0 Vue]',error);
   if(state.closed)return;
   // Keep the legacy editor as a temporary fallback if Vue assets are unavailable.
   host.replaceChildren();
   const warning=document.createElement('div');warning.className='alert alert-warning';warning.textContent='Interface classique (secours) : Vue n’a pas pu démarrer. '+String(error.message||error);host.appendChild(warning);
   if(Number(frm.doc.docstatus||0)!==0)return;
   const legacy=document.createElement('div');host.appendChild(legacy);
   state.editor=ns.mountUX20Editor(frm,legacy,{enabled:true,getTree:()=>state.tree,onReset:()=>{state.tree=clone(state.base);state.editor.refresh();},onApply:async ({preview})=>{
     if(Number(frm.doc.docstatus||0)!==0)throw new Error('Document soumis : modification impossible.');
     state.tree=updateSimulation(state.tree,preview);state.editor.refresh();
     frm.__mcp_ux20_visual=clone(state.tree);renderPreviewField(frm,{useCurrent:false});
   }});
 });
 return dlg;
}

async function initializePreview(frm){
 if(frm.__mcp_ux20_saving)return false;
 let base;
 try{base=originalTree(frm);}catch{return false;}
 const documentName=frm.doc.name;
 await loadVueAssets();
 if(frm.__mcp_ux20_saving)return false;
 const loaded=await loadBackend(frm);
 if(loaded)base=loaded.effective_tree;
 if(frm.doc.name!==documentName)return false;
 const signature=JSON.stringify(base);
 if(frm.__mcp_ux20_base_signature&&frm.__mcp_ux20_base_signature!==signature){
   frm.__mcp_ux20_modal?.hide();
   frm.__mcp_ux20_preview_instance?.unmount();frm.__mcp_ux20_preview_instance=null;
   frm.__mcp_ux20_visual=null;
 }
 frm.__mcp_ux20_base_signature=signature;
 if(!frm.__mcp_ux20_visual)frm.__mcp_ux20_visual=clone(base);
 if(Number(frm.doc.docstatus||0)!==0){lockEditors(frm);return true;}
 return renderPreviewField(frm);
}
function lockEditors(frm){
 if(Number(frm.doc.docstatus||0)===0)return;
 const modal=frm.__mcp_ux20_modal_state;
 const latest=modal?.vue?.store?.simulationTree||frm.__mcp_ux20_preview_instance?.store?.simulationTree||frm.__mcp_ux20_visual;
 if(latest)frm.__mcp_ux20_visual=clone(latest);
 modal?.vue?.store?.setLocked(true);
 if(modal?.editor)frm.__mcp_ux20_modal?.hide();
 frm.__mcp_ux20_preview_instance?.store?.setLocked(true);
 if(frm.__mcp_ux20_visual)renderPreviewField(frm,{useCurrent:false});
}
ns.version='20261014_terrain_rotation_1';
ns.initializeUX20Preview=initializePreview;
ns.lockUX20Editors=lockEditors;
ns.openUX20Modal=openModal;ns.renderUX20ReadOnly=renderPreviewField;ns.simulateUX20Operation=updateSimulation;
})(typeof window!=='undefined'?window:globalThis);
