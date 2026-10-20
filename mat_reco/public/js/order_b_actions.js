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
