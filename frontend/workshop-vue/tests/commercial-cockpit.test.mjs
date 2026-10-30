import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
 buildCommercialLayout, commercialRouteFor, nodeCanOpen,
 formatCommercialAmount, periodRange, connectedPath,
} from '../src/commercial-layout.js';

const doc=(kind,name,extra={})=>({id:`${kind}:${name}`,kind,name,...extra});
const relation=(source,target,kind='source',extra={})=>({source:source.id,target:target.id,kind,...extra});
const chain=()=>{
 const project=doc('project','C-1');
 const quotation=doc('quotation','Q-1');
 const order=doc('order','SO-1',{order_type:'A'});
 const study=doc('study','FT-1');
 const delivery=doc('delivery','BL-1',{order_type:'A'});
 const payment=doc('payment','R-1',{order_type:'A'});
 return {project,quotation,order,study,delivery,payment,
  documents:[project,quotation,order,study,delivery,payment],
  edges:[relation(project,quotation),relation(quotation,order),relation(order,study),
   relation(order,delivery),relation(delivery,payment,'allocation',{amount:12500,currency:'XOF'})]};
};

test('commercial graph keeps one card per document and omits native accounting cards',()=>{
 const fixture=chain();
 const invoice=doc('invoice','INV-1');
 const nativeDelivery=doc('native_delivery','DN-1');
 const nativePayment=doc('native_payment','PE-1');
 const scene=buildCommercialLayout([...fixture.documents,fixture.order,invoice,nativeDelivery,nativePayment],
  [...fixture.edges,relation(fixture.order,invoice),relation(fixture.order,fixture.order)]);
 assert.equal(scene.nodes.length,6);
 assert.equal(new Set(scene.nodes.map(node=>node.id)).size,6);
 assert(scene.nodes.every(node=>!['invoice','native_delivery','native_payment'].includes(node.kind)));
 assert.equal(scene.edges.length,5);
 const byKind=Object.fromEntries(scene.nodes.map(node=>[node.kind,node]));
 assert(byKind.project.x<byKind.quotation.x);
 assert(byKind.quotation.x<byKind.order.x);
 assert(byKind.order.x<byKind.delivery.x);
 assert(byKind.delivery.x<byKind.payment.x);
 assert.equal(byKind.study.column,byKind.order.column);
 assert(byKind.study.y>=byKind.order.y+byKind.order.height);
 assert(scene.nodes.every(node=>Number.isFinite(node.x)&&Number.isFinite(node.y)));
});

test('a mixed payment is one shared document linked to both A and B allocations',()=>{
 const a=doc('order','A',{order_type:'A'}),b=doc('order','B',{order_type:'B'});
 const da=doc('delivery','DA',{order_type:'A'}),db=doc('delivery','DB',{order_type:'B'});
 const mixed=doc('payment','MIX',{order_type:'Mixte',currency:'XOF',amount:300});
 const edges=[relation(a,da),relation(b,db),
  relation(da,mixed,'allocation',{amount:100,currency:'XOF'}),
  relation(db,mixed,'allocation',{amount:200,currency:'XOF'})];
 const scene=buildCommercialLayout([a,b,da,db,mixed,{...mixed}], [...edges,edges[2]]);
 assert.equal(scene.nodes.filter(node=>node.id===mixed.id).length,1);
 const allocations=scene.edges.filter(edge=>edge.kind==='allocation');
 assert.equal(allocations.length,2);
 assert.deepEqual(allocations.map(edge=>[edge.amount,edge.currency]),[[100,'XOF'],[200,'XOF']]);
 assert(allocations.every(edge=>edge.to.id===mixed.id));
});

