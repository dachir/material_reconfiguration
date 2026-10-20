frappe.pages["technical-study"].on_page_load = function(wrapper) {
 const page = frappe.ui.make_app_page({parent: wrapper, title: __("Fiche technique"), single_column: true});
 frappe.require(["/assets/mat_reco/js/workshop_vue_dist/workshop.js", "/assets/mat_reco/js/workshop_vue_dist/workshop.css"], () => {
  wrapper.study = window.UniversWorkshop.mountTechnicalStudy(page.main[0], status => {
   if (status == null) {
    page.clear_indicator();
   } else {
    page.set_indicator([__("Brouillon"), __("Validée"), __("Annulée")][status], ["orange", "green", "red"][status]);
   }
  });
  if (frappe.get_route()[0] === "technical-study") wrapper.study.show();
 });
};
frappe.pages["technical-study"].on_page_show = function(wrapper) {
 document.body.classList.remove("ug-technical-active");
 wrapper.study?.show();
};
frappe.pages["technical-study"].on_page_hide = function(wrapper) {
 wrapper.study?.hide();
};
