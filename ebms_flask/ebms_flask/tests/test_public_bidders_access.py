import unittest
import uuid

from app import create_app
from app.extensions import db
from app.models.procurement import Procurement


class PublicTenderAccessTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        with self.app.app_context():
            db.session.rollback()
            unique_number = f"TB-2026-PUBLIC-{uuid.uuid4().hex[:8].upper()}"
            tender = Procurement(
                tender_number=unique_number,
                title='Public Tender View Test',
                category='works',
                method='open_domestic',
                estimated_value=250000,
                procurement_entity='Ministry of Works',
                user_department='Ministry of Works',
                status='published',
                created_by_id=1,
            )
            db.session.add(tender)
            db.session.commit()

    def test_root_page_is_available_without_login(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'National e-Procurement', response.data)
        self.assertIn(b'Current Tenders', response.data)

    def test_public_tender_search_page_accepts_filters_without_login(self):
        response = self.client.get('/tenders?q=Public%20Tender&category=works')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Public Tender View Test', response.data)


if __name__ == '__main__':
    unittest.main()
