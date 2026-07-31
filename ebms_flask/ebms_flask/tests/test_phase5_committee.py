import unittest
from datetime import datetime, timedelta

from app.models.committee import CommitteeMember
from app.models.procurement import Procurement


class Phase5CommitteeTests(unittest.TestCase):
    def test_committee_member_access_is_revoked_when_expired(self):
        member = CommitteeMember(
            access_granted=True,
            access_valid_from=datetime.utcnow() - timedelta(days=10),
            access_valid_until=datetime.utcnow() - timedelta(days=1),
            confidentiality_signed=True,
        )
        self.assertFalse(member.is_access_active())

    def test_procurement_allows_committee_access_only_for_active_members(self):
        procurement = Procurement(status='technical_evaluation')
        member = CommitteeMember(
            procurement_id=1,
            user_id=7,
            role='member',
            access_granted=True,
            access_valid_from=datetime.utcnow() - timedelta(days=3),
            access_valid_until=datetime.utcnow() + timedelta(days=30),
            confidentiality_signed=True,
            conflict_of_interest_declared=False,
        )
        self.assertTrue(procurement.can_committee_member_access(member))


if __name__ == '__main__':
    unittest.main()
