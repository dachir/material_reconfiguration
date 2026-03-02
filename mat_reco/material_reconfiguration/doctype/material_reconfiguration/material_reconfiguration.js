// Copyright (c) 2026, Richard Amouzou and contributors
// For license information, please see license.txt

frappe.ui.form.on("Material Reconfiguration", {
  refresh(frm) {
    if (frm.doc.docstatus !== 1) return;

    frm.add_custom_button(__("Create Repack (New, Bundled)"), async () => {
      try {
        const res = await frappe.call({
          method: "mat_reco.material_reconfiguration.api.get_repack_payload",
          args: { mr_name: frm.doc.name },
          freeze: true
        });

        const payload = res.message;
        if (!payload || !payload.lines) {
          frappe.msgprint("No payload returned.");
          return;
        }

        // 1) New Stock Entry (unsaved)
        const se = frappe.model.get_new_doc("Stock Entry");
        se.stock_entry_type = payload.stock_entry_type || "Repack";
        se.remarks = payload.remarks || "";

        // Helper: create bundle in DB (so link validation passes on Stock Entry save)
        const make_bundle = async (item_code, warehouse, serials, transaction_type) => {
          const r = await frappe.call({
            method: "mat_reco.material_reconfiguration.api.create_serial_batch_bundle",
            args: {
              company: frm.doc.company,
              voucher_type: "Stock Entry",
              item_code: item_code,
              warehouse: warehouse,
              serials: serials,
              transaction_type: transaction_type || "Outward",
              custom_sales_order : frm.doc.sales_order,
            },
            freeze: true
          });
          return r.message; // real bundle name
        };

        // cache item -> stock_uom
        const item_uom_cache = {};

        const get_stock_uom = async (item_code) => {
          if (item_uom_cache[item_code]) return item_uom_cache[item_code];
          const r = await frappe.db.get_value("Item", item_code, "stock_uom");
          const uom = (r && r.message && r.message.stock_uom) ? r.message.stock_uom : null;
          item_uom_cache[item_code] = uom;
          return uom;
        };

        // 2) Fill Stock Entry items using 1 line per group
        for (const line of payload.lines) {
          const row = frappe.model.add_child(se, "Stock Entry Detail", "items");

          row.item_code = line.item_code;
          row.s_warehouse = line.s_warehouse || null;
          row.t_warehouse = line.t_warehouse || null;

          row.qty = line.qty || 0;
          row.conversion_factor = 1;
          row.allow_zero_valuation_rate = 1;

          const stock_uom = await get_stock_uom(line.item_code);
          if (stock_uom) row.stock_uom = stock_uom;
          row.stock_qty = row.qty;

          // Bundles
          if (line.serials && line.serials.length) {
            const wh = line.s_warehouse || line.t_warehouse;

            // Input bundles are Outward; Output bundles are Inward (if you want)
            const tx = (line.row_type === "Input") ? "Outward" : "Inward";

            const bundle_name = await make_bundle(line.item_code, wh, line.serials, tx);
            row.serial_and_batch_bundle = bundle_name;
            row.serial_batch_bundle = bundle_name;
          }
        }

        // 3) Open unsaved Stock Entry
        frappe.set_route("Form", "Stock Entry", se.name);

      } catch (e) {
        console.error(e);
        frappe.msgprint({
          title: __("Error"),
          message: __(e.message || e),
          indicator: "red"
        });
      }
    }, __("Actions"));
  }
});

