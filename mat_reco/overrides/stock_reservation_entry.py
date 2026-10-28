"""Keep the exact manufactured serial, retaining every native SRE validation."""
import frappe
from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import StockReservationEntry


class UGStockReservationEntry(StockReservationEntry):
    def auto_reserve_serial_and_batch(self, based_on=None):
        if frappe.flags.get('ug_exact_production_reservation'):
            return
        return super().auto_reserve_serial_and_batch(based_on)
