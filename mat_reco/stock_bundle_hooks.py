import frappe
from frappe import _
from frappe.utils import flt


def validate_bundle_uniform_dimensions(doc, method=None):
    entries = doc.get("entries") or []
    serials = [d.serial_no for d in entries if d.serial_no]

    # Rien à contrôler si 0 ou 1 serial
    if len(serials) <= 1:
        return

    serial_rows = frappe.get_all(
        "Serial No",
        filters={"name": ["in", serials]},
        fields=[
            "name",
            "item_code",
            "custom_dimension_length_mm",
            "custom_dimension_width_mm",
            "custom_dimension_tickness_mm",
        ],
    )

    if not serial_rows:
        return

    # Vérifier que tous les serials existent bien
    found_names = {r["name"] for r in serial_rows}
    missing = [sn for sn in serials if sn not in found_names]
    if missing:
        frappe.throw(
            _("The following Serial Nos were not found: {0}").format(", ".join(missing))
        )

    ref = serial_rows[0]
    ref_item = ref.get("item_code")
    ref_length = flt(ref.get("custom_dimension_length_mm"))
    ref_width = flt(ref.get("custom_dimension_width_mm"))
    ref_thickness = flt(ref.get("custom_dimension_tickness_mm"))

    # Les dimensions doivent exister
    if ref_length <= 0 or ref_width <= 0 or ref_thickness <= 0:
        frappe.throw(
            _("Serial No {0} has missing or invalid dimensions.").format(ref.get("name"))
        )

    invalid = []

    for row in serial_rows[1:]:
        row_item = row.get("item_code")
        row_length = flt(row.get("custom_dimension_length_mm"))
        row_width = flt(row.get("custom_dimension_width_mm"))
        row_thickness = flt(row.get("custom_dimension_tickness_mm"))

        if row_length <= 0 or row_width <= 0 or row_thickness <= 0:
            invalid.append(
                _("{0} (missing dimensions)").format(row.get("name"))
            )
            continue

        if (
            row_item != ref_item
            or row_length != ref_length
            or row_width != ref_width
            or row_thickness != ref_thickness
        ):
            invalid.append(
                _("{0} ({1} x {2} x {3})").format(
                    row.get("name"),
                    row_length,
                    row_width,
                    row_thickness,
                )
            )

    if invalid:
        frappe.throw(
            _(
                "All Serial Nos in a bundle must have the same item and the same dimensions "
                "(Length x Width x Thickness).<br><br>"
                "Reference: {0} / {1} x {2} x {3}<br>"
                "Invalid Serial Nos:<br>{4}"
            ).format(
                ref_item,
                ref_length,
                ref_width,
                ref_thickness,
                "<br>".join(invalid),
            )
        )