frappe.ui.form.on("Workshop Refabrication", {
	setup(frm) {
		frm.set_query("sales_order", () => ({ filters: { docstatus: 1 } }));
		frm.set_query("sales_order_item", () => ({
			query: "mat_reco.material_reconfiguration.services.workshop_service.search_order_lines",
			filters: { sales_order: frm.doc.sales_order },
		}));
		frm.set_query("source_stock_entry", () => ({
			filters: { docstatus: 1, stock_entry_type: "Repack" },
		}));
	},
	sales_order(frm) {
		frm.set_value("sales_order_item", null);
		frm.set_value("source_stock_entry", null);
	},
});
