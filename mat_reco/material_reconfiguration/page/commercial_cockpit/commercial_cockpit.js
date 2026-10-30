frappe.pages["commercial-cockpit"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Cockpit commercial"),
		single_column: true,
	});
	$(wrapper).addClass("univers-commercial-page");
	page.$title_area.append(
		$('<span class="ug-commercial-access-badge">').append(
			'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 4v3"/></svg>',
			document.createTextNode(__("Documents spéciaux · A et B"))
		)
	);
	page.main.addClass("univers-commercial-host");
	frappe.require(
		[
			"/assets/mat_reco/js/workshop_vue_dist/workshop.js",
			"/assets/mat_reco/js/workshop_vue_dist/workshop.css",
		],
		() => {
			wrapper.commercial = window.UniversWorkshop.mountCommercialCockpit(page.main[0]);
			if (frappe.get_route()[0] === "commercial-cockpit") wrapper.commercial.show();
		}
	);
};
frappe.pages["commercial-cockpit"].on_page_show = function (wrapper) {
	wrapper.commercial?.show();
};
frappe.pages["commercial-cockpit"].on_page_hide = function (wrapper) {
	wrapper.commercial?.hide();
};
