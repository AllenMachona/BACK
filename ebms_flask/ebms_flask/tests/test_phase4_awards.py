import unittest
from datetime import datetime, timedelta

from app.models.award import Award
from app.models.complaint import Complaint
from app.models.procurement import Procurement


class Phase4AwardAndComplaintTests(unittest.TestCase):
    def test_award_cooling_off_is_active_while_valid(self):
        award = Award(cooling_off_expiry=datetime.utcnow() + timedelta(days=5))
        self.assertTrue(award.cooling_off_active())

    def test_procurement_blocks_contract_stage_while_complaint_is_live(self):
        procurement = Procurement(status='award_published')
        procurement.complaints = [Complaint(status='under_review')]
        self.assertFalse(procurement.can_transition_to_contract())

    def test_procurement_allows_contract_when_complaint_is_resolved(self):
        procurement = Procurement(status='award_published')
        procurement.complaints = [Complaint(status='dismissed')]
        self.assertTrue(procurement.can_transition_to_contract())


if __name__ == '__main__':
    unittest.main()
