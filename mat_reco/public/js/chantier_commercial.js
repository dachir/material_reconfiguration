for (const doctype of ['Quotation','Sales Order']) {
 frappe.ui.form.on(doctype, {
  setup(frm) {
   frm.set_query('custom_chantier',()=>({filters:{company:frm.doc.company,customer:frm.doc.customer||frm.doc.party_name}}));
   frm.set_query('custom_chantier_section','items',()=>({filters:{chantier:frm.doc.custom_chantier||'__none__'}}));
  },
  refresh(frm) {
   if(frm.doc.custom_chantier)frm.add_custom_button(__('Chantier'),()=>{sessionStorage.setItem('univers-chantier-selected',frm.doc.custom_chantier);frappe.set_route('chantiers');});
   if(doctype==='Sales Order' && frm.doc.docstatus===1 && frm.doc.custom_chantier)frm.add_custom_button(__('Préparer MPP'),()=>{
    const rows=frm.doc.items.filter(r=>r.custom_technical_snapshot);
    const dialog=new frappe.ui.Dialog({title:__('Ligne à planifier'),fields:[{fieldname:'row',label:__('Ouvrage'),fieldtype:'Select',options:rows.map(r=>({value:r.name,label:`${r.custom_repere} · ${r.item_code} · ${r.qty}`})),reqd:1}],primary_action_label:__('Préparer MPP'),async primary_action(values){dialog.disable_primary_action();try{const result=await frappe.call({method:'mat_reco.material_reconfiguration.services.chantier_service.create_mpp',args:{sales_order:frm.doc.name,sales_order_item:values.row}});dialog.hide();frappe.set_route('Form','Material Production Plan',result.message);}finally{dialog.enable_primary_action();}}});dialog.show();
   });
  }
 });
}
