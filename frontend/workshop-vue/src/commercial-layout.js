// Deterministic commercial graph geometry. No requests or financial recomputation.
export const COMMERCIAL_COLUMNS = [
 {kind:'project',label:'Chantiers'}, {kind:'quotation',label:'Devis'},
 {kind:'order',label:'Commandes'}, {kind:'delivery',label:'Bordereaux spéciaux'},
 {kind:'payment',label:'Règlements spéciaux'},
];
const COLUMNS = new Map(COMMERCIAL_COLUMNS.map((column,index)=>[column.kind,index]));
const CARD_WIDTH=270, CARD_HEIGHT=124, STRIDE=330, MARGIN=28, GAP=34;
const GRAPH_KINDS=new Set([...COLUMNS.keys(),'study']);
const CAPABILITY={project:'can_read_projects',quotation:'can_read_quotations',order:'can_read_orders',study:'can_read_studies',delivery:'can_read_deliveries',payment:'can_read_payments',native_delivery:'can_read_native_deliveries',invoice:'can_read_invoices',native_payment:'can_read_native_payments'};
const DOCTYPES={project:'Chantier',quotation:'Quotation',order:'Sales Order',study:'Chantier Technical Study',delivery:'Bordereau Special',payment:'Reglement Special',native_delivery:'Delivery Note',invoice:'Sales Invoice',native_payment:'Payment Entry'};
const labels={Draft:'Brouillon',Submitted:'Validé',Cancelled:'Annulé',Accepted:'Accepté',Open:'Ouvert',Closed:'Clôturé','To Deliver and Bill':'À livrer et facturer','To Bill':'À facturer','To Deliver':'À livrer',Completed:'Terminée',Lost:'Perdu',Ordered:'Commandé','Partially Ordered':'Partiellement commandé'};

export function commercialStatus(node={}) {
 if(node.docstatus===2)return 'Annulé';
 return labels[node.status]||node.status||(node.docstatus===1?'Validé':'Brouillon');
}
export function commercialKindLabel(kind){return ({project:'Chantier',quotation:'Devis',order:'Commande',study:'Fiche technique',delivery:'Bordereau spécial',payment:'Règlement spécial',native_delivery:'Bon de livraison',invoice:'Facture',native_payment:'Encaissement ERPNext'})[kind]||'Document';}
export function nodeCanOpen(node,capabilities={}) {
 if(!node||node.can_open===false)return false;
 const kind=node.kind||Object.keys(DOCTYPES).find(key=>DOCTYPES[key]===node.doctype);
 return Boolean(capabilities[CAPABILITY[kind]]);
}
export function commercialRouteFor(node){
 if(!node?.name)return null;
 if(node.kind==='project'||node.doctype==='Chantier')return ['chantiers',node.name];
 if(node.kind==='study'||node.doctype==='Chantier Technical Study')return ['technical-study',node.name];
 const doctype=node.doctype||DOCTYPES[node.kind];
 return doctype?['Form',doctype,node.name]:null;
}
export function formatCommercialAmount(amount,currency){
 if(amount===null||amount===undefined||amount==='')return '—';
 const numeric=Number(amount);if(!Number.isFinite(numeric))return '—';
 const code=String(currency||'');
 let decimals=['XOF','XAF','JPY','KRW'].includes(code)?0:2;
 try{return new Intl.NumberFormat('fr-FR',{minimumFractionDigits:decimals,maximumFractionDigits:decimals}).format(numeric)+(code?' '+code:'');}
 catch{return String(numeric)+(code?' '+code:'');}
}
export function periodRange(period,today=new Date().toISOString().slice(0,10)){
 const date=new Date(String(today).slice(0,10)+'T12:00:00Z');
 if(!Number.isFinite(date.getTime())||period==='all'||period==='custom')return {from_date:'',to_date:''};
 const iso=value=>value.toISOString().slice(0,10);
 let start=new Date(date),end=new Date(date);
 if(period==='today')return {from_date:iso(date),to_date:iso(date)};
 if(period==='month'){start.setUTCDate(1);end=new Date(Date.UTC(date.getUTCFullYear(),date.getUTCMonth()+1,0,12));}
 else if(period==='year'){start=new Date(Date.UTC(date.getUTCFullYear(),0,1,12));end=new Date(Date.UTC(date.getUTCFullYear(),11,31,12));}
 else if(period==='30days')start.setUTCDate(start.getUTCDate()-29);
 else return {from_date:'',to_date:''};
 return {from_date:iso(start),to_date:iso(end)};
}
export function connectedPath(id,edges=[]){
 const result=new Set(id?[id]:[]);if(!id)return result;
 for(const direction of ['source','target']){
  const other=direction==='source'?'target':'source',queue=[id];
  for(let cursor=0;cursor<queue.length;cursor++)for(const edge of edges){
   if(edge[direction]!==queue[cursor]||result.has(edge[other]))continue;
   result.add(edge[other]);queue.push(edge[other]);
  }
 }
 return result;
}

