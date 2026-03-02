import frappe
from frappe.utils import flt


def _next_remainder_serial(root_serial: str) -> str:
    last = frappe.db.sql(
        """select name from `tabSerial No`
           where custom_root_serial_no=%s and name like %s
           order by name desc limit 1""",
        (root_serial, f"{root_serial}-R%"),
        as_dict=True
    )
    if not last:
        return f"{root_serial}-R01"
    name = last[0].name
    try:
        rnum = int(name.split('-R')[-1])
    except Exception:
        rnum = 0
    return f"{root_serial}-R{rnum+1:02d}"


@frappe.whitelist()
def execute(material_reconfiguration: str) -> str:
    mr = frappe.get_doc('Material Reconfiguration', material_reconfiguration)
    mr.check_permission('write')

    if mr.status not in ('Proposed',):
        frappe.throw('MR must be Proposed before Execute.')

    input_lines = [l for l in mr.material_lines if l.line_type == 'Input']

    if not input_lines:
        frappe.throw('No Inputs found. Please Propose first.')

    # For each input serial, create one Repack and create 0..n remainder serials
    for inp in input_lines:
        parent_serial = inp.serial_no
        root_serial = frappe.db.get_value('Serial No', parent_serial, 'custom_root_serial_no') or parent_serial

        # Build Stock Entry
        se = frappe.new_doc('Stock Entry')
        se.stock_entry_type = 'Repack'

        se.append('items', {
            'item_code': mr.source_item,
            's_warehouse': mr.source_warehouse,
            'qty': 1,
            'serial_no': parent_serial,
        })

        # Outputs for this input
        outs = [
            o for o in mr.outputs
            if getattr(o, 'output_type', None) in ('Remainder', 'Scrap')
            and o.source_serial_no == parent_serial
            and flt(o.length_mm) > 0 and flt(o.width_mm) > 0
        ]

        for o in outs:
            # Remainder and Scrap both generate a serial and become outputs of Repack
            remainder_serial = _next_remainder_serial(root_serial)

            sn = frappe.new_doc('Serial No')
            sn.item_code = mr.source_item
            sn.set_new_name(remainder_serial)
            sn.custom_dimension_length_mm = flt(o.length_mm)
            sn.custom_dimension_width_mm = flt(o.width_mm)
            sn.custom_quality_rating = o.quality_rating or 5
            sn.custom_parent_serial_no = parent_serial
            sn.custom_root_serial_no = root_serial
            sn.custom_material_status = 'Partial'
            sn.insert(ignore_permissions=True)

            se.append('items', {
                'item_code': mr.source_item,
                't_warehouse': o.target_warehouse,
                'qty': 1,
                'serial_no': remainder_serial,
            })

            o.serial_no = remainder_serial

        se.insert(ignore_permissions=True)
        se.submit()

        frappe.db.set_value('Serial No', parent_serial, 'custom_material_status', 'Consumed')

    mr.status = 'Executed'
    mr.save(ignore_permissions=True)
    return mr.name