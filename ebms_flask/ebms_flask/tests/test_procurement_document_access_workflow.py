import io
import os
import unittest
import uuid
from datetime import datetime

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.role import Role
from app.models.bidder import Bidder
from app.models.procurement import Procurement
from app.models.payment import BidderPayment, BidderDocumentAccess
from app.models.communication import Communication
from app.models.audit import AuditLog
from app.models.notification import Notification


class ProcurementDocumentAccessWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            # Clean / ensure base roles
            self._ensure_test_users_and_roles()

    def _ensure_test_users_and_roles(self):
        # 1. Procurement Officer
        proc_role = Role.query.filter_by(code='procurement_unit').first()
        if not proc_role:
            proc_role = Role(code='procurement_unit', name='Procurement Unit', description='Procurement Officer',
                             can_create_procurement=True, can_approve_procurement=True,
                             can_publish=True, can_admin_system=True, can_view_all_records=True)
            db.session.add(proc_role)
            db.session.commit()
        else:
            proc_role.can_create_procurement = True
            proc_role.can_approve_procurement = True
            proc_role.can_publish = True
            proc_role.can_admin_system = True
            proc_role.can_view_all_records = True
            db.session.commit()

        self.proc_user = User.query.filter_by(username='proc_officer_test').first()
        if not self.proc_user:
            self.proc_user = User(
                username='proc_officer_test',
                email='proc_test@gov.bw',
                first_name='Kagiso',
                last_name='Procurement',
                role_id=proc_role.id,
                is_active=True
            )
            self.proc_user.set_password('Secret123!')
            db.session.add(self.proc_user)
            db.session.commit()
        else:
            self.proc_user.role_id = proc_role.id
            self.proc_user.is_active = True
            self.proc_user.set_password('Secret123!')
            db.session.commit()

        self.proc_user_id = self.proc_user.id

        # 2. Bidder Role
        bidder_role = Role.query.filter_by(code='bidder').first()
        if not bidder_role:
            bidder_role = Role(code='bidder', name='Registered Bidder', description='Bidder Role',
                               can_create_procurement=False, can_approve_procurement=False, can_bid=True)
            db.session.add(bidder_role)
            db.session.commit()
        else:
            bidder_role.can_bid = True
            db.session.commit()

        # 3. Bidder A
        self.bidder_company_a = Bidder.query.filter_by(company_name='Alpha Construction Ltd').first()
        if not self.bidder_company_a:
            self.bidder_company_a = Bidder(
                company_name='Alpha Construction Ltd',
                contact_email='alpha@construct.bw',
                ppra_registration_number=f'PPRA-ALPHA-{uuid.uuid4().hex[:4].upper()}',
                active=True,
                verified=True
            )
            db.session.add(self.bidder_company_a)
            db.session.commit()

        self.bidder_company_a_id = self.bidder_company_a.id

        self.bidder_user_a = User.query.filter_by(username='bidder_alpha_test').first()
        if not self.bidder_user_a:
            self.bidder_user_a = User(
                username='bidder_alpha_test',
                email='alpha@construct.bw',
                first_name='Tebogo',
                last_name='Alpha',
                role_id=bidder_role.id,
                bidder_id=self.bidder_company_a.id,
                is_active=True
            )
            self.bidder_user_a.set_password('Secret123!')
            db.session.add(self.bidder_user_a)
            db.session.commit()

        # 4. Bidder B
        self.bidder_company_b = Bidder.query.filter_by(company_name='Beta Builders Ltd').first()
        if not self.bidder_company_b:
            self.bidder_company_b = Bidder(
                company_name='Beta Builders Ltd',
                contact_email='beta@builders.bw',
                ppra_registration_number=f'PPRA-BETA-{uuid.uuid4().hex[:4].upper()}',
                active=True,
                verified=True
            )
            db.session.add(self.bidder_company_b)
            db.session.commit()

        self.bidder_company_b_id = self.bidder_company_b.id

        self.bidder_user_b = User.query.filter_by(username='bidder_beta_test').first()
        if not self.bidder_user_b:
            self.bidder_user_b = User(
                username='bidder_beta_test',
                email='beta@builders.bw',
                first_name='Lesedi',
                last_name='Beta',
                role_id=bidder_role.id,
                bidder_id=self.bidder_company_b.id,
                is_active=True
            )
            self.bidder_user_b.set_password('Secret123!')
            db.session.add(self.bidder_user_b)
            db.session.commit()

    def _login(self, username, password='Secret123!'):
        self.client.get('/logout', follow_redirects=True)
        resp = self.client.post('/login', data={
            'username': username,
            'password': password
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        return resp

    def test_complete_end_to_end_procurement_document_access_workflow(self):
        """
        Comprehensive test running through the full lifecycle:
        1. Create procurement with Form D & Form E.
        2. Upload RFCE & ITT documents and set tender fee.
        3. Verify Bidders cannot access Form D or Form E (403 Forbidden).
        4. Verify Bidders cannot access RFCE or ITT before payment approval (403 Forbidden).
        5. Bidder A submits proof of payment (Status -> pending).
        6. Procurement reviews and requests resubmission (Status -> resubmission_required).
        7. Bidder A resubmits corrected proof of payment (Status -> pending).
        8. Procurement approves Bidder A payment (Status -> approved, document access granted).
        9. Bidder A can now successfully download and view RFCE and ITT.
        10. Bidder B attempts to download RFCE and ITT -> HTTP 403 Forbidden (Isolation).
        11. Procurement revokes Bidder A access -> Subsequent access returns 403 Forbidden.
        12. Verify audit logs and notifications generated.
        """
        # Step 1: Procurement Officer creates procurement with Form D, Form E, RFCE, ITT
        self._login('proc_officer_test')

        unique_tender_num = f"TB-TEST-DOCS-{uuid.uuid4().hex[:8].upper()}"
        create_data = {
            'tender_number': unique_tender_num,
            'title': 'Hospital Solar Power Infrastructure',
            'description': 'Supply, installation and maintenance of hospital solar power grids.',
            'category': 'works',
            'ppra_code': '100',
            'ppra_sub_code': '01',
            'procurement_entity': 'Ministry of Health',
            'method': 'open_domestic',
            'evaluation_method': 'quality_cost',
            'envelope_type': 'dual',
            'estimated_value': '8500000.00',
            'tender_fee': '500.00',
            'advertisement_document': (io.BytesIO(b'%PDF-1.4 Public Advertisement Notice'), 'advertisement.pdf'),
            'form_d_document': (io.BytesIO(b'%PDF-1.4 Confidential Form D Requisition Data'), 'form_d_requisition.pdf'),
            'form_e_document': (io.BytesIO(b'%PDF-1.4 Confidential Form E Specification Data'), 'form_e_spec.pdf'),
            'rfce_document': (io.BytesIO(b'%PDF-1.4 Official RFCE Eligibility Document'), 'rfce_hospital_solar.pdf'),
            'itt_document': (io.BytesIO(b'%PDF-1.4 Official ITT Instructions and BOQ'), 'itt_hospital_solar.pdf'),
        }

        resp = self.client.post('/procurements/create', data=create_data, content_type='multipart/form-data', follow_redirects=True)
        if b'Hospital Solar Power Infrastructure' not in resp.data:
            print("CREATE RESPONSE STATUS:", resp.status_code)
            print("CREATE RESPONSE HTML:", resp.data.decode('utf-8', errors='ignore')[:1000])

        with self.app.app_context():
            proc = Procurement.query.filter_by(title='Hospital Solar Power Infrastructure').order_by(Procurement.id.desc()).first()
            self.assertIsNotNone(proc)
            self.assertTrue(proc.has_form_d())
            self.assertTrue(proc.has_form_e())
            self.assertTrue(proc.has_rfce())
            self.assertTrue(proc.has_itt())
            self.assertEqual(float(proc.tender_fee), 500.0)

            # Move procurement status to 'submission_open' so bidders can access the workspace
            proc.status = 'submission_open'
            db.session.commit()
            proc_id = proc.id

        # Step 2: Test Form D & Form E internal access (Procurement officer CAN download)
        resp = self.client.get(f'/procurements/{proc_id}/tender-docs/form_d/download')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Confidential Form D', resp.data)

        resp = self.client.get(f'/procurements/{proc_id}/tender-docs/form_e/download')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Confidential Form E', resp.data)

        # Step 3: Login as Bidder A -> Attempt direct access to Form D & Form E (MUST be 403 Forbidden)
        self._login('bidder_alpha_test')

        resp = self.client.get(f'/procurements/{proc_id}/tender-docs/form_d/download')
        self.assertEqual(resp.status_code, 403)

        resp = self.client.get(f'/procurements/{proc_id}/tender-docs/form_e/download')
        self.assertEqual(resp.status_code, 403)

        # Step 4: Login as Bidder A -> Attempt direct access to RFCE & ITT BEFORE payment (MUST be 403 Forbidden)
        resp = self.client.get(f'/procurements/{proc_id}/tender-docs/rfce/download')
        self.assertEqual(resp.status_code, 403)

        resp = self.client.get(f'/procurements/{proc_id}/tender-docs/itt/download')
        self.assertEqual(resp.status_code, 403)

        resp = self.client.get(f'/procurements/{proc_id}/tender-docs/rfce/view')
        self.assertEqual(resp.status_code, 403)

        # Step 5: Bidder A submits Proof of Payment
        payment_data = {
            'action': 'submit_payment',
            'amount': '500.00',
            'payment_reference': 'EFT-STANBIC-998811',
            'proof_file': (io.BytesIO(b'%PDF-1.4 Official Bank Deposit Receipt Slip'), 'bank_deposit_slip.pdf')
        }
        resp = self.client.post(f'/bidders/workspace/{proc_id}', data=payment_data, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Payment proof submitted successfully', resp.data)

        with self.app.app_context():
            payment = BidderPayment.query.filter_by(procurement_id=proc_id, payment_reference='EFT-STANBIC-998811').first()
            self.assertIsNotNone(payment)
            self.assertEqual(payment.status, 'pending')
            payment_id = payment.id

        # Bidder A still cannot access RFCE/ITT while status is pending
        resp = self.client.get(f'/procurements/{proc_id}/tender-docs/rfce/download')
        self.assertEqual(resp.status_code, 403)

        # Step 6: Procurement reviews payment and requests Resubmission
        self._login('proc_officer_test')

        # View payment proof file
        resp = self.client.get(f'/procurements/payments/{payment_id}/proof')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Official Bank Deposit Receipt Slip', resp.data)

        # Request resubmission
        resp = self.client.post(f'/procurements/payments/{payment_id}/verify', data={
            'action': 'request_resubmission',
            'reason': 'Deposit slip date stamp is unclear. Please re-upload high-resolution receipt.'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        with self.app.app_context():
            payment = BidderPayment.query.get(payment_id)
            self.assertEqual(payment.status, 'resubmission_required')
            self.assertIn('Deposit slip date stamp is unclear', payment.notes)

        # Bidder A still cannot access RFCE/ITT
        self._login('bidder_alpha_test')
        resp = self.client.get(f'/procurements/{proc_id}/tender-docs/rfce/download')
        self.assertEqual(resp.status_code, 403)

        # Step 7: Bidder A resubmits corrected payment proof
        resubmit_data = {
            'action': 'submit_payment',
            'amount': '500.00',
            'payment_reference': 'EFT-STANBIC-998811-CORRECTED',
            'proof_file': (io.BytesIO(b'%PDF-1.4 Clear HD Bank Deposit Receipt Slip with Stamp'), 'bank_slip_hd.pdf')
        }
        resp = self.client.post(f'/bidders/workspace/{proc_id}', data=resubmit_data, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        with self.app.app_context():
            payment = BidderPayment.query.filter_by(procurement_id=proc_id, bidder_id=self.bidder_company_a.id).first()
            self.assertEqual(payment.status, 'pending')
            self.assertEqual(payment.payment_reference, 'EFT-STANBIC-998811-CORRECTED')

        # Step 8: Procurement Approves Payment & Grants Document Access
        self._login('proc_officer_test')

        resp = self.client.post(f'/procurements/payments/{payment_id}/verify', data={
            'action': 'approve',
            'reason': 'Bank receipt verified with Finance.'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'approved', resp.data.lower())

        with self.app.app_context():
            payment = BidderPayment.query.get(payment_id)
            self.assertEqual(payment.status, 'approved')

            access = BidderDocumentAccess.query.filter_by(procurement_id=proc_id, bidder_id=self.bidder_company_a.id, status='active').all()
            self.assertTrue(len(access) >= 1)

        # Step 9: Bidder A now has FULL UNLOCKED ACCESS to RFCE and ITT
        self._login('bidder_alpha_test')

        resp = self.client.get(f'/procurements/{proc_id}/tender-docs/rfce/download')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Official RFCE Eligibility Document', resp.data)

        resp = self.client.get(f'/procurements/{proc_id}/tender-docs/itt/download')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Official ITT Instructions and BOQ', resp.data)

        resp = self.client.get(f'/procurements/{proc_id}/tender-docs/rfce/view')
        self.assertEqual(resp.status_code, 200)

        # Step 10: Bidder B Isolation Check -> Bidder B MUST STILL GET 403 Forbidden!
        self._login('bidder_beta_test')

        resp = self.client.get(f'/procurements/{proc_id}/tender-docs/rfce/download')
        self.assertEqual(resp.status_code, 403)

        resp = self.client.get(f'/procurements/{proc_id}/tender-docs/itt/download')
        self.assertEqual(resp.status_code, 403)

        # Bidder B also cannot download Bidder A's payment proof
        resp = self.client.get(f'/procurements/payments/{payment_id}/proof')
        self.assertEqual(resp.status_code, 403)

        # Step 11: Revocation Flow -> Procurement revokes Bidder A's access
        self._login('proc_officer_test')

        resp = self.client.post(f'/procurements/payments/{payment_id}/verify', data={
            'action': 'revoke',
            'reason': 'Administrative revocation per oversight audit.'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # Bidder A now gets 403 Forbidden again
        self._login('bidder_alpha_test')
        resp = self.client.get(f'/procurements/{proc_id}/tender-docs/rfce/download')
        self.assertEqual(resp.status_code, 403)

        # Step 12: Check Audit Logs and Notifications
        with self.app.app_context():
            logs = AuditLog.query.all()
            actions = [log.action for log in logs]
            self.assertIn('PAYMENT_PROOF_SUBMITTED', actions)
            self.assertIn('PAYMENT_APPROVED', actions)
            self.assertIn('DOCUMENT_ACCESS_GRANTED', actions)
            self.assertIn('DOCUMENT_ACCESS_REVOKED', actions)

            notifs = Notification.query.all()
            self.assertTrue(len(notifs) >= 2)

    def test_payment_rejection_flow_and_reapplication(self):
        """Test payment rejection with explicit reasons and verify documents remain locked."""
        # 1. Setup a published tender with RFCE/ITT
        with self.app.app_context():
            proc = Procurement(
                tender_number=f"TB-REJECT-{uuid.uuid4().hex[:6].upper()}",
                title='Road Construction Quality Audit',
                category='services',
                method='open_domestic',
                estimated_value=1200000,
                tender_fee=300.0,
                rfce_file_path='uploads/test_rfce.pdf',
                rfce_filename='test_rfce.pdf',
                itt_file_path='uploads/test_itt.pdf',
                itt_filename='test_itt.pdf',
                status='submission_open',
                created_by_id=self.proc_user_id
            )
            db.session.add(proc)
            db.session.commit()
            proc_id = proc.id

        # 2. Bidder A submits payment proof
        self._login('bidder_alpha_test')
        payment_data = {
            'action': 'submit_payment',
            'amount': '300.00',
            'payment_reference': 'EFT-REJECT-TEST-001',
            'proof_file': (io.BytesIO(b'%PDF-1.4 Fake or unreadable slip'), 'fake_slip.pdf')
        }
        resp = self.client.post(f'/bidders/workspace/{proc_id}', data=payment_data, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        with self.app.app_context():
            payment = BidderPayment.query.filter_by(procurement_id=proc_id, payment_reference='EFT-REJECT-TEST-001').first()
            self.assertIsNotNone(payment)
            payment_id = payment.id

        # 3. Procurement rejects payment
        self._login('proc_officer_test')
        resp = self.client.post(f'/procurements/payments/{payment_id}/verify', data={
            'action': 'reject',
            'reason': 'Deposit slip is unreadable and amount does not match bank transaction record.'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'rejected', resp.data.lower())

        with self.app.app_context():
            payment = BidderPayment.query.filter_by(id=payment_id).first()
            self.assertEqual(payment.status, 'rejected')
            self.assertIn('Deposit slip is unreadable', payment.notes)

        # 4. Bidder A attempts to access RFCE -> MUST get 403 Forbidden
        self._login('bidder_alpha_test')
        resp = self.client.get(f'/procurements/{proc_id}/tender-docs/rfce/download')
        self.assertEqual(resp.status_code, 403)

    def test_bidders_cannot_view_procurement_details_or_docs_before_payment_approval(self):
        """Bidder workspace and bidder-facing procurement docs must stay locked until payment is approved."""
        with self.app.app_context():
            proc = Procurement(
                tender_number=f"TB-LOCK-{uuid.uuid4().hex[:6].upper()}",
                title='Locked Tender Access Control',
                category='goods',
                method='open_domestic',
                estimated_value=900000,
                tender_fee=250.0,
                status='submission_open',
                created_by_id=self.proc_user_id
            )
            db.session.add(proc)
            db.session.commit()
            proc_id = proc.id

            notice = Communication(
                procurement_id=proc_id,
                type='advertisement',
                content='First bidder notice',
                from_bidder_id=None,
                is_public=True,
                original_filename='notice.pdf',
                file_path='uploads/test_notice.pdf'
            )
            db.session.add(notice)
            db.session.commit()
            notice_id = notice.id

        self._login('bidder_alpha_test')

        resp = self.client.get(f'/bidders/workspace/{proc_id}')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b'Official Tender Addenda &amp; Notices', resp.data)
        self.assertNotIn(b'View Document', resp.data)

        resp = self.client.get(f'/procurements/{proc_id}/documents/{notice_id}/download')
        self.assertEqual(resp.status_code, 403)

    def test_procurement_officer_upload_replacement_documents(self):
        """Test Procurement uploading or replacing Form D, Form E, RFCE, and ITT."""
        with self.app.app_context():
            proc = Procurement(
                tender_number=f"TB-UPLOAD-{uuid.uuid4().hex[:6].upper()}",
                title='Water Treatment Chemical Supply',
                category='supplies',
                method='open_domestic',
                estimated_value=3500000,
                tender_fee=150.0,
                status='draft',
                created_by_id=self.proc_user_id
            )
            db.session.add(proc)
            db.session.commit()
            proc_id = proc.id

        self._login('proc_officer_test')
        upload_data = {
            'form_d_document': (io.BytesIO(b'%PDF-1.4 Form D Requisition V2'), 'form_d_v2.pdf'),
            'form_e_document': (io.BytesIO(b'%PDF-1.4 Form E Spec V2'), 'form_e_v2.pdf'),
            'rfce_document': (io.BytesIO(b'%PDF-1.4 RFCE Addendum V2'), 'rfce_v2.pdf'),
            'itt_document': (io.BytesIO(b'%PDF-1.4 ITT Complete Pack V2'), 'itt_v2.pdf'),
            'tender_fee': '250.00'
        }
        resp = self.client.post(f'/procurements/{proc_id}/upload-documents', data=upload_data, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        with self.app.app_context():
            updated_proc = Procurement.query.filter_by(id=proc_id).first()
            self.assertTrue(updated_proc.has_form_d())
            self.assertTrue(updated_proc.has_form_e())
            self.assertTrue(updated_proc.has_rfce())
            self.assertTrue(updated_proc.has_itt())
            self.assertEqual(float(updated_proc.tender_fee), 250.0)

    def test_payment_verifications_global_queue_filters_and_access_control(self):
        """Test global payment queue access: Procurement allowed, Bidder forbidden (403)."""
        # Bidder access MUST be blocked (403)
        self._login('bidder_alpha_test')
        resp = self.client.get('/procurements/payment-verifications')
        self.assertEqual(resp.status_code, 403)

        # Procurement access MUST succeed (200) and support status filter query params
        self._login('proc_officer_test')
        resp = self.client.get('/procurements/payment-verifications?status=all')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Bidder Payment Verifications', resp.data)

        resp = self.client.get('/procurements/payment-verifications?status=pending')
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get('/procurements/payment-verifications?status=approved')
        self.assertEqual(resp.status_code, 200)


if __name__ == '__main__':
    unittest.main()
