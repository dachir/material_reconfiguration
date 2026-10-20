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
