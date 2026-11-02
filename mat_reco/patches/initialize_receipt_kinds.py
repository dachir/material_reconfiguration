"""Legacy receipts remain receipts; never infer refunds from negative balances."""
import frappe


def execute():
    frappe.db.sql("""UPDATE `tabReglement Special` SET payment_kind='Encaissement'
        WHERE payment_kind IS NULL OR payment_kind=''""")
    frappe.db.add_index('Reglement Special', ['refund_of', 'docstatus'])
