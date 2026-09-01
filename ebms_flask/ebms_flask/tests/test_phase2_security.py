import unittest
from types import SimpleNamespace

from app.models.procurement import Procurement
from app.models.role import Role
from app.models.user import User


class Phase2SecurityTests(unittest.TestCase):
    def test_has_role_returns_true_for_matching_role(self):
        user = User(role=Role(code='procurement_unit'))
        self.assertTrue(user.has_role('procurement_unit'))
        self.assertFalse(user.has_role('bidder'))

    def test_accounting_officer_can_access_procurement_without_limit_restriction(self):
        user = User(
            role=Role(code='accounting_officer'),
            department='Finance',
            delegation_limit=0,
        )
        procurement = SimpleNamespace(user_department='Finance', estimated_value=4000)
        self.assertTrue(user.can_access_procurement(procurement))

    def test_generate_mfa_secret_returns_valid_base32_value(self):
        user = User()
        secret = user.generate_mfa_secret()
        self.assertIsInstance(secret, str)
        self.assertGreater(len(secret), 10)

    def test_user_can_access_procurement_by_procurement_entity(self):
        user = User(role=Role(code='user_department'), department='Ministry of Health')
        procurement = SimpleNamespace(procurement_entity='Ministry of Health', user_department='Ministry of Health', estimated_value=4000)
        self.assertTrue(user.can_access_procurement(procurement))

    def test_ppra_code_options_include_main_codes_and_subcodes(self):
        options = Procurement.ppra_code_options()
        self.assertIn('100', options)
        self.assertIn('101', options)
        self.assertIn('100-01', options)

    def test_ppra_classification_lookup_has_descriptions_for_code_and_subcode(self):
        self.assertIn('100', Procurement.ppra_classification_lookup())
        self.assertIn('01', Procurement.ppra_sub_codes_for('100'))
        description = Procurement.ppra_description('100', '01')
        self.assertIsInstance(description, str)
        self.assertTrue(description)
        self.assertIn('construction', description.lower())

    def test_ppra_code_labels_include_code_and_name(self):
        labels = Procurement.ppra_code_labels()
        self.assertIn('100', labels)
        self.assertIn('Security Services', labels['100'])
        self.assertIn('General Supplies', labels['211'])

    def test_ppra_description_returns_code_name_and_subcode_description(self):
        self.assertIn('Clinical waste', Procurement.ppra_description('103', '03'))
        self.assertIn('Security Services', Procurement.ppra_description('100', '01'))


if __name__ == '__main__':
    unittest.main()
