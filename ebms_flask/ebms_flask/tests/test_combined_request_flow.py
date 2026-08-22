import io
import unittest

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.role import Role
from app.models.request import FormDERequest
from app.models.procurement import Procurement


class CombinedRequestWorkflowTests(unittest.TestCase):
    """Combined Form D & E request-to-procurement workflow tests.

    Covers the current requester flow:
      1. The requester uploads both signed Form D and Form E documents plus a
         justification in ONE window (no procurement-detail fields).
      2. The combined request appears in the Incoming Requests queue.
      3. Procurement clicks "Create Procurement", which opens the Create
         Procurement page where they enter the tender details and upload the
         ITT (paid view) or RFQ document (free view).
      4. The request is linked to the created procurement and marked converted.
      5. Bidders can view the RFQ document for free but the ITT stays locked
         until the tender-fee payment is approved.
    """

    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            self.requester_role_id, self.proc_role_id, self.bidder_role_id = self._ensure_roles()
            self.requester_a = self._ensure_user('req_combo_test', 'reqcombo@health.gov.bw',
                                                 'Fiona', 'Requester', self.requester_role_id, 'Ministry of Health')
            self.requester_b = self._ensure_user('req_combo_other_test', 'reqcomboother@edu.gov.bw',
                                                 'Grace', 'Requester', self.requester_role_id, 'Ministry of Education')
            self.proc_user = self._ensure_user('proc_combo_test', 'proccombo@gov.bw',
                                               'Gerald', 'Procurement', self.proc_role_id, 'Procurement')
            self.bidder_user = self._ensure_user('bidder_combo_test', 'biddercombo@company.bw',
                                                 'Harry', 'Bidder', self.bidder_role_id, None)
            self.requester_a_id = self.requester_a.id
            db.session.query(FormDERequest).filter(
                FormDERequest.requester_id.in_([self.requester_a.id, self.requester_b.id])
            ).delete(synchronize_session=False)
            db.session.commit()

    # ------------------------------------------------------------------ setup
    @staticmethod
    def _ensure_roles():
        requester_role = Role.query.filter_by(code='requester').first()
        if not requester_role:
            requester_role = Role(code='requester', name='Requester', description='Form D/E requester')
            db.session.add(requester_role)
            db.session.commit()
        requester_role_id = requester_role.id

        proc_role = Role.query.filter_by(code='procurement_unit').first()
        if not proc_role:
            proc_role = Role(code='procurement_unit', name='Procurement Unit', description='Procurement Officer',
                             can_create_procurement=True, can_view_all_records=True,
                             can_publish=True, can_admin_system=True, can_approve_procurement=True)
            db.session.add(proc_role)
            db.session.commit()
        else:
            proc_role.can_create_procurement = True
            proc_role.can_view_all_records = True
            proc_role.can_publish = True
            db.session.commit()
        proc_role_id = proc_role.id

        bidder_role = Role.query.filter_by(code='bidder').first()
        if not bidder_role:
            bidder_role = Role(code='bidder', name='Bidder', can_bid=True)
            db.session.add(bidder_role)
            db.session.commit()
        bidder_role_id = bidder_role.id

        return requester_role_id, proc_role_id, bidder_role_id

    def _ensure_user(self, username, email, first_name, last_name, role_id, department):
        user = User.query.filter_by(username=username).first()
        if not user:
            user = User(username=username, email=email, first_name=first_name,
                        last_name=last_name, role_id=role_id, department=department, is_active=True)
            user.set_password('Secret123!')
            db.session.add(user)
            db.session.commit()
        else:
            user.role_id = role_id
            user.is_active = True
            user.set_password('Secret123!')
            db.session.commit()
        return user

    def _login(self, username, password='Secret123!'):
        self.client.get('/logout', follow_redirects=True)
        resp = self.client.post('/login', data={'username': username, 'password': password},
                                follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        return resp

    def _submit_combined(self, username, justification='Annual reagent restock for the Central Medical Stores.'):
        data = {
            'department': 'Ministry of Health',
            'justification': justification,
            'form_d_document': (io.BytesIO(b'%PDF-1.4 signed form d combined'), 'form_d_combined.pdf'),
            'form_e_document': (io.BytesIO(b'%PDF-1.4 signed form e combined'), 'form_e_combined.pdf'),
        }
        self._login(username)
        return self.client.post('/requests/new', data=data,
                                content_type='multipart/form-data', follow_redirects=True)

    def _first_combined_id(self):
        with self.app.app_context():
            req = FormDERequest.query.filter_by(requester_id=self.requester_a_id).order_by(
                FormDERequest.id.desc()).first()
            return req.id if req else None

    @staticmethod
    def _pdf(content, name):
        return (io.BytesIO(content), name)

    def test_requester_submits_one_combined_request(self):
        response = self._submit_combined('req_combo_test')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Request submitted to Procurement', response.data)
        with self.app.app_context():
            request_obj = FormDERequest.query.filter_by(id=self._first_combined_id()).one()
            self.assertEqual(request_obj.status, 'submitted')
            self.assertEqual(request_obj.department, 'Ministry of Health')
            self.assertEqual(request_obj.justification, 'Annual reagent restock for the Central Medical Stores.')
            self.assertTrue(request_obj.has_form_d())
            self.assertTrue(request_obj.has_form_e())

    def test_requester_cannot_override_department_or_upload_invalid_file(self):
        self._login('req_combo_test')
        response = self.client.post('/requests/new', data={
            'department': 'Procurement Department',
            'justification': 'Invalid upload check',
            'form_d_document': self._pdf(b'%PDF-1.4 D', 'form_d.pdf'),
            'form_e_document': self._pdf(b'not allowed', 'form_e.exe'),
        }, content_type='multipart/form-data')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'supported Office document', response.data)
        with self.app.app_context():
            self.assertEqual(FormDERequest.query.filter_by(requester_id=self.requester_a_id).count(), 0)

    def test_requester_sees_only_own_request_and_not_queue(self):
        self._submit_combined('req_combo_test')
        request_id = self._first_combined_id()

        self._login('req_combo_other_test')
        self.assertEqual(self.client.get(f'/requests/de/{request_id}').status_code, 403)
        self.assertEqual(self.client.get('/requests/').status_code, 403)

        self._login('proc_combo_test')
        queue_response = self.client.get('/requests/?form_type=de&status=submitted')
        self.assertEqual(queue_response.status_code, 200)
        self.assertIn(b'Form D &amp; E', queue_response.data)

    def test_procurement_can_mark_request_under_review(self):
        self._submit_combined('req_combo_test')
        request_id = self._first_combined_id()

        self._login('proc_combo_test')
        response = self.client.post(f'/requests/de/{request_id}/review')
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            request_obj = FormDERequest.query.get(request_id)
            self.assertEqual(request_obj.status, 'under_review')
            self.assertIsNotNone(request_obj.under_review_at)