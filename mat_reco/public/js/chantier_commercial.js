for (const doctype of ['Quotation','Sales Order']) {
 frappe.ui.form.on(doctype, {
  setup(frm) {
   frm.set_query('custom_chantier',()=>({filters:{company:frm.doc.company,customer:frm.doc.customer||frm.doc.party_name}}));
   frm.set_query('custom_chantier_section','items',()=>({filters:{chantier:frm.doc.custom_chantier||'__none__'}}));
  },
  refresh(frm) {
   if(doctype==='Quotation'&&frm.doc.custom_chantier)frm.add_custom_button(__('Chantier'),()=>{sessionStorage.setItem('univers-chantier-selected',frm.doc.custom_chantier);frappe.set_route('chantiers');});

  }
 });
}

frappe.ui.form.on('Sales Order', {
 custom_ug_order_type(frm) {
  if(frm.is_new())frm.set_value('naming_series',frm.doc.custom_ug_order_type==='B'?'SAL-ORD-B-.YYYY.-.#####':'SAL-ORD-.YYYY.-.#####');
 },
 async refresh(frm) {
  frm.set_df_property('custom_ug_order_type','read_only',!frm.is_new());
  frm.set_df_property('naming_series','read_only',true);
  try {
   frm._ug_commercial_permissions ||= frappe.call({method:'mat_reco.material_reconfiguration.services.chantier_service.get_commercial_permissions',type:'GET'}).then(r=>r.message||{});
   const permissions=await frm._ug_commercial_permissions;
   frm.set_df_property('custom_ug_order_type','options',permissions.can_access_b?'A\nB':'A');
  } catch {
   frm._ug_commercial_permissions=null;
   frm.set_df_property('custom_ug_order_type','options','A');
  }
 }
});
