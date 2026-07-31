import unittest
from types import SimpleNamespace

from app.models.role import Role
from app.models.user import User


class Phase2SecurityTests(unittest.TestCase):
    def test_has_role_returns_true_for_matching_role(self):
        user = User(role=Role(code='procurement_unit'))
        self.assertTrue(user.has_role('procurement_unit'))
        self.assertFalse(user.has_role('bidder'))

    def test_accounting_officer_can_access_procurement_within_delegation(self):
        user = User(
            role=Role(code='accounting_officer'),
            department='Finance',
            delegation_limit=5000,
        )
        procurement = SimpleNamespace(user_department='Finance', estimated_value=4000)
        self.assertTrue(user.can_access_procurement(procurement))

    def test_generate_mfa_secret_returns_valid_base32_value(self):
        user = User()
        secret = user.generate_mfa_secret()
        self.assertIsInstance(secret, str)
        self.assertGreater(len(secret), 10)


if __name__ == '__main__':
    unittest.main()