test('collapsing A keeps a mixed payment reachable through B and its A proxy link',()=>{
 const a=doc('order','A'),b=doc('order','B');
 const da=doc('delivery','DA'),db=doc('delivery','DB');
 const mixed=doc('payment','MIX');
 const scene=buildCommercialLayout([a,b,da,db,mixed],[relation(a,da),relation(b,db),
  relation(da,mixed,'allocation',{amount:100,currency:'XOF'}),
  relation(db,mixed,'allocation',{amount:200,currency:'XOF'})],{collapsed:new Set([a.id])});
 const visible=new Set(scene.nodes.map(node=>node.id));
 assert(!visible.has(da.id));
 assert(visible.has(db.id)&&visible.has(mixed.id));
 const proxy=scene.edges.find(edge=>edge.to.id===mixed.id&&edge.from.id===a.id);
 assert(proxy?.proxy);
 assert.equal(proxy.amount,100);
 assert(scene.edges.some(edge=>edge.from.id===db.id&&edge.to.id===mixed.id&&!edge.proxy));
 assert(scene.nodes.find(node=>node.id===a.id).hidden_count>=1);
});

test('independent draft projects and standalone advances remain visible',()=>{
 const draft=doc('project','DRAFT',{docstatus:0});
 const advance=doc('payment','ADVANCE',{amount:50,currency:'EUR'});
 const scene=buildCommercialLayout([draft,advance],[]);
 assert.deepEqual(new Set(scene.nodes.map(node=>node.id)),new Set([draft.id,advance.id]));
 assert.equal(scene.edges.length,0);
 assert(scene.height>Math.max(...scene.nodes.map(node=>node.y+node.height)));
});

test('technical and project cards open the Vue pages and native forms use the correct doctype',()=>{
 assert.deepEqual(commercialRouteFor(doc('project','C-1')),['chantiers','C-1']);
 assert.deepEqual(commercialRouteFor(doc('study','FT-1')),['technical-study','FT-1']);
 assert.deepEqual(commercialRouteFor(doc('order','SO-1')),['Form','Sales Order','SO-1']);
 assert.deepEqual(commercialRouteFor(doc('delivery','BL-1')),['Form','Bordereau Special','BL-1']);
 assert.deepEqual(commercialRouteFor(doc('payment','R-1')),['Form','Reglement Special','R-1']);
 assert.equal(commercialRouteFor({kind:'study'}),null);
});

test('each card opening obeys its own document capability and an explicit denial',()=>{
 const delivery=doc('delivery','BL-1'),payment=doc('payment','R-1');
 assert(nodeCanOpen(delivery,{can_read_deliveries:true}));
 assert(!nodeCanOpen(payment,{can_read_deliveries:true}));
 assert(!nodeCanOpen(delivery,{can_read_payments:true}));
 assert(!nodeCanOpen({...delivery,can_open:false},{can_read_deliveries:true}));
 assert(!nodeCanOpen(doc('order','B'),{can_read_deliveries:true}));
 assert(nodeCanOpen({doctype:'Chantier Technical Study',name:'FT-1'},{can_read_studies:true}));
 assert(!nodeCanOpen(delivery));
 assert(!nodeCanOpen(null,{can_read_deliveries:true}));
});

test('amounts retain their currency and unknown values are never displayed as zero',()=>{
 const cfa=formatCommercialAmount(1234.75,'XOF');
 const euro=formatCommercialAmount(1234.75,'EUR');
 assert.match(cfa,/XOF$/);
 assert(!cfa.includes(','));
 assert.match(euro,/,75 EUR$/);
 assert.equal(formatCommercialAmount(null,'XOF'),'—');
 assert.equal(formatCommercialAmount(undefined,'EUR'),'—');
 assert.equal(formatCommercialAmount('not-a-number','EUR'),'—');
 assert.match(formatCommercialAmount(0,'XOF'),/^0 XOF$/);
 const documents=[doc('order','CFA',{amount:100,currency:'XOF'}),doc('order','EUR',{amount:100,currency:'EUR'})];
 const scene=buildCommercialLayout(documents,[]);
 assert.deepEqual(scene.nodes.map(node=>[node.amount,node.currency]),[[100,'XOF'],[100,'EUR']]);
});

