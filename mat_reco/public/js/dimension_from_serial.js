function bind_dimension_fields_from_serial(doctype) {
    frappe.ui.form.on(doctype, {
        serial_and_batch_bundle(frm, cdt, cdn) {
            update_dimension_fields_from_bundle(frm, cdt, cdn);
        }
    });
}

bind_dimension_fields_from_serial("Delivery Note Item");
bind_dimension_fields_from_serial("Sales Invoice Item");

async function update_dimension_fields_from_bundle(frm, cdt, cdn) {

    const row = locals[cdt][cdn];
    if (!row.item_code || !row.serial_and_batch_bundle) return;

    try {

        const item_r = await frappe.db.get_value(
            "Item",
            row.item_code,
            "custom_item_types"
        );

        const item_type = item_r?.message?.custom_item_types || "";
        if (item_type !== "DECOUPE") return;

        const bundle = await frappe.db.get_doc(
            "Serial and Batch Bundle",
            row.serial_and_batch_bundle
        );

        const first_entry = (bundle.entries || []).find(d => d.serial_no);
        if (!first_entry) return;

        const serial = await frappe.db.get_doc("Serial No", first_entry.serial_no);

        frappe.model.set_value(
            cdt,
            cdn,
            "custom_client_length_mm",
            parseFloat(serial.custom_dimension_length_mm)
        );

        frappe.model.set_value(
            cdt,
            cdn,
            "custom_client_width_mm",
            parseFloat(serial.custom_dimension_width_mm)
        );

        frappe.model.set_value(
            cdt,
            cdn,
            "custom_client_thickness_mm",
            parseFloat(serial.custom_dimension_thickness_mm)
        );

    } catch (e) {
        console.error("Failed to fetch dimensions from Serial No bundle", e);
    }
}