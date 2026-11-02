"""Cash amounts and available advances are distinct after a refund."""
import unittest
from mat_reco.material_reconfiguration.services.commercial_cockpit import _receipt_parts


class RefundProjectionTests(unittest.TestCase):
    def test_mixed_receipt_keeps_its_cash_split_and_reduces_only_the_advance(self):
        orders={'A':dict(name='A',custom_ug_order_type='A')}
        parts=_receipt_parts(dict(order_type='Mixte',amount=150,sales_order='A',unallocated_amount=30),
            [dict(bordereau='BL',amount=100)],{'BL':dict(order_type='B',sales_order='B')},orders)
        self.assertEqual((parts['A'],parts['B']),(50,100))
        self.assertEqual(parts['advances_by_order']['A'],30)
        self.assertEqual(parts['by_order']['A'],50)

    def test_refund_is_a_cash_reversal_not_a_new_negative_advance(self):
        parts=_receipt_parts(dict(payment_kind='Remboursement',order_type='B',amount=50,sales_order='B',unallocated_amount=0),
            [],{}, {'B':dict(name='B',custom_ug_order_type='B')})
        self.assertEqual(parts['B'],-50)
        self.assertEqual(parts['by_order']['B'],-50)
        self.assertEqual(dict(parts['advances_by_order']),{})

    def test_original_b_receipt_is_counted_once_even_after_refund(self):
        parts=_receipt_parts(dict(order_type='B',amount=120,sales_order='B',unallocated_amount=70),
            [],{}, {'B':dict(name='B',custom_ug_order_type='B')})
        self.assertEqual(parts['B'],120)
        self.assertEqual(parts['advances_by_order']['B'],70)
