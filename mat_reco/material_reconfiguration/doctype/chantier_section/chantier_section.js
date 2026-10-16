frappe.ui.form.on('Chantier Section', {setup(frm){frm.set_query('parent_chantier_section',()=>({filters:{chantier:frm.doc.chantier,is_group:1,name:['!=',frm.doc.name]}}));}});
