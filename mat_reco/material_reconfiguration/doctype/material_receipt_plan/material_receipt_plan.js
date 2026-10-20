// Copyright (c) 2026, Richard Amouzou and contributors
// For license information, please see license.txt

const RECEIPT_DETAIL_FIELD = "material_receipt_plan_serial";

function receipt_rows(frm) {
    return frm.doc[RECEIPT_DETAIL_FIELD] || [];
}

function set_receipt_grid_properties(frm) {
    const field = frm.fields_dict[RECEIPT_DETAIL_FIELD];
    if (!field || !field.grid) return;

    const is_primary = (frm.doc.item_type || "").toUpperCase() === "PRIMAIRE";
    const grid = field.grid;

    ["length_mm", "width_mm", "thickness_mm"].forEach((fieldname) => {
        grid.update_docfield_property(fieldname, "read_only", is_primary ? 1 : 0);
    });

    ["serial_no", "area_m2", "basic_rate"].forEach((fieldname) => {
        grid.update_docfield_property(fieldname, "read_only", 1);
    });
}

function calculate_receipt_plan(frm) {
    const rows = receipt_rows(frm);
    let total_area = 0;

    rows.forEach((row) => {
        const length = flt(row.length_mm);
        const width = flt(row.width_mm);
        row.area_m2 = (length > 0 && width > 0)
            ? length * width / 1000000.0
            : 0;
        total_area += flt(row.area_m2);
    });

    frm.doc.total_area = total_area;

    const amount = flt(frm.doc.amount);
    const positive_rows = rows.filter((row) => flt(row.area_m2) > 0);
    let allocated = 0;

    positive_rows.forEach((row, index) => {
        if (index === positive_rows.length - 1) {
            row.basic_rate = amount - allocated;
        } else {
            row.basic_rate = total_area > 0
                ? amount * flt(row.area_m2) / total_area
                : 0;
            allocated += flt(row.basic_rate);
        }
    });

    rows.filter((row) => flt(row.area_m2) <= 0).forEach((row) => {
        row.basic_rate = 0;
    });

    frm.refresh_field("total_area");
    frm.refresh_field(RECEIPT_DETAIL_FIELD);
}

function sync_receipt_rows(frm) {
    const qty = Math.max(0, Math.floor(flt(frm.doc.qty)));
    let rows = receipt_rows(frm);

    while (rows.length < qty) {
        frappe.model.add_child(
            frm.doc,
            "Material Receipt Plan Serial",
            RECEIPT_DETAIL_FIELD
        );
        rows = receipt_rows(frm);
    }

    while (rows.length > qty) {
        const row = rows[rows.length - 1];
        frappe.model.clear_doc(row.doctype, row.name);
        rows = receipt_rows(frm);
    }

    frm.refresh_field(RECEIPT_DETAIL_FIELD);
}

async function apply_primary_dimensions(frm) {
    if (!frm.doc.item_code || (frm.doc.item_type || "").toUpperCase() !== "PRIMAIRE") {
        return;
    }

    const r = await frappe.db.get_value("Item", frm.doc.item_code, [
        "custom_sheet_length_mm",
        "custom_sheet_width_mm",
        "custom_thickness_mm"
    ]);
    const values = r.message || {};

    receipt_rows(frm).forEach((row) => {
        row.length_mm = flt(values.custom_sheet_length_mm);
        row.width_mm = flt(values.custom_sheet_width_mm);
        row.thickness_mm = flt(values.custom_thickness_mm);
    });

    calculate_receipt_plan(frm);
}

frappe.ui.form.on("Material Receipt Plan", {
    refresh(frm) {
        set_receipt_grid_properties(frm);
        calculate_receipt_plan(frm);
    },

    async item_code(frm) {
        if (!frm.doc.item_code) {
            frm.set_value("item_type", "");
            return;
        }

        const r = await frappe.db.get_value(
            "Item",
            frm.doc.item_code,
            "custom_item_types"
        );
        await frm.set_value(
            "item_type",
            (r.message || {}).custom_item_types || ""
        );

        set_receipt_grid_properties(frm);
        sync_receipt_rows(frm);
        await apply_primary_dimensions(frm);
        calculate_receipt_plan(frm);
    },

    async qty(frm) {
        sync_receipt_rows(frm);
        await apply_primary_dimensions(frm);
        calculate_receipt_plan(frm);
    },

    amount(frm) {
        calculate_receipt_plan(frm);
    }
});

frappe.ui.form.on("Material Receipt Plan Serial", {
    length_mm(frm) { calculate_receipt_plan(frm); },
    width_mm(frm) { calculate_receipt_plan(frm); },
    thickness_mm(frm) { calculate_receipt_plan(frm); },
    material_receipt_plan_serial_remove(frm) { calculate_receipt_plan(frm); }
});
