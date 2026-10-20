frappe.pages["chantiers"].on_page_load = function(wrapper) {
 const page=frappe.ui.make_app_page({parent:wrapper,title:__("Chantiers Univers Glass"),single_column:true});
 frappe.require(["/assets/mat_reco/js/workshop_vue_dist/workshop.js", "/assets/mat_reco/js/workshop_vue_dist/workshop.css"],()=>{
  wrapper.chantiers=window.UniversWorkshop.mountChantiers(page.main[0]);
  if(frappe.get_route()[0]==="chantiers")wrapper.chantiers.show();
 });
};
frappe.pages["chantiers"].on_page_show=function(wrapper){wrapper.chantiers?.show();};
frappe.pages["chantiers"].on_page_hide=function(wrapper){wrapper.chantiers?.hide();};
