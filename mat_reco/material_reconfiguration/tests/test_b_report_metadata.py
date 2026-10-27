"""Document type names are routing data, not links to technical DocType records."""
import unittest
from unittest.mock import patch

import frappe
from frappe.desk.query_report import get_linked_doctypes
from mat_reco.material_reconfiguration.report.situation_des_comptes_clients_b import situation_des_comptes_clients_b as report


class BReportMetadataTests(unittest.TestCase):
    def test_reference_links_do_not_require_reading_doctype_records(self):
        with patch.object(report.b, 'access'), patch.object(frappe, 'get_list', return_value=[]):
            columns, _ = report.execute({'from_date': '2026-10-01', 'to_date': '2026-10-27'})
        by_name = {column['fieldname']: column for column in columns}
        self.assertEqual(by_name['reference_doctype']['fieldtype'], 'Data')
        self.assertEqual(by_name['reference_name']['fieldtype'], 'Dynamic Link')
        self.assertEqual(by_name['reference_name']['options'], 'reference_doctype')
        for doctype in (report.b.DELIVERY, report.b.PAYMENT):
            linked = get_linked_doctypes(columns, [frappe._dict(reference_doctype=doctype, reference_name='TEST')])
            self.assertNotIn('DocType', linked)