test('period filters use inclusive calendar ranges including leap years',()=>{
 assert.deepEqual(periodRange('today','2026-10-30'),{from_date:'2026-10-30',to_date:'2026-10-30'});
 assert.deepEqual(periodRange('30days','2026-10-30'),{from_date:'2026-10-01',to_date:'2026-10-30'});
 assert.deepEqual(periodRange('month','2024-02-10'),{from_date:'2024-02-01',to_date:'2024-02-29'});
 assert.deepEqual(periodRange('year','2026-10-30'),{from_date:'2026-01-01',to_date:'2026-12-31'});
 assert.deepEqual(periodRange('all','2026-10-30'),{from_date:'',to_date:''});
 assert.deepEqual(periodRange('custom','2026-10-30'),{from_date:'',to_date:''});
 assert.deepEqual(periodRange('month','invalid-date'),{from_date:'',to_date:''});
});

test('selection highlights only ancestors and descendants, without sibling branches',()=>{
 const fixture=chain();
 const sibling=doc('order','SO-2');
 const siblingDelivery=doc('delivery','BL-2');
 const edges=[...fixture.edges,relation(fixture.quotation,sibling),relation(sibling,siblingDelivery)];
 const selected=connectedPath(fixture.order.id,edges);
 assert.deepEqual(selected,new Set(fixture.documents.map(node=>node.id)));
 assert(!selected.has(sibling.id)&&!selected.has(siblingDelivery.id));
 assert.equal(connectedPath('',edges).size,0);
});

test('shared payment selection reaches both source orders and cyclic data terminates',()=>{
 const a=doc('order','A'),b=doc('order','B'),p=doc('payment','P');
 const edges=[relation(a,p,'allocation'),relation(b,p,'allocation')];
 assert.deepEqual(connectedPath(p.id,edges),new Set([a.id,b.id,p.id]));
 const cyclic=[relation(a,b),relation(b,a)];
 assert.deepEqual(connectedPath(a.id,cyclic),new Set([a.id,b.id]));
 assert.equal(buildCommercialLayout([a,b],cyclic).nodes.length,2);
});

test('several collapsed A deliveries keep their full allocation total on one shared payment proxy',()=>{
 const a=doc('order','A'),b=doc('order','B');
 const da1=doc('delivery','DA-1'),da2=doc('delivery','DA-2'),db=doc('delivery','DB');
 const mixed=doc('payment','MIX',{order_type:'Mixte',currency:'XOF',amount:300});
 const scene=buildCommercialLayout([a,b,da1,da2,db,mixed],
  [relation(a,da1),relation(a,da2),relation(b,db),
   relation(da1,mixed,'allocation',{amount:100,currency:'XOF'}),
   relation(da2,mixed,'allocation',{amount:50,currency:'XOF'}),
   relation(db,mixed,'allocation',{amount:150,currency:'XOF'})],{collapsed:new Set([a.id])});
 assert.equal(scene.nodes.filter(node=>node.id===mixed.id).length,1);
 assert(!scene.nodes.some(node=>node.id===da1.id||node.id===da2.id));
 const proxies=scene.edges.filter(edge=>edge.from.id===a.id&&edge.to.id===mixed.id);
 assert.equal(proxies.length,1);
 assert.equal(proxies[0].amount,150);
 assert.equal(proxies[0].currency,'XOF');
 assert(proxies[0].proxy);
 assert(scene.edges.some(edge=>edge.from.id===db.id&&edge.to.id===mixed.id&&edge.amount===150));
});

test('collapsed allocation links never add different currencies together',()=>{
 const a=doc('order','A'),b=doc('order','B');
 const da1=doc('delivery','DA-1'),da2=doc('delivery','DA-2'),db=doc('delivery','DB');
 const shared=doc('payment','SHARED');
 const scene=buildCommercialLayout([a,b,da1,da2,db,shared],
  [relation(a,da1),relation(a,da2),relation(b,db),
   relation(da1,shared,'allocation',{amount:100,currency:'XOF'}),
   relation(da2,shared,'allocation',{amount:50,currency:'EUR'}),
   relation(db,shared,'allocation',{amount:25,currency:'XOF'})],{collapsed:new Set([a.id])});
 const proxies=scene.edges.filter(edge=>edge.from.id===a.id&&edge.to.id===shared.id);
 assert.equal(proxies.length,2);
 assert.deepEqual(proxies.map(edge=>[edge.currency,edge.amount]).sort(),[['EUR',50],['XOF',100]]);
});
