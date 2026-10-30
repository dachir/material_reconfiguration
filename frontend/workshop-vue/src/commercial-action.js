// Local editor state only. The server owns permissions, workflow, stock and final amounts.
const EPSILON=1e-6;
const number=value=>value!==''&&value!==null&&value!==undefined&&Number.isFinite(Number(value))?Number(value):null;
const clone=value=>JSON.parse(JSON.stringify(value));
export function actionIsPayment(preparation={}){return preparation.target_doctype==='Reglement Special'||preparation.action==='payment';}
export function actionRequestKey(){return globalThis.crypto?.randomUUID?.()||'commercial-'+Date.now()+'-'+Math.random().toString(16).slice(2);}
export function normaliseActionRows(rows=[],payment=false,{deriveChildren=true}={}){
 const result=rows.map(row=>({...clone(row),id:String(row.id),selected:row.selected===undefined?!payment:Boolean(row.selected),qty:row.qty??row.remaining_qty??0,amount:row.amount??(payment&&row.selected?(row.remaining_amount??row.balance??0):0),warehouse:row.warehouse||'',serial_no:Array.isArray(row.serial_no)?row.serial_no.join('\n'):row.serial_no||'',batch_no:row.batch_no||'',_initial_qty:number(row.qty)??number(row.remaining_qty)??0,_initial_amount:number(row.amount)}));
 const index=new Map(result.map(row=>[row.id,row]));
 for(const row of result){
  const parent=index.get(String(row.parent_id||''));
  if(!parent)continue;
  row._parent_id=parent.id;
  row._derived=Boolean(deriveChildren&&!payment);
  row._ratio=number(row.ratio)??(number(parent.ordered_qty)>0&&number(row.ordered_qty)!==null?Number(row.ordered_qty)/Number(parent.ordered_qty):parent._initial_qty?row._initial_qty/parent._initial_qty:0);
 }
 if(!payment&&deriveChildren)for(const row of result.filter(row=>!row._derived))synchroniseActionChildren(result,row.id);
 // Keep supplements immediately after their parent without dropping detached rows.
 const ordered=[],seen=new Set();
 function add(row){if(seen.has(row.id))return;seen.add(row.id);ordered.push(row);for(const child of result)if(child._parent_id===row.id)add(child);}
 result.filter(row=>!row._parent_id).forEach(add);result.forEach(add);
 return ordered;
}
export function synchroniseActionChildren(rows,id){
 const index=new Map(rows.map(row=>[row.id,row])),visited=new Set(),queue=[String(id)];
 for(let cursor=0;cursor<queue.length;cursor++){
  const parent=index.get(queue[cursor]);if(!parent||visited.has(parent.id))continue;visited.add(parent.id);
  for(const child of rows.filter(row=>row._parent_id===parent.id&&row._derived)){
   child.selected=Boolean(parent.selected);
   child.qty=Math.round((number(parent.qty)??0)*(number(child._ratio)??0)*1e9)/1e9;
   queue.push(child.id);
  }
 }
 return rows;
}
export function selectActionRow(rows,id,selected,payment=false){
 const row=rows.find(value=>value.id===String(id));if(!row||(!payment&&row._derived))return rows;
 row.selected=Boolean(selected);
 if(payment&&row.selected&&!(number(row.amount)>0))row.amount=row.remaining_amount??row.balance??row.remaining_qty??0;
 if(!payment)synchroniseActionChildren(rows,row.id);
 return rows;
}
export function selectAllActionRows(rows,selected,payment=false){
 for(const row of rows){
  if(!payment&&row._derived)continue;
  const available=number(payment?(row.remaining_amount??row.balance??row.remaining_qty):row.remaining_qty);
  selectActionRow(rows,row.id,Boolean(selected)&&(available===null||available>EPSILON),payment);
 }
 return rows;
}
export function updateActionQuantity(rows,id,value){const row=rows.find(row=>row.id===String(id));if(!row||row._derived)return rows;row.qty=value;synchroniseActionChildren(rows,row.id);return rows;}
export function proposeActionSerials(rows,row){
 if(!row.has_serial_no||row._serials_manual)return row;
 const wanted=Number(row.qty)*Number(row.conversion_factor||1);
 if(!Number.isInteger(wanted)||wanted<0)return row;
 const split=value=>(Array.isArray(value)?value:String(value||'').split(/[\n,]+/)).map(value=>String(value).trim()).filter(Boolean);
 const used=new Set(rows.filter(other=>other!==row&&other.selected).flatMap(other=>split(other.serial_no)));
 const supplied=(row.serials||[]).map(serial=>typeof serial==='string'?{name:serial}:serial);
 const compatible=supplied.filter(serial=>(!row.warehouse||!serial.warehouse||serial.warehouse===row.warehouse)&&!used.has(serial.name));
 const names=new Set(compatible.map(serial=>serial.name));
 const prior=split(row.serial_no).filter(name=>!used.has(name)&&(!supplied.length||names.has(name)));
 const pool=[...new Set([...prior,...compatible.map(serial=>serial.name)])];
 row.serial_no=pool.slice(0,wanted).join('\n');
 return row;
}
export function buildActionSelections(rows,payment=false,{target_doctype}={}){
 return rows.filter(row=>row.selected).map(row=>{
  if(payment)return {id:row.id,amount:number(row.amount)};
  const result={id:row.id,qty:number(row.qty)};
  if(target_doctype==='Bordereau Special')Object.assign(result,{warehouse:row.warehouse||'',serial_no:row.serial_no||'',batch_no:row.batch_no||''});
  return result;
 });
}
export function buildActionValues(preparation={},values={}){
 const result={};
 for(const field of preparation.fields||[])if(field.fieldname&&Object.hasOwn(values,field.fieldname))result[field.fieldname]=values[field.fieldname];
 if(preparation.target_doctype==='Bordereau Special'&&values.accounting_dimensions){
  const allowed=new Set((preparation.dimensions||[]).map(field=>field.fieldname));
  result.accounting_dimensions=Object.fromEntries(Object.entries(values.accounting_dimensions).filter(([key])=>allowed.has(key)));
 }
 return result;
}
export function actionLineAmount(row,payment=false){
 if(payment)return number(row.amount);
 const quantity=number(row.qty);if(quantity===null)return null;
 if(row._initial_amount!==null&&row._initial_amount!==undefined&&number(row._initial_qty)>0)return row._initial_amount*quantity/row._initial_qty;
 const rate=number(row.rate);return rate===null?null:rate*quantity;
}
export function actionTotals(rows,values={},payment=false){
 const selected=rows.filter(row=>row.selected),byUnit=new Map(),byCurrency=new Map();
 let allocated=0,amountA=0,amountB=0,unknownAmount=false;
 for(const row of selected){
  const value=actionLineAmount(row,payment),currency=row.currency||values.currency||'';
  if(value===null)unknownAmount=true;else{byCurrency.set(currency,(byCurrency.get(currency)||0)+value);if(payment){allocated+=value;if(row.order_type==='A')amountA+=value;if(row.order_type==='B')amountB+=value;}}
  if(!payment){const unit=row.uom||'';byUnit.set(unit,(byUnit.get(unit)||0)+(number(row.qty)??0));}
 }
 return {count:selected.length,parent_count:selected.filter(row=>!row._derived).length,quantities:[...byUnit].map(([uom,qty])=>({uom,qty})),amounts:[...byCurrency].map(([currency,amount])=>({currency,amount})),allocated,amount_a:amountA,amount_b:amountB,unallocated:(number(values.amount)??0)-allocated,unknown_amount:unknownAmount};
}
export function actionSubmissionButtons(submission={}){
 const result=[];
 if(submission.can_save)result.push({key:'save',intent:'save',label:'Enregistrer le brouillon',primary:false});
 if(submission.can_submit)result.push({key:'submit',intent:'submit',label:'Valider',primary:true});
 for(const item of submission.workflow_actions||[]){
  const entry=typeof item==='string'?{action:item,label:item}:item;
  if(!entry?.action)continue;
  result.push({key:'workflow:'+entry.action,intent:'workflow',workflow_action:entry.action,label:entry.label||entry.action,primary:Number(entry.docstatus)===1,next_state:entry.next_state});
 }
 return result;
}
export function actionFieldFilters(field={},values={}){
 const convert=value=>typeof value==='string'&&value.startsWith('$')?values[value.slice(1)]??'':Array.isArray(value)?value.map(convert):value;
 return Object.fromEntries(Object.entries(field.filters||{}).map(([key,value])=>[key,convert(value)]));
}
export function validateActionEditor(preparation,rows,values={}){
 const payment=actionIsPayment(preparation),errors=[],selected=rows.filter(row=>row.selected);
 if(!payment&&preparation.rows?.length&&!selected.length)errors.push('Sélectionner au moins une ligne.');
 for(const row of selected){
  const label=row.label||row.description||row.item_code||row.id;
  if(payment){
   const amount=number(row.amount),available=number(row.remaining_amount??row.balance??row.remaining_qty);
   if(amount===null||amount<=0)errors.push(label+' : saisir un montant affecté supérieur à zéro.');
   else if(available!==null&&amount>available+EPSILON)errors.push(label+' : le montant dépasse le solde disponible.');
  }else{
   const quantity=number(row.qty),remaining=number(row.remaining_qty);
   if(quantity===null||quantity<=0)errors.push(label+' : saisir une quantité supérieure à zéro.');
   else if(remaining!==null&&quantity>remaining+EPSILON)errors.push(label+' : la quantité dépasse le reste disponible.');
   if(row.must_be_whole_number&&quantity!==null&&!Number.isInteger(quantity))errors.push(label+' : une quantité entière est requise.');
  }
 }
 for(const field of [...(preparation.fields||[]),...(preparation.dimensions||[]).map(field=>({...field,_dimension:true}))]){
  if(!field.reqd||field.hidden||field.read_only||['Section Break','Column Break'].includes(field.fieldtype))continue;
  const value=field._dimension?values.accounting_dimensions?.[field.fieldname]:values[field.fieldname];
  if(value===undefined||value===null||String(value).trim()==='')errors.push('Renseigner '+(field.label||field.fieldname)+'.');
 }
 if(payment){
  const amount=number(values.amount),allocated=actionTotals(rows,values,true).allocated;
  if(amount===null||amount<=0)errors.push('Saisir un montant encaissé supérieur à zéro.');
  else if(allocated>amount+EPSILON)errors.push('Les affectations dépassent le montant encaissé.');
 }
 return [...new Set(errors)];
}