export function buildCommercialLayout(documents=[],inputEdges=[],options={}){
 const documentsById=new Map();
 for(const document of documents)if(document?.id&&GRAPH_KINDS.has(document.kind)&&!documentsById.has(document.id))documentsById.set(document.id,document);
 const edges=[],edgeKeys=new Set();
 for(const edge of inputEdges){
  if(!documentsById.has(edge.source)||!documentsById.has(edge.target)||edge.source===edge.target)continue;
  const key=[edge.source,edge.target,edge.kind||'',edge.currency||''].join('|');if(edgeKeys.has(key))continue;
  edgeKeys.add(key);edges.push({...edge,id:edge.id||key});
 }
 const incoming=new Map(),outgoing=new Map();
 for(const id of documentsById.keys()){incoming.set(id,[]);outgoing.set(id,[]);}
 for(const edge of edges){outgoing.get(edge.source).push(edge.target);incoming.get(edge.target).push(edge.source);}
 const collapsed=options.collapsed instanceof Set?options.collapsed:new Set(options.collapsed||[]);
 const visible=new Set(),queue=[...documentsById.keys()].filter(id=>!incoming.get(id).length);
 // Corrupt cyclic data must not make every document disappear.
 if(!queue.length&&documentsById.size)queue.push(documentsById.keys().next().value);
 for(let cursor=0;cursor<queue.length;cursor++){
  const id=queue[cursor];if(visible.has(id))continue;visible.add(id);
  if(!collapsed.has(id))queue.push(...outgoing.get(id));
 }
 const nodes=new Map([...visible].map(id=>[id,{...documentsById.get(id),width:CARD_WIDTH,height:documentsById.get(id).kind==='study'?70:CARD_HEIGHT,column:COLUMNS.get(documentsById.get(id).kind)??2}]));
 const stable=(a,b)=>String(a.creation||a.posting_date||'').localeCompare(String(b.creation||b.posting_date||''))||String(a.name||a.id).localeCompare(String(b.name||b.id));
 const ofKind=kind=>[...nodes.values()].filter(node=>node.kind===kind).sort(stable);
 const parents=id=>(incoming.get(id)||[]).map(parent=>nodes.get(parent)).filter(Boolean);
 const children=id=>(outgoing.get(id)||[]).map(child=>nodes.get(child)).filter(Boolean);
 const placed=new Set();let nextY=38;
 for(const order of ofKind('order')){
  const deliveries=children(order.id).filter(node=>node.kind==='delivery').sort(stable);
  const studies=children(order.id).filter(node=>node.kind==='study').sort(stable);
  const deliverySpan=Math.max(1,deliveries.length)*(CARD_HEIGHT+GAP);
  order.y=nextY+(deliverySpan-CARD_HEIGHT)/2;placed.add(order.id);
  deliveries.forEach((node,index)=>{if(!placed.has(node.id)){node.y=nextY+index*(CARD_HEIGHT+GAP);placed.add(node.id);}});
  studies.forEach((node,index)=>{node.y=order.y+CARD_HEIGHT+22+index*85;node.column=2;placed.add(node.id);});
  nextY+=Math.max(deliverySpan,order.y-nextY+CARD_HEIGHT+(studies.length?studies.length*85+28:0))+64;
 }
 // Upstream cards sit at the average height of their visible child documents.
 for(const kind of ['quotation','project']){
  let floor=38;
  for(const node of ofKind(kind)){
   const attached=children(node.id).filter(child=>placed.has(child.id));
   const target=attached.length?attached.reduce((sum,child)=>sum+child.y,0)/attached.length:nextY;
   node.y=Math.max(floor,target);placed.add(node.id);floor=node.y+CARD_HEIGHT+GAP;
   if(!attached.length)nextY=node.y+CARD_HEIGHT+64;
  }
 }
 for(const kind of ['delivery','payment','study']){
  let floor=38;
  for(const node of ofKind(kind)){
   if(placed.has(node.id)){floor=Math.max(floor,node.y+node.height+GAP);continue;}
   const attached=parents(node.id).filter(parent=>placed.has(parent.id));
   node.y=Math.max(floor,attached.length?attached.reduce((sum,parent)=>sum+parent.y,0)/attached.length:38);
   placed.add(node.id);floor=node.y+node.height+GAP;
  }
 }
 for(const node of nodes.values()){
  node.x=MARGIN+node.column*STRIDE+(node.kind==='study'?28:0);
  node.y??=38;
  node.has_children=Boolean(outgoing.get(node.id)?.length);
  node.collapsed=collapsed.has(node.id);
  const descendants=new Set(),pending=[...(outgoing.get(node.id)||[])];
  for(let i=0;i<pending.length;i++){const id=pending[i];if(descendants.has(id)||id===node.id)continue;descendants.add(id);pending.push(...(outgoing.get(id)||[]));}
  node.hidden_count=[...descendants].filter(id=>!visible.has(id)).length;
 }
 function visibleAncestor(id){
  const visited=new Set(),pending=[id];
  for(let cursor=0;cursor<pending.length;cursor++){
   const current=pending[cursor];if(visited.has(current))continue;visited.add(current);
   if(nodes.has(current))return nodes.get(current);
   pending.push(...(incoming.get(current)||[]));
  }
  return null;
 }
 const connections=[],connectionsByKey=new Map();
 for(const edge of edges){
  if(!nodes.has(edge.target))continue;
  const from=visibleAncestor(edge.source),to=nodes.get(edge.target);if(!from||from.id===to.id)continue;
  const key=[from.id,to.id,edge.kind||'',edge.currency||''].join('|');
  const previous=connectionsByKey.get(key);
  if(previous){
   previous.amount=previous.amount!==null&&previous.amount!==undefined&&edge.amount!==null&&edge.amount!==undefined?Number(previous.amount)+Number(edge.amount):null;
   previous.source_ids.push(edge.source);
   continue;
  }
  const fromX=from.x+from.width,fromY=from.y+from.height/2,toX=to.x,toY=to.y+to.height/2;
  const elbow=Math.min(toX-18,fromX+26+(Math.abs(fromY-toY)>10?12:0));
  const path=to.column===from.column?`M ${from.x+30} ${from.y+from.height} V ${toY} H ${toX}`:`M ${fromX} ${fromY} H ${elbow} V ${toY} H ${toX}`;
  const connection={...edge,from,to,path,proxy:from.id!==edge.source,source_ids:[edge.source],label_x:fromX+12,label_y:fromY-10};
  connections.push(connection);connectionsByKey.set(key,connection);
 }
 return {nodes:[...nodes.values()],edges:connections,width:5*STRIDE+MARGIN,height:Math.max(610,...[...nodes.values()].map(node=>node.y+node.height+50)),card_width:CARD_WIDTH,column_stride:STRIDE};
}
