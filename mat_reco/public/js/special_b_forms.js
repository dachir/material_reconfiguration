/* Native Frappe forms: stock and financial validation remain server-side. */
(() => {
 if(window.__ug_special_b_forms_loaded)return;
 window.__ug_special_b_forms_loaded=true;
 const api='mat_reco.material_reconfiguration.services.special_b.';
 const openDoc = async data => {await frappe.model.with_doctype(data.doctype);const doc=frappe.model.sync(data)[0];frappe.set_route('Form',doc.doctype,doc.name);};
 const query = (frm,bOnly=false) => {
  frm.set_query('sales_order',()=>({filters:{docstatus:1,...(bOnly?{custom_ug_order_type:'B'}:{}),...(frm.doc.customer?{customer:frm.doc.customer}:{}),...(frm.doc.company?{company:frm.doc.company}:{})}}));
 };
 const deliveryLabels = frm => frm.set_df_property('grand_total','label',__(frm.doc.order_type==='A'?'Montant du BL TTC':'Montant du BL HT'));
 async function loadDelivery(frm){
  const r=await frappe.call({method:api+'make_delivery',args:{sales_order:frm.doc.sales_order}});
  for(const field of ['company','customer','currency','order_type','warehouse','net_total','tax_amount','grand_total'])await frm.set_value(field,r.message[field]);
  frm.clear_table('items');for(const row of r.message.items||[]){const values={...row};for(const key of ['name','parent','parenttype','parentfield','doctype','docstatus','idx','__islocal','__unsaved','owner','creation','modified','modified_by'])delete values[key];frm.add_child('items',values);}frm.refresh_field('items');
 }
 frappe.ui.form.on('Bordereau Special',{
  setup(frm){query(frm);frm.fields_dict.items.grid.cannot_add_rows=true;frm.set_query('warehouse',()=>({filters:{company:frm.doc.company,is_group:0}}));frm.set_query('warehouse','items',()=>({filters:{company:frm.doc.company,is_group:0}}));},
  async sales_order(frm){
   if(!frm.is_new()||!frm.doc.sales_order||frm.doc.items?.length)return;
   await loadDelivery(frm);
  },
  order_type:deliveryLabels,
  refresh(frm){
   deliveryLabels(frm);
   if(frm.doc.docstatus===0&&frm.doc.sales_order&&!frm.doc.adopt_existing_stock)frm.add_custom_button(__('Recharger les articles'),()=>frappe.confirm(__('Remplacer les lignes par les quantités restant à livrer ? Les choix de séries et de quantités seront réinitialisés.'),()=>loadDelivery(frm)));
   if(frm.doc.docstatus===1){
    if(frappe.model.can_create('Reglement Special'))frm.add_custom_button(__('Recevoir un règlement'),async()=>{const r=await frappe.call({method:api+'make_payment',args:{bordereau:frm.doc.name}});openDoc(r.message);});
    if(frm.doc.stock_entry)frm.add_custom_button(__('Sortie de stock'),()=>frappe.set_route('Form','Stock Entry',frm.doc.stock_entry));
   }
   if(frm.doc.sales_order)frm.add_custom_button(__('Commande client'),()=>frappe.set_route('Form','Sales Order',frm.doc.sales_order));
  }
 });
 frappe.ui.form.on('Reglement Special',{
  setup(frm){query(frm);frm.set_query('bordereau','allocations',()=>({filters:{docstatus:1,company:frm.doc.company,customer:frm.doc.customer,currency:frm.doc.currency}}));},
  refresh(frm){if(frm.doc.docstatus===1)frm.dashboard.set_headline_alert(__(frm.doc.order_type==='B'?'Les affectations peuvent être ajustées puis mises à jour. Le montant encaissé est compté une seule fois.':'Les affectations mettent à jour le lettrage de l’encaissement ERPNext pour les factures concernées. Le montant encaissé est compté une seule fois.'));},
  async sales_order(frm){if(!frm.is_new()||!frm.doc.sales_order)return;const r=await frappe.call({method:api+'make_payment',args:{sales_order:frm.doc.sales_order}});for(const field of ['company','customer','currency','order_type'])await frm.set_value(field,r.message[field]);}
 });
 frappe.ui.form.on('Solde Initial Client B',{setup:frm=>query(frm,true)});
frappe.ui.form.on('Bordereau Special',{
 refresh(frm){
  if(frm.doc.docstatus!==0||!frm.doc.sales_order)return;
  frm.add_custom_button(__('Dimensions de stock'),async()=>{
   const r=await frappe.call({method:api+'get_delivery_data',args:{sales_order:frm.doc.sales_order}});
   const values=JSON.parse(frm.doc.accounting_dimensions_json||'{}');
   const fields=(r.message.dimensions||[]).map(f=>({...f,default:values[f.fieldname]||f.default}));
   if(!fields.length){frappe.msgprint(__('Aucune dimension de stock supplémentaire requise.'));return;}
   frappe.prompt(fields,v=>frm.set_value('accounting_dimensions_json',JSON.stringify(v)),__('Dimensions de stock'),__('Appliquer'));
  });
 }
});

})();
