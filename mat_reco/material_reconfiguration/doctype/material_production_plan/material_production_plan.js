frappe.ui.form.on('Material Production Plan', {refresh(frm) {
 if(frm.doc.sales_order)frm.add_custom_button(__('Ouvrir le cockpit atelier'),()=>{
  if(frm.doc.chantier)sessionStorage.setItem('univers-workshop-chantier',frm.doc.chantier);
  frappe.set_route('workshop-cockpit');
 });
}});
