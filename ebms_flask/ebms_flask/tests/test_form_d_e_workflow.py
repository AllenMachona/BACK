import io
import unittest

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.role import Role
from app.models.request import FormDRequest, FormERequest
from app.models.procurement import Procurement


class FormDWorkflowTests(unittest.TestCase):
    """Form D / Form E request-to-procurement workflow tests.

    Covers: the requester role restriction, the submission flow, the
    procurement queue access rules, the convert flow and the reject flow.
    Uses the same idempotent role/user bootstrap as the other test modules.
    """

    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            self.requester_role_id, self.proc_role_id, self.bidder_role_id = self._ensure_roles()
            self.requester_a = self._ensure_user('req_a_test', 'reqa@health.gov.bw',
                                                 'Anna', 'Requester', self.requester_role_id, 'Ministry of Health')
            self.requester_b = self._ensure_user('req_b_test', 'reqb@edu.gov.bw',
                                                 'Ben', 'Requester', self.requester_role_id, 'Ministry of Education')
            self.proc_user = self._ensure_user('proc_req_test', 'proc_req@gov.bw',
                                               'Carol', 'Procurement', self.proc_role_id, 'Procurement')
            self.bidder_user = self._ensure_user('bidder_req_test', 'bidder_req@company.bw',
                                                 'Dan', 'Bidder', self.bidder_role_id, None)
            self.requester_a_id = self.requester_a.id
            self.proc_user_id = self.proc_user.id

    # ------------------------------------------------------------------ setup
    def _ensure_roles(self):
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
# --------------------------------------------------------------- helpers

    def _submit_form_d(self, username):
        data = {
            'requisition_title': 'Medical-grade laboratory reagent supply',
            'category': 'supplies',
            'procurement_method': 'open_domestic',
            'estimated_value': '750000',
            'procurement_entity': 'Ministry of Health',
            'justification': 'Annual reagent restock for the Central Medical Stores.',
            'delivery_period': '60 days',
            'authorized_by': 'Dr. K. Mokgadi',
            'authorization_date': '2026-08-20',
            'signed_form_document': (io.BytesIO(b'%PDF-1.4 signed form d'), 'form_d_signed.pdf'),
        }
        self._login(username)
        return self.client.post('/requests/form-d', data=data,
                    content_type='multipart/form-data', follow_redirects=True)

    def _submit_form_e(self, username):
        data = {
            'specification_title': 'Solar water irrigation pumps',
            'category': 'supplies',
            'technical_specification': 'Twelve 45kW solar pumps with installation.',
            'budget_line': 'BUD-2026-114',
            'budget_allocated': '320000',
            'budget_status': 'available',
            'procurement_entity': 'Ministry of Agriculture',
            'clearance_authority': 'Ms. Finance Lead',
            'clearance_date': '2026-08-21',
            'signed_form_e_document': (io.BytesIO(b'%PDF-1.4 FORM E'), 'form_e_signed.pdf'),
        }
        self._login(username)
        return self.client.post('/requests/form-e', data=data,
                    content_type='multipart/form-data', follow_redirects=True)

    def _first_form_d_id(self):
        with self.app.app_context():
            req = FormDRequest.query.filter_by(requester_id=self.requester_a_id).first()
            return req.id if req else None

    # -------------------------------------------------------------- tests
    def test_requester_can_submit_form_d_and_form_e(self):
        resp = self._submit_form_d('req_a_test')
        self.assertEqual(resp.status_code, 200)
        resp_e = self._submit_form_e('req_a_test')
        self.assertEqual(resp_e.status_code, 200)

        with self.app.app_context():
            d_req = FormDRequest.query.filter_by(requester_id=self.requester_a_id).first()
            self.assertIsNotNone(d_req)
            self.assertEqual(d_req.status, 'submitted')
            self.assertEqual(d_req.category, 'supplies')
            self.assertEqual(float(d_req.estimated_value), 750000.0)
            self.assertTrue(d_req.has_signed_document())

            e_req = FormERequest.query.filter_by(requester_id=self.requester_a_id).first()
            self.assertIsNotNone(e_req)
            self.assertEqual(e_req.status, 'submitted')
            self.assertEqual(float(e_req.budget_allocated), 320000.0)
            self.assertTrue(e_req.has_signed_document())

    def test_requester_my_requests_shows_only_own(self):
        self._submit_form_d('req_a_test')

        self._login('req_a_test')
        resp = self.client.get('/requests/my')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Medical-grade laboratory reagent supply', resp.data)

    def test_requester_can_view_only_own_requests(self):
        self._submit_form_d('req_a_test')
        req_id = self._first_form_d_id()

        # Own detail -> 200
        self._login('req_a_test')
        resp = self.client.get(f'/requests/form-d/{req_id}')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Medical-grade laboratory reagent supply', resp.data)

        # Another requester's detail -> 403 (server-side IDOR guard)
        self._login('req_b_test')
        resp = self.client.get(f'/requests/form-d/{req_id}')
        self.assertEqual(resp.status_code, 403)

    def test_requester_blocked_from_procurement_queue(self):
        self._login('req_a_test')
        resp = self.client.get('/requests/')
        self.assertEqual(resp.status_code, 403)

    def test_bidder_blocked_from_procurement_queue(self):
        self._login('bidder_req_test')
        resp = self.client.get('/requests/')
        self.assertEqual(resp.status_code, 403)

    def test_procurement_user_can_view_queue_and_filters(self):
        self._submit_form_d('req_a_test')
        self._login('proc_req_test')

        resp = self.client.get('/requests/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Incoming Procurement Requests', resp.data)

        resp = self.client.get('/requests/?status=submitted&form_type=form_d')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Medical-grade laboratory reagent supply', resp.data)

        resp = self.client.get('/requests/?status=converted')
        self.assertEqual(resp.status_code, 200)

    def test_requester_cannot_convert_or_reject(self):
        self._submit_form_d('req_a_test')
        req_id = self._first_form_d_id()

        self._login('req_a_test')
        resp = self.client.post(f'/requests/form-d/{req_id}/convert')
        self.assertEqual(resp.status_code, 403)
        resp = self.client.post(f'/requests/form-d/{req_id}/reject', data={'reason': 'no budget'})
        self.assertEqual(resp.status_code, 403)

    def test_convert_form_d_creates_procurement_and_links(self):
        self._submit_form_d('req_a_test')
        with self.app.app_context():
            req = FormDRequest.query.filter_by(requester_id=self.requester_a_id).first()
            req_id = req.id
            signed_path = req.submitted_form_path
            signed_filename = req.submitted_form_filename

        self._login('proc_req_test')
        resp = self.client.post(f'/requests/form-d/{req_id}/convert')
        self.assertEqual(resp.status_code, 302)

        with self.app.app_context():
            updated = FormDRequest.query.get(req_id)
            self.assertEqual(updated.status, 'converted')
            self.assertIsNotNone(updated.procurement_id)
            proc = Procurement.query.get(updated.procurement_id)
            self.assertIsNotNone(proc)
            self.assertEqual(proc.status, 'draft')
            self.assertEqual(proc.title, 'Medical-grade laboratory reagent supply')
            self.assertEqual(proc.category, 'supplies')
            self.assertEqual(proc.method, 'open_domestic')
            self.assertEqual(float(proc.estimated_value), 750000.0)
            self.assertEqual(proc.form_d_file_path, signed_path)
            self.assertEqual(proc.form_d_filename, signed_filename)
            self.assertEqual(proc.created_by_id, self.proc_user_id)
            self.assertEqual(proc.user_department, 'Ministry of Health')

    def test_convert_form_e_creates_procurement_and_links(self):
        self._submit_form_e('req_a_test')
        with self.app.app_context():
            req = FormERequest.query.filter_by(requester_id=self.requester_a_id).first()
            req_id = req.id
            signed_path = req.submitted_form_path
            signed_filename = req.submitted_form_filename

        self._login('proc_req_test')
        resp = self.client.post(f'/requests/form-e/{req_id}/convert')
        self.assertEqual(resp.status_code, 302)

        with self.app.app_context():
            updated = FormERequest.query.get(req_id)
            self.assertEqual(updated.status, 'converted')
            self.assertIsNotNone(updated.procurement_id)
            proc = Procurement.query.get(updated.procurement_id)
            self.assertIsNotNone(proc)
            self.assertEqual(proc.title, 'Solar water irrigation pumps')
            self.assertEqual(float(proc.estimated_value), 320000.0)
            self.assertEqual(proc.form_e_file_path, signed_path)
            self.assertEqual(proc.form_e_filename, signed_filename)

    def test_reject_form_d_sets_status_and_reason(self):
        self._submit_form_d('req_a_test')
        req_id = self._first_form_d_id()

        self._login('proc_req_test')
        resp = self.client.post(f'/requests/form-d/{req_id}/reject',
                                data={'reason': 'Budget not cleared for this financial year.'})
        self.assertEqual(resp.status_code, 302)

        with self.app.app_context():
            updated = FormDRequest.query.get(req_id)
            self.assertEqual(updated.status, 'rejected')
            self.assertEqual(updated.rejection_reason, 'Budget not cleared for this financial year.')
            self.assertEqual(updated.rejected_by_id, self.proc_user_id)
            self.assertIsNotNone(updated.rejected_at)


if __name__ == '__main__':
    unittest.main()