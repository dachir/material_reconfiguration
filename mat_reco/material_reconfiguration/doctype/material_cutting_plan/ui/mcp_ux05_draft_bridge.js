/* UX-05: Explicitly staged drafts; does not insert rows or touch frm.doc. */
(function(root){'use strict';const ns=root.MatRecoMCPUX20=root.MatRecoMCPUX20||{};
function createBridge(options){const drafts=[];const builder=ns.buildUX05Incident;if(typeof builder!=='function')throw new Error('Load mcp_ux05_action_adapter.js first');
function prepare(preview,lookup,context){if(!preview||!preview.action||!preview.sourceNodeId)throw new Error('Complete UX-04 preview required');if(!['Resize','Destroy','Single','Merge'].includes(preview.action))throw new Error('Action not in UX-05');if(typeof lookup!=='function')throw new TypeError('Node lookup required');const source=lookup(preview.sourceNodeId);const targets=(preview.targetNodeIds||[]).map(id=>{const n=lookup(id);if(!n)throw new Error('Unknown target node '+id);return n;});const payload=builder(preview.action,source,targets,preview.parameters,context);const draft=Object.freeze({action:preview.action,payload:Object.freeze({...payload}),committed:false,serverVerified:false});return draft;}
function stage(draft){if(!draft||draft.committed!==false||draft.serverVerified!==false)throw new Error('Only uncommitted UX-05 drafts can be staged');drafts.push(draft);return drafts.length;}
return {prepare,stage,list:()=>drafts.slice(),clear:()=>{drafts.length=0;},get stagedCount(){return drafts.length;},get enabledForWrites(){return false;}};}
ns.createUX05DraftBridge=createBridge;
})(typeof window!=='undefined'?window:globalThis);
