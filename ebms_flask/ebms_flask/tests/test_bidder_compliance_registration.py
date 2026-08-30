import io
import unittest

from app import create_app
from app.extensions import db
from app.models.bidder import Bidder
from app.models.bidder_compliance import BidderComplianceDocument
from app.models.payment import BidderPayment
from app.models.procurement import Procurement
from app.models.role import Role
from app.models.user import User


class BidderComplianceRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        with self.app.app_context():
            db.drop_all()
            db.create_all()

    def test_registration_requires_two_compliance_documents(self):
        response = self.client.post(
            '/register',
            data={
                'first_name': 'Test',
                'last_name': 'Bidder',
                'username': 'testbidder1',
                'email': 'testbidder1@example.com',
                'department': 'Acme Supplies',
                'designation': 'Manager',
                'role_code': 'bidder',
                'password': 'StrongPass123!',
                'confirm_password': 'StrongPass123!',
                'cipa_document': (io.BytesIO(b'cipa-doc-content'), 'cipa.pdf'),
                'tax_certificate': (io.BytesIO(b'tax-doc-content'), 'tax_certificate.pdf'),
            },
            content_type='multipart/form-data',
        )

        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            user = User.query.filter_by(email='testbidder1@example.com').first()
            self.assertIsNotNone(user)
            self.assertFalse(user.is_active)
            docs = BidderComplianceDocument.query.filter_by(bidder_id=user.bidder_id).order_by(BidderComplianceDocument.document_type).all()
            self.assertEqual(len(docs), 2)
            self.assertEqual({doc.document_type for doc in docs}, {'cipa_equivalent', 'tax_certificate'})
            self.assertTrue(all(doc.status == 'pending' for doc in docs))

    def test_registration_blocks_when_one_required_document_is_missing(self):
        response = self.client.post(
            '/register',
            data={
                'first_name': 'Test',
                'last_name': 'Bidder',
                'username': 'testbidder2',
                'email': 'testbidder2@example.com',
                'department': 'Acme Supplies',
                'designation': 'Manager',
                'role_code': 'bidder',
                'password': 'StrongPass123!',
                'confirm_password': 'StrongPass123!',
                'cipa_document': (io.BytesIO(b'cipa-doc-content'), 'cipa.pdf'),
            },
            content_type='multipart/form-data',
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Please upload both required compliance documents', response.data)

    def test_youth_owned_payment_allows_optional_supporting_document(self):
        with self.app.app_context():
            role = Role.query.filter_by(code='bidder').first()
            bidder = Bidder(company_name='Youth Works', contact_email='youth@example.com', active=True, verified=True)
            db.session.add(bidder)
            db.session.flush()
            user = User(
                username='youthbidder', email='youth@example.com', first_name='Youth', last_name='Owner',
                role_id=role.id, bidder_id=bidder.id, is_active=True
            )
            user.set_password('StrongPass123!')
            db.session.add(user)
            procurement = Procurement(
                tender_number='TB-2026-999', title='Youth Support Tender', category='works', method='open_domestic',
                estimated_value=200000, procurement_entity='MOG', user_department='MOG', status='submission_open',
                created_by_id=1, tender_fee=5000.0
            )
            db.session.add(procurement)
            db.session.commit()

            with self.client.session_transaction() as sess:
                sess['_user_id'] = str(user.id)
                sess['_fresh'] = True

            response = self.client.post(
                f'/bidders/workspace/{procurement.id}',
                data={
                    'action': 'submit_payment',
                    'payment_reference': 'YOUTH-REF-1',
                    'amount': '2500',
                    'proof_file': (io.BytesIO(b'proof'), 'proof.pdf'),
                    'supporting_document': (io.BytesIO(b'youth-ownership-proof'), 'youth_support.pdf'),
                },
                content_type='multipart/form-data',
                follow_redirects=True,
            )
            self.assertEqual(response.status_code, 200)
            payment = BidderPayment.query.filter_by(payment_reference='YOUTH-REF-1', bidder_id=bidder.id).first()
            self.assertIsNotNone(payment)
            self.assertEqual(payment.amount, 2500.0)
            self.assertIsNotNone(payment.supporting_document_path)
            self.assertEqual(payment.supporting_document_filename, 'youth_support.pdf')


if __name__ == '__main__':
    unittest.main()
