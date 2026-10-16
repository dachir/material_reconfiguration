export function compositionThickness(node) {
 if(!node)return null;
 const children=node.children||[];
 if(node.item_type==='ACCESSOIRE')return 0;
 if(['PRIMAIRE','AIR'].includes(node.item_type))return Number(node.thickness_mm)>0?Number(node.thickness_mm):null;
 if(node.item_type==='DECOUPE')return children.length===1?compositionThickness(children[0]):null;
 if(node.item_type!=='OUVRAGE'||!children.length)return null;
 let total=Number(node.air_gap_mm||0);
 if(!Number.isFinite(total)||total<0)return null;
 for(const child of children){const thickness=compositionThickness(child),qty=Number(child.qty_factor??1);if(thickness===null||!Number.isInteger(qty)||qty<=0)return null;total+=thickness*qty;}
 return Math.round(total*1000000)/1000000;
}
