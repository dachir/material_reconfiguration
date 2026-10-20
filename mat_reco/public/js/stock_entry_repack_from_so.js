frappe.ui.form.on("Stock Entry", {
	refresh(frm) {
		if (frm.doc.docstatus !== 0) return;
		if (frm.doc.stock_entry_type && frm.doc.stock_entry_type !== "Repack") return;

		frm.add_custom_button(__("Get Pending SO Line"), function () {
			open_pending_so_line_dialog(frm);
		});
	}
});

async function open_pending_so_line_dialog(frm) {
	try {
		const company = frm.doc.company;

		if (!company) {
			frappe.msgprint(__("Please select Company first."));
			return;
		}

		const r = await frappe.call({
			method: "mat_reco.material_reconfiguration.services.repack_from_sales_order_service.get_pending_sales_order_lines_for_repack",
			args: {
				company: company
			},
			freeze: true,
			freeze_message: __("Loading pending sales order lines...")
		});

		const rows = (r.message || []).filter(d => flt_num(d.qty_pending) > 0);

		let selected = null;

		const dialog = new frappe.ui.Dialog({
			title: __("Select Sales Order Line"),
			size: "extra-large",
			fields: [
				{
					fieldname: "results_html",
					fieldtype: "HTML"
				}
			],
			primary_action_label: __("Create Repack"),
			primary_action: async function () {
				if (!selected) {
					frappe.msgprint(__("Please select one line."));
					return;
				}

				try {
					const x = await frappe.call({
						method: "mat_reco.material_reconfiguration.services.repack_from_sales_order_service.create_repack_from_sales_order_item",
						args: {
							company: company,
							sales_order_item_name: selected.sales_order_item,
							generate_qty: selected.qty_generable
						},
						freeze: true,
						freeze_message: __("Creating repack...")
					});

					const docname = x.message.stock_entry;
					dialog.hide();

					frappe.set_route("Form", "Stock Entry", docname);
				} catch (e) {
					frappe.msgprint({
						title: __("Creation Error"),
						message: e.message || e,
						indicator: "red"
					});
				}
			}
		});

		dialog.show();

		const wrapper = dialog.get_field("results_html").$wrapper;
		wrapper.empty();

		if (!rows.length) {
			wrapper.html(
				`<div class="text-muted" style="padding:12px;">
					${__("No pending Sales Order line can currently be satisfied from stock.")}
				</div>`
			);
			return;
		}

		const table = $(`
			<div style="max-height: 500px; overflow: auto;">
				<table class="table table-bordered table-hover">
					<thead>
						<tr>
							<th style="width:40px;">${__("Select")}</th>
							<th>${__("Sales Order")}</th>
							<th>${__("Item Code")}</th>
							<th>${__("Item Name")}</th>
							<th>${__("Longueur")}</th>
							<th>${__("Hauteur")}</th>
							<th>${__("Epaisseur")}</th>
							<th>${__("Qty Commande")}</th>
							<th>${__("Qty Déjà Générée")}</th>
							<th>${__("Qty Restante")}</th>
							<th>${__("Qty Satisfiable")}</th>
						</tr>
					</thead>
					<tbody></tbody>
				</table>
			</div>
		`);

		wrapper.append(table);
		const tbody = table.find("tbody");

		rows.forEach((row, index) => {
			const tr = $(`
				<tr data-index="${index}" style="cursor:pointer;">
					<td><input type="radio" name="so_line_pick"></td>
					<td>${escape_html(row.sales_order || "")}</td>
					<td>${escape_html(row.item_code || "")}</td>
					<td>${escape_html(row.item_name || "")}</td>
					<td style="text-align:right;">${format_num(row.length_mm)}</td>
					<td style="text-align:right;">${format_num(row.width_mm)}</td>
					<td style="text-align:right;">${format_num(row.thickness_mm)}</td>
					<td style="text-align:right;">${format_num(row.qty_ordered)}</td>
					<td style="text-align:right;">${format_num(row.qty_generated)}</td>
					<td style="text-align:right;">${format_num(row.qty_pending)}</td>
					<td style="text-align:right;"><b>${format_num(row.qty_generable)}</b></td>
				</tr>
			`);

			tr.on("click", function () {
				tbody.find("tr").removeClass("table-active");
				tbody.find("input[type=radio]").prop("checked", false);

				$(this).addClass("table-active");
				$(this).find("input[type=radio]").prop("checked", true);

				selected = row;
			});

			tbody.append(tr);
		});

	} catch (e) {
		frappe.msgprint({
			title: __("Error"),
			message: e.message || e,
			indicator: "red"
		});
	}
}

function flt_num(v) {
	return parseFloat(v || 0);
}

function format_num(v) {
	return frappe.format(flt_num(v), { fieldtype: "Float" });
}

function escape_html(txt) {
	return frappe.utils.escape_html(txt || "");
}