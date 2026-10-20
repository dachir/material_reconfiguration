/* MCP UX-03: non-committing contextual toolbar. */
(function(root){'use strict';const ns=root.MatRecoMCPUX20=root.MatRecoMCPUX20||{};
function createToolbar(host,controller,store){const bar=document.createElement('div');bar.style.cssText='display:none;flex-wrap:wrap;gap:6px;padding:10px;border:1px solid #e2e8f0;border-radius:10px;background:white;box-shadow:0 2px 8px #0001';bar.setAttribute('aria-label','Actions de découpe');host.appendChild(bar);
const unsub=store.subscribe(render);function render(state){bar.replaceChildren();bar.style.display=state.sourceNodeId?'flex':'none';if(!state.sourceNodeId)return;for(const action of controller.actions){if(!controller.canStart(action,state.sourceNodeType))continue;const btn=document.createElement('button');btn.type='button';btn.textContent=action;btn.disabled=state.busy;btn.style.cssText='padding:6px 10px;border:1px solid #cbd5e1;border-radius:6px;background:'+(state.action===action?'#dbeafe':'white')+';cursor:pointer';btn.addEventListener('click',()=>controller.begin(action));bar.appendChild(btn);}}
render(store.getState());return {destroy(){unsub();bar.remove();}};}
ns.createContextToolbar=createToolbar;
})(typeof window!=='undefined'?window:globalThis);
