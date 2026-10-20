// Draft inheritance is immediate; the server recalculates and validates on save.
export function inheritTypeExtras(chantier, catalogue = []) {
 const types=new Map((chantier.work_types||[]).map(t=>[t.type_id,t]));
 const items=new Map(catalogue.map(i=>[i.name,i]));
 const current=chantier.commercial_extras||[];
 const kept=current.filter(e=>!e.inherited_from);
 for(const line of chantier.lines||[]){
  if(line.line_kind==='Vente directe')continue;
  const type=types.get(line.work_type);if(!type)continue;
  for(const definition of JSON.parse(type.common_extras||'[]')){
   const prior=current.find(e=>e.parent_line_id===line.line_id&&e.inherited_from===type.type_id&&e.inherited_key===definition.key);
   const item=items.get(definition.item_code)||{};
   const basis=item.basis||definition.basis||prior?.calculation_basis||'MANUEL';
   const count=Number(line.qty||0),length=Number(line.length_mm||0),width=Number(line.width_mm||0);
   const quantity={SURFACE:length*width/1e6*count,PERIMETRE:2*(length+width)/1000*count,PIECE:count,FIXE:Number(item.custom_service_fixed_qty||definition.fixed_qty||1),MANUEL:Number(definition.qty||1)*count}[basis]??0;
   kept.push({...prior,line_id:prior?.line_id||`type-extra:${line.line_id}:${definition.key}`,parent_line_id:line.line_id,item_code:definition.item_code,
    item_name:item.item_name||definition.item_name||prior?.item_name||definition.item_code,item_type:item.custom_item_types||definition.item_type||prior?.item_type,
    uom:item.stock_uom||definition.uom||prior?.uom,calculation_basis:basis,manual_qty:1,rate_set:1,
    inherited_from:type.type_id,inherited_key:definition.key,
    qty:prior?.inherited_qty_override?prior.qty:quantity*Number(definition.factor||1),rate:prior?.inherited_rate_override?prior.rate:Number(definition.rate||0)});
  }
 }
 chantier.commercial_extras=kept;
}
