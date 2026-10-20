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
