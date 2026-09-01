import unittest
import uuid

from app import create_app
from app.extensions import db
from app.models.procurement import Procurement


class AdminGlobalSearchTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        with self.app.app_context():
            tender_number = f"TB-2026-ADMIN-{uuid.uuid4().hex[:8].upper()}"
            tender = Procurement(
                tender_number=tender_number,
                title='Admin Tender Lookup',
                category='works',
                method='open_domestic',
                estimated_value=180000,
                procurement_entity='Ministry of Transport',
                user_department='Ministry of Transport',
                status='published',
                created_by_id=1,
            )
            db.session.add(tender)
            db.session.commit()

    def test_admin_can_access_global_search(self):
        login_response = self.client.post(
            '/login',
            data={'username': 'admin', 'password': 'ChangeMe123!'},
            follow_redirects=True,
        )
        self.assertEqual(login_response.status_code, 200)

        response = self.client.get('/procurements/search?q=Admin%20Tender', follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Global Search', response.data)
        self.assertIn(b'Admin Tender Lookup', response.data)


if __name__ == '__main__':
    unittest.main()
