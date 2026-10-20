frappe.pages["workshop-cockpit"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Atelier Univers Glass"),
		single_column: true,
	});
	wrapper.workshopPage = page;
	page.main.addClass("univers-workshop-host");
	frappe.require(
		[
			"/assets/mat_reco/js/workshop_vue_dist/workshop.js",
			"/assets/mat_reco/js/workshop_vue_dist/workshop.css",
		],
		() => {
			wrapper.workshop = window.UniversWorkshop.mount(page.main[0]);
			wrapper.workshop.show();
		}
	);
};
frappe.pages["workshop-cockpit"].on_page_show = function (wrapper) {
	document.body.classList.remove("ug-workshop-active");
	wrapper.workshop?.show();
};
frappe.pages["workshop-cockpit"].on_page_hide = function (wrapper) {
	document.body.classList.remove("ug-workshop-active");
	wrapper.workshop?.hide();
};
