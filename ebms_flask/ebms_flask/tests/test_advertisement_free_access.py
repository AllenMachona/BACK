import unittest
import uuid

from app import create_app
from app.extensions import db
from app.models.communication import Communication
from app.models.procurement import Procurement
from app.models.bidder import Bidder
from app.models.role import Role
from app.models.user import User


class AdvertisementFreeAccessTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        with self.app.app_context():
            bidder = Bidder.query.filter_by(contact_email='bids@mokwenaconstruction.co.bw').first()
            if not bidder:
                bidder = Bidder(company_name='Mokwena Construction', contact_email='bids@mokwenaconstruction.co.bw', active=True, verified=True)
                db.session.add(bidder)
                db.session.commit()

            user = User.query.filter_by(username='bidder1').first()
            if not user:
                role = Role.query.filter_by(code='bidder').first()
                user = User(
                    username='bidder1',
                    email='bids@mokwenaconstruction.co.bw',
                    first_name='Karabo',
                    last_name='Mokwena',
                    department='Construction',
                    designation='Bidder',
                    role_id=role.id,
                    bidder_id=bidder.id,
                    is_active=True,
                )
                user.set_password('ChangeMe123!')
                db.session.add(user)
                db.session.commit()

            tender_number = f"TB-2026-ADVERT-{uuid.uuid4().hex[:8].upper()}"
            tender = Procurement(
                tender_number=tender_number,
                title='Advertisement Access Test',
                category='works',
                method='open_domestic',
                estimated_value=150000,
                procurement_entity='Ministry of Transport',
                user_department='Ministry of Transport',
                status='published',
                created_by_id=1,
            )
            db.session.add(tender)
            db.session.commit()

            comm = Communication(
                procurement_id=tender.id,
                type='advertisement',
                title='Tender Advertisement',
                content='Public advertisement',
                file_path='dummy.pdf',
                original_filename='advertisement.pdf',
                is_public=True,
                from_user_id=1,
            )
            db.session.add(comm)
            db.session.commit()

    def test_bidder_can_download_free_advertisement_without_payment(self):
        self.client.post('/login', data={'username': 'bidder1', 'password': 'ChangeMe123!'}, follow_redirects=True)

        with self.app.app_context():
            procurement = Procurement.query.filter_by(title='Advertisement Access Test').first()
            advertisement = procurement.communications.filter_by(type='advertisement').first()
            response = self.client.get(f'/procurements/{procurement.id}/documents/{advertisement.id}/download', follow_redirects=False)
            self.assertNotEqual(response.status_code, 403)
            self.assertNotEqual(response.status_code, 404)


if __name__ == '__main__':
    unittest.main()
