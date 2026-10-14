export const asNumber = value => Number(value) || 0;
export const copy = value => JSON.parse(JSON.stringify(value));
export const nodeId = node => String(node?.node_id ?? node?.id ?? '');
export const labels = Object.freeze({Move:'Déplacer',Merge:'Fusionner',Single:'Chute en L',Resize:'Redimensionner',Destroy:'Détruire'});
export function normalizeTree(input) {
 const tree=typeof input==='string'?JSON.parse(input||'{}'):copy(input||{});
 if(!Array.isArray(tree.nodes))throw new Error('Plan invalide : nodes manquant.');
 return tree;
}
export function findPiece(tree,id){for(const sheet of tree.nodes){const node=(sheet.children||[]).find(n=>nodeId(n)===String(id));if(node)return {sheet,node};}return null;}
export function rect(n){return {x:asNumber(n.x),y:asNumber(n.y),length_mm:asNumber(n.node_type==='destroyed'?n.length_mm:n.effective_length_mm??n.length_mm),width_mm:asNumber(n.node_type==='destroyed'?n.width_mm:n.effective_width_mm??n.width_mm)};}
export function regions(n){
 if(Array.isArray(n.visual_regions))return n.visual_regions.map(rect);
 const r=rect(n),l=asNumber(n.removed_length_mm),w=asNumber(n.removed_width_mm);
 if(l>0&&w>0)return [{x:r.x+l,y:r.y,length_mm:r.length_mm-l,width_mm:w},{x:r.x,y:r.y+w,length_mm:r.length_mm,width_mm:r.width_mm-w}].filter(p=>p.length_mm>0&&p.width_mm>0);
 return [r];
}
export const area=n=>regions(n).reduce((s,r)=>s+r.length_mm*r.width_mm,0);
export const overlaps=(a,b)=>Math.min(a.x+a.length_mm,b.x+b.length_mm)-Math.max(a.x,b.x)>0.001&&Math.min(a.y+a.width_mm,b.y+b.width_mm)-Math.max(a.y,b.y)>0.001;
const contains=(a,b)=>b.x>=a.x&&b.y>=a.y&&b.x+b.length_mm<=a.x+a.length_mm&&b.y+b.width_mm<=a.y+a.width_mm;
export function pathFor(n){return regions(n).map(r=>`M${r.x},${r.y}h${r.length_mm}v${r.width_mm}h${-r.length_mm}Z`).join(' ');}
export const allowedActions=n=>n?.__preexisting_cutout?[]:n?.node_type==='finished_good'?['Move','Resize','Destroy']:n?.node_type==='leftover'?['Merge','Single']:n?.node_type==='waste'?['Merge','Resize','Destroy']:[];
function union(a,b,action){
 const rs=[...regions(a),...regions(b)];
 if(rs.some((r,i)=>rs.slice(i+1).some(t=>overlaps(r,t))))throw new Error('Les régions se superposent.');
 const x=Math.min(...rs.map(r=>r.x)),y=Math.min(...rs.map(r=>r.y)),right=Math.max(...rs.map(r=>r.x+r.length_mm)),bottom=Math.max(...rs.map(r=>r.y+r.width_mm));
 const bounds={x,y,length_mm:right-x,width_mm:bottom-y},sum=area(a)+area(b),missing=bounds.length_mm*bounds.width_mm-sum;
 if(action==='Merge'){if(Math.abs(missing)>0.01)throw new Error('Fusion rectangulaire impossible.');return {...bounds,area_mm2:sum};}
 // The supported physical L has exactly one upper-left notch.
 for(const hx of [...new Set(rs.flatMap(r=>[r.x,r.x+r.length_mm]))])for(const hy of [...new Set(rs.flatMap(r=>[r.y,r.y+r.width_mm]))]){
 const hole={x,y,length_mm:hx-x,width_mm:hy-y};
 if(hole.length_mm>0&&hole.width_mm>0&&hx<right&&hy<bottom&&Math.abs(hole.length_mm*hole.width_mm-missing)<0.01&&!rs.some(r=>overlaps(r,hole)))return {...bounds,area_mm2:sum,geometry_type:'single',removed_length_mm:hole.length_mm,removed_width_mm:hole.width_mm,visual_regions:rs};
 }
 throw new Error('Aperçu non disponible : les régions ne forment pas une chute en L compatible.');
}
// The initiating leftover grows; only an aligned strip is taken from its donor.
// For waste -> leftover, the existing leftover still receives the recovered material.
export function mergePlan(a,b){
 const base=a.node_type==='leftover'?a:b.node_type==='leftover'?b:a;
 const donor=base===a?b:a;
 const type=a.node_type==='leftover'||b.node_type==='leftover'?'leftover':'waste';
 try{return {geometry:union(a,b,'Merge'),node_type:type,base,donor};}catch(error){if(type!=='leftover')throw error;}
 if(regions(base).length!==1||regions(donor).length!==1)throw new Error('Fusion partielle non disponible pour une région avec encoche.');
 const l=regions(base)[0],w=regions(donor)[0];let cut;
 const equal=(x,y)=>Math.abs(x-y)<0.001;
 if(overlaps(l,w))throw new Error('Les régions se superposent.');
 if(equal(l.x+l.length_mm,w.x)||equal(w.x+w.length_mm,l.x))cut={x:w.x,y:l.y,length_mm:w.length_mm,width_mm:l.width_mm};
 else if(equal(l.y+l.width_mm,w.y)||equal(w.y+w.width_mm,l.y))cut={x:l.x,y:w.y,length_mm:l.length_mm,width_mm:w.width_mm};
 if(!cut||!contains(w,cut))throw new Error('Aucune bande adjacente ne prolonge la chute source en rectangle.');
 const geometry=union(base,cut,'Merge');
 return {geometry,node_type:type,base,donor,reclaimed:cut,remainder:subtract(w,cut)};
}
// Maximal slots are alternatives for one move. Residuals use disjoint regions.
export function movePlacement(source,target,{allow_rotation=false,rotation_degrees='auto'}={}){
 if(!['auto',0,90].includes(rotation_degrees)||rotation_degrees===90&&!allow_rotation)return null;
 const r=rect(source),t=rect(target),rl=asNumber(target.removed_length_mm),rw=asNumber(target.removed_width_mm);
 const slots=rl>0&&rw>0?[{x:t.x+rl,y:t.y,length_mm:t.length_mm-rl,width_mm:t.width_mm},{x:t.x,y:t.y+rw,length_mm:t.length_mm,width_mm:t.width_mm-rw}]:regions(target);
 const orientations=rotation_degrees==='auto'?(allow_rotation?[0,90]:[0]):[rotation_degrees];
 for(const degrees of orientations){
  const length_mm=degrees===90?r.width_mm:r.length_mm,width_mm=degrees===90?r.length_mm:r.width_mm;
  const slot=slots.find(s=>s.length_mm>=length_mm&&s.width_mm>=width_mm);
  if(slot)return {x:slot.x,y:slot.y,length_mm,width_mm,rotation_degrees:degrees};
 }
 return null;
}
export function candidateFor(action,source,target,options={}){
 if(!source||!target||nodeId(source.node)===nodeId(target.node)||source.node.__preexisting_cutout||target.node.__preexisting_cutout)return false;
 if(!allowedActions(source.node).includes(action))return false;
 if(action==='Merge'&&!['leftover','waste'].includes(target.node.node_type))return false;
 if(action!=='Merge'&&!['leftover','waste'].includes(target.node.node_type))return false;
 if(action==='Move')return !!movePlacement(source.node,target.node,options);
 if(source.sheet!==target.sheet)return false;
 try{if(action==='Merge')mergePlan(source.node,target.node);else if(action==='Single')union(source.node,target.node,action);else return false;return true;}catch{return false;}
}
function generated(sheet,base,r,suffix,type='leftover'){let id=nodeId(base)+'::UX20'+suffix;while(sheet.children.some(n=>nodeId(n)===id))id+='x';return {...base,...r,id,...(base.node_id!==undefined?{node_id:id}:{}),node_type:type,geometry_type:'rectangle',visual_regions:undefined,removed_length_mm:0,removed_width_mm:0,effective_length_mm:r.length_mm,effective_width_mm:r.width_mm,area_mm2:r.length_mm*r.width_mm,label:type==='waste'?'Déchet (simulation)':'Chute (simulation)',visual_simulation:true};}
function subtract(region,cut){return [{x:region.x,y:region.y,length_mm:region.length_mm,width_mm:cut.y-region.y},{x:region.x,y:cut.y+cut.width_mm,length_mm:region.length_mm,width_mm:region.y+region.width_mm-cut.y-cut.width_mm},{x:region.x,y:cut.y,length_mm:cut.x-region.x,width_mm:cut.width_mm},{x:cut.x+cut.length_mm,y:cut.y,length_mm:region.x+region.length_mm-cut.x-cut.length_mm,width_mm:cut.width_mm}].filter(r=>r.length_mm>0&&r.width_mm>0);}
export function simulate(tree,operation){
 const next=copy(tree),src=findPiece(next,operation.sourceNodeId),target=findPiece(next,operation.targetNodeIds?.[0]);
 if(!src||!allowedActions(src.node).includes(operation.action))throw new Error('Action non applicable.');
 const {action}=operation,n=src.node,r=rect(n);
 if(action==='Destroy'){n.node_type='destroyed';n.visual_simulation=true;return next;}
 if(action==='Resize'){
 const l=Number(operation.parameters?.length_mm),w=Number(operation.parameters?.width_mm);
 if(!Number.isFinite(l)||!Number.isFinite(w)||l<=0||w<=0||l>r.length_mm||w>r.width_mm)throw new Error('Aperçu non disponible : seules les réductions positives sont prises en charge.');
 const parts=regions(n);
 if(parts.length!==1||['x','y','length_mm','width_mm'].some(key=>Math.abs(parts[0][key]-r[key])>0.001))throw new Error('Aperçu non disponible : redimensionnement d’une région avec encoche.');
 const cut={...r,length_mm:l,width_mm:w};n.effective_length_mm=l;n.effective_width_mm=w;n.area_mm2=l*w;if(n.visual_regions)n.visual_regions=[cut];
 subtract(r,cut).forEach((p,i)=>src.sheet.children.push(generated(src.sheet,n,p,'RESIZE'+i,n.node_type==='waste'?'waste':'leftover')));return next;
 }
 if(!candidateFor(action,src,target,operation.parameters))throw new Error('Aperçu non disponible : cible incompatible.');
 if(action==='Merge'||action==='Single'){
 const plan=action==='Merge'?mergePlan(n,target.node):{geometry:union(n,target.node,action),node_type:'leftover',base:n};
 const geometry=plan.geometry;
 if(src.sheet.children.some(p=>p!==n&&p!==target.node&&regions({...geometry}).some(r=>regions(p).some(q=>overlaps(r,q)))))throw new Error('Aperçu non disponible : zone fusionnée occupée.');
 src.sheet.children=src.sheet.children.filter(p=>p!==n&&p!==target.node);
 const merged=generated(src.sheet,plan.base,geometry,action,plan.node_type);Object.assign(merged,geometry,{effective_length_mm:geometry.length_mm,effective_width_mm:geometry.width_mm});
 if(action==='Merge'){
  if(plan.base.id!==undefined)merged.id=plan.base.id;else delete merged.id;
  if(plan.base.node_id!==undefined)merged.node_id=plan.base.node_id;
  if(plan.base.label!==undefined)merged.label=plan.base.label;
 }
 src.sheet.children.push(merged);
 if(plan.remainder?.length){
  plan.remainder.forEach((r,i)=>{
   const part=generated(src.sheet,plan.donor,r,'REMAIN'+i,plan.donor.node_type);
   if(i===0){if(plan.donor.id!==undefined)part.id=plan.donor.id;else delete part.id;if(plan.donor.node_id!==undefined)part.node_id=plan.donor.node_id;}
   src.sheet.children.push(part);
  });
 }
 return next;
 }

 const available=regions(target.node),cut=movePlacement(n,target.node,operation.parameters);
 if((target.sheet.children||[]).some(p=>p!==n&&p!==target.node&&regions(p).some(q=>overlaps(q,cut))))throw new Error('Aperçu non disponible : destination occupée.');
 if(!contains(rect(target.sheet),cut))throw new Error('Destination hors plaque.');
 target.sheet.children=target.sheet.children.filter(p=>p!==target.node);src.sheet.children=src.sheet.children.filter(p=>p!==n);
 target.sheet.children.push({...n,x:cut.x,y:cut.y,length_mm:cut.length_mm,width_mm:cut.width_mm,effective_length_mm:cut.length_mm,effective_width_mm:cut.width_mm,effective_area_mm2:cut.length_mm*cut.width_mm,rotation:!!n.rotation!==(cut.rotation_degrees===90),__move_rotation_degrees:cut.rotation_degrees,source_serial_no:target.sheet.source_serial_no??target.sheet.serial_no??n.source_serial_no});
 src.sheet.children.push(generated(src.sheet,n,r,'FREE'));
 available.flatMap(p=>{
  if(!overlaps(p,cut))return [p];
  const x=Math.max(p.x,cut.x),y=Math.max(p.y,cut.y),length_mm=Math.min(p.x+p.length_mm,cut.x+cut.length_mm)-x,width_mm=Math.min(p.y+p.width_mm,cut.y+cut.width_mm)-y;
  return subtract(p,{x,y,length_mm,width_mm});
 }).forEach((p,i)=>target.sheet.children.push(generated(target.sheet,target.node,p,'MOVE'+i)));

 return next;
}
