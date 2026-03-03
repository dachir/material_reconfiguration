# mat_reco/stock_hooks.py

#from apps.crm.crm.api import doc
import frappe
from mat_reco.material_reconfiguration.utils.costing import allocate_repack_costs


def stock_entry_before_submit(doc, method):
    # On applique seulement aux repack venant de MR
    if doc.stock_entry_type != "Repack":
        return

    if not doc.get("custom_sales_order"):
        # ou autre champ pour identifier que ça vient d’un MR
        return

    mr_name = doc.get("custom_material_reconfiguration")
    if not mr_name:
        return

    result = allocate_repack_costs(mr_name)

    lines_map = {l["row_type"]: l for l in result["lines"]}

    for row in doc.items:
        #if row.s_warehouse and not row.t_warehouse:
            # INPUT
        #    row.valuation_rate = lines_map["Input"]["valuation_rate"]

        if row.t_warehouse and row.item_code == lines_map["FG"]["item_code"]:
            # FG
            row.valuation_rate = lines_map["FG"]["valuation_rate"]
            row.basic_amount = row.qty * row.valuation_rate

        elif row.t_warehouse and row.item_code == lines_map["ByProduct"]["item_code"]:
            # CHUTES
            row.valuation_rate = lines_map["ByProduct"]["valuation_rate"]
            row.basic_amount = row.qty * row.valuation_rate

    doc.set_total_incoming_outgoing_value()
    doc.set_total_amount()