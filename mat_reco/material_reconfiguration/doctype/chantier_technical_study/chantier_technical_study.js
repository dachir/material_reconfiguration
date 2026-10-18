frappe.ui.form.on('Chantier Technical Study',{refresh(frm){if(!frm.is_new())frm.add_custom_button(__('Vue fiche technique'),()=>frappe.set_route('technical-study',frm.doc.name));}});