frappe.ui.form.on("Material Reconfiguration", {
  refresh(frm) {
    // Filter queries (safe to call on refresh)
    setup_queries(frm);
  },

  sales_order(frm) {
    // reset dependent fields
    frm.set_value("fg_item_code", null);
    frm.set_value("so_item_row", null);
    frm.set_value("fg_total_qty", 0);
    frm.set_value("fg_length_mm", 0);
    frm.set_value("fg_width_mm", 0);

    setup_queries(frm);
  },

  fg_item_code: async function (frm) {
    setup_queries(frm);

    if (!frm.doc.sales_order || !frm.doc.fg_item_code) return;

    // Auto-pick first row of that FG in the SO
    try {
      const r = await frappe.call({
        method:
          "mat_reco.material_reconfiguration.doctype.material_reconfiguration.material_reconfiguration.get_first_so_item_row",
        args: {
          sales_order: frm.doc.sales_order,
          item_code: frm.doc.fg_item_code,
        },
      });

      const rowname = r.message;
      if (rowname) {
        // This will trigger so_item_row handler
        await frm.set_value("so_item_row", rowname);
      } else {
        frm.set_value("so_item_row", null);
        frm.set_value("fg_total_qty", 0);
        frm.set_value("fg_length_mm", 0);
        frm.set_value("fg_width_mm", 0);
      }
    } catch (e) {
      console.error(e);
      frappe.msgprint(__("Failed to fetch the first SO item row for this FG."));
    }
  },

  so_item_row: async function (frm) {
    if (!frm.doc.so_item_row) return;

    try {
      const r = await frappe.call({
        method:
          "mat_reco.material_reconfiguration.doctype.material_reconfiguration.material_reconfiguration.get_fg_from_so_item_row",
        args: { so_item_row: frm.doc.so_item_row },
      });

      const data = r.message || {};
      // For safety, keep fg_item_code consistent with the row
      if (data.item_code && frm.doc.fg_item_code !== data.item_code) {
        await frm.set_value("fg_item_code", data.item_code);
      }

      await frm.set_value("fg_total_qty", data.qty || 0);
      await frm.set_value("fg_length_mm", data.length_mm || 0);
      await frm.set_value("fg_width_mm", data.width_mm || 0);
    } catch (e) {
      console.error(e);
      frappe.msgprint(__("Failed to fetch FG dimensions/qty from Sales Order line."));
    }
  },

  validate(frm) {
    if (frm.doc.fg_item_code && !frm.doc.so_item_row) {
      frappe.throw(__("Please select a Sales Order Item row (so_item_row)."));
    }
  },
});

function setup_queries(frm) {
  // 1) fg_item_code: only reconfigurable FG items in this SO
  frm.set_query("fg_item_code", () => {
    if (!frm.doc.sales_order) return {};

    return {
      query:
        "mat_reco.material_reconfiguration.doctype.material_reconfiguration.material_reconfiguration.get_reconfigurable_fg_items",
      filters: {
        sales_order: frm.doc.sales_order,
      },
    };
  });

  // 2) so_item_row: only reconfigurable SO item rows
  // If fg_item_code is chosen, restrict to that item_code.
  frm.set_query("so_item_row", () => {
    const filters = { sales_order: frm.doc.sales_order };

    // IMPORTANT: only include item_code if fg_item_code is set
    if (frm.doc.fg_item_code) {
      filters.item_code = frm.doc.fg_item_code;
    }

    return {
      query:
        "mat_reco.material_reconfiguration.doctype.material_reconfiguration.material_reconfiguration.get_reconfigurable_so_item_rows",
      filters,
    };
  });
}

// material_reconfiguration.js
// Préremplit le champ kerf_mm avec la valeur des paramètres globaux
frappe.ui.form.on('Material Reconfiguration', {
    refresh: function(frm) {
        // Si kerf_mm est vide, récupérer la valeur depuis Reconfiguration Settings
        if (!frm.doc.kerf_mm) {
          frappe.db
            .get_single_value("Reconfiguration Settings","kerf_mm")
            .then(v=> frm.set_value('kerf_mm', v))
            .catch(e => {
              console.error("Failed to fetch kerf_mm from Reconfiguration Settings:", e);
              frappe.msgprint({
                title: __("Error"),
                message: __("Failed to fetch kerf_mm from Reconfiguration Settings. Please set it manually."),
                indicator: "red"
              });
            });
        }
    }
});