import unittest

from app.models.procurement import Procurement, Lot


class Phase3GovernanceTests(unittest.TestCase):
    def test_direct_procurement_is_blocked_above_threshold(self):
        procurement = Procurement(method='direct', estimated_value=900000)
        result = procurement.check_governance_rules(direct_threshold=500000)
        self.assertIn('direct_procurement_exceeds_threshold', result['errors'])

    def test_lot_splitting_is_flagged_when_total_crosses_threshold(self):
        procurement = Procurement(method='direct', estimated_value=600000)
        procurement.lots = [
            Lot(estimated_value=300000),
            Lot(estimated_value=300000),
        ]
        result = procurement.check_governance_rules(direct_threshold=500000, open_threshold=500000)
        self.assertIn('lot_splitting_risk', result['warnings'])


if __name__ == '__main__':
    unittest.main()
