/* Circuit B actions stay on the native Sales Order form. */
frappe.ui.form.on('Sales Order', {
 refresh(frm) {
  if(frm.doc.custom_ug_order_type!=='B'||frm.doc.docstatus!==1)return;
  for(const label of ['Delivery Note','Sales Invoice','Payment'])frm.remove_custom_button(__(label),__('Create'));
  const api='mat_reco.material_reconfiguration.services.';
  frm.add_custom_button(__(frm.doc.custom_ug_b_export_file?'Télécharger export B':'Exporter pour Sage'),async()=>{
   const result=await frappe.call({method:api+'order_b_export.export_order',args:{sales_order:frm.doc.name},type:'POST'});
   await frm.reload_doc();window.open(result.message.file_url,'_blank','noopener,noreferrer');
  });
  if(frm.doc.custom_ug_b_export_file&&!frm.doc.custom_ug_b_sage_reference)frm.add_custom_button(__('Confirmer import Sage'),()=>frappe.prompt([{fieldname:'reference',fieldtype:'Data',label:__('Référence du document dans Sage'),reqd:1}],async(v)=>{
   await frappe.call({method:api+'order_b_export.confirm_import',args:{sales_order:frm.doc.name,sage_reference:v.reference},type:'POST'});await frm.reload_doc();
  },__('Confirmer import Sage'),__('Confirmer')));
 }
});

frappe.ui.form.on('Sales Order',{
 refresh(frm){
  if(frm.doc.custom_ug_order_type!=='B'||frm.doc.docstatus!==1)return;
  const api='mat_reco.material_reconfiguration.services.special_b.';
  const create=async(method,args)=>{const r=await frappe.call({method:api+method,args});await frappe.model.with_doctype(r.message.doctype);const doc=frappe.model.sync(r.message)[0];frappe.set_route('Form',doc.doctype,doc.name);};
  frm.add_custom_button(__('Bordereau Spécial'),()=>create('make_delivery',{sales_order:frm.doc.name}),__('Create'));
  frm.add_custom_button(__('Règlement Spécial'),()=>create('make_payment',{sales_order:frm.doc.name}),__('Create'));
  frm.add_custom_button(__('Situation client B'),()=>frappe.set_route('query-report','Situation des comptes clients B',{company:frm.doc.company,customer:frm.doc.customer,currency:frm.doc.currency}));
  frm.add_custom_button(__('Livraisons et règlements B'),async()=>{
   const r=await frappe.call({method:api+'get_order_summary',args:{sales_order:frm.doc.name}});const data=r.message,esc=frappe.utils.escape_html;
   const dialog=new frappe.ui.Dialog({title:__('Suivi de la commande B'),size:'extra-large',fields:[{fieldtype:'HTML',fieldname:'overview'}]});
   const link=(dt,name)=>`<a href="/app/${frappe.router.slug(dt)}/${encodeURIComponent(name)}">${esc(name)}</a>`;
   const table=(headers,rows)=>`<table class="table table-bordered"><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(cell=>`<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
   const money=n=>format_currency(n,data.currency);
   dialog.fields_dict.overview.$wrapper.html(`<p>BL validés : ${money(data.delivery_amount)} · Règlements B : ${money(data.received)} · Solde commande : <b>${money(data.balance)}</b></p>`+
    table(['Article','Commandées','Livrées','Restantes','Unité'],data.items.map(i=>[esc(i.item_name),i.ordered_qty,i.delivered_qty,i.remaining_qty,esc(i.uom)]))+
    table(['BL','Date','État','Montant','Affecté','Solde','Sortie'],data.deliveries.map(i=>[link('Bordereau Special',i.name),esc(i.posting_date),i.docstatus===1?'Validé':i.docstatus===2?'Annulé':'Brouillon',money(i.grand_total),money(i.received),money(i.balance),i.stock_entry?link('Stock Entry',i.stock_entry):'']))+
    table(['Règlement','Date','Montant commande','Montant non affecté'],data.payments.map(i=>[link('Reglement Special',i.name),esc(i.posting_date),money(i.amount),money(i.unallocated_amount)])));
   dialog.show();
  });
 }
});

frappe.ui.form.on('Sales Order',{
 refresh(frm){
  if(frm.doc.custom_ug_order_type!=='B'||frm.doc.docstatus!==1)return;
  frm.add_custom_button(__('Reprendre une sortie B existante'),()=>frappe.prompt([
   {fieldname:'stock_entry',label:__('Sortie de stock B'),fieldtype:'Link',options:'Stock Entry',reqd:1,
    get_query:()=>({filters:{docstatus:1,custom_ug_b_sales_order:frm.doc.name,custom_ug_special_delivery:['is','not set']}})}
  ],async values=>{
   const r=await frappe.call({method:'mat_reco.material_reconfiguration.services.special_b.make_from_issue',args:values,type:'POST'});
   frappe.set_route('Form','Bordereau Special',r.message);
  },__('Reprendre sans nouvelle sortie de stock'),__('Préparer le bordereau')),__('Create'));
 }
});
