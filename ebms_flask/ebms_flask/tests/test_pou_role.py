import unittest

from app import create_app
from app.extensions import db
from app.models.role import Role
from app.models.user import User
from app.models.procurement import Procurement


class PouRoleTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_pou_role_exists_and_grants_access(self):
        role = Role.query.filter_by(code='pou').first()
        self.assertIsNotNone(role)
        self.assertEqual(role.name, 'Procurement Oversight Unit')
        self.assertTrue(role.can_view_all_records)

        user = User.query.filter_by(username='pou_user').first()
        if not user:
            user = User(
                username='pou_user',
                email='pou@example.com',
                first_name='POU',
                last_name='Reviewer',
                role_id=role.id,
                department='Quality Assurance',
                is_active=True,
            )
            user.set_password('ChangeMe123!')
            db.session.add(user)
            db.session.commit()

        procurement = Procurement(
            tender_number='TB-POU-TEST-001',
            title='POU oversight access test',
            category='works',
            method='open_domestic',
            estimated_value=200000,
            procurement_entity='Ministry of Transport',
            user_department='Ministry of Transport',
            status='published',
            created_by_id=1,
        )
        db.session.add(procurement)
        db.session.commit()

        self.assertTrue(user.can_access_procurement(procurement))


if __name__ == '__main__':
    unittest.main()
