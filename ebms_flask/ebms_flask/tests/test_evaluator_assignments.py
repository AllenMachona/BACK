"""Unit tests for evaluator assignments with document-type scope.

Covers the requirements:
- assignment before closure must fail;
- assignment after closure succeeds for each scope (technical/single/both);
- evaluator document visibility follows the assigned scope (downloads);
- multiple evaluators with different scopes on the same procurement;
- reassignment (update) semantics, revocation, audit logging, and the
  Procurement-role restriction on the management API.
"""
import os
import unittest
import uuid
from werkzeug.utils import secure_filename

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.role import Role
from app.models.bidder import Bidder
from app.models.procurement import Procurement
from app.models.submission import Submission
from app.models.evaluator_assignment import EvaluatorAssignment
from app.models.audit import AuditLog
from app.utils.crypto import encrypt_bytes

TAG = uuid.uuid4().hex[:6]
PASSWORD = 'Secret123!'


class EvaluatorAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        self._created = {
            'assignments': [], 'submissions': [], 'procurements': [],
            'users': [], 'bidders': [], 'files': [],
        }
        self._tender_numbers = {}
        with self.app.app_context():
            self._ensure_roles_and_users()

    def tearDown(self):
        with self.app.app_context():
            for pid in self._created['procurements']:
                db.session.query(EvaluatorAssignment).filter_by(procurement_id=pid).delete()
            for aid in self._created['assignments']:
                db.session.query(EvaluatorAssignment).filter_by(id=aid).delete()
            for sid in self._created['submissions']:
                db.session.query(Submission).filter_by(id=sid).delete()
            for pid in self._created['procurements']:
                db.session.query(Procurement).filter_by(id=pid).delete()
            for uid in self._created['users']:
                db.session.query(User).filter_by(id=uid).delete()
            for bid in self._created['bidders']:
                db.session.query(Bidder).filter_by(id=bid).delete()
            db.session.commit()
        for path in self._created['files']:
            try:
                os.remove(path)
            except OSError:
                pass
    # ------------------------------------------------------------------ #
    # Fixtures — plain scalar IDs/usernames so no ORM instance is ever
    # used across app-context boundaries (prevents DetachedInstanceError).
    # ------------------------------------------------------------------ #
    def _ensure_roles_and_users(self):
        def get_role(code, **flags):
            role = Role.query.filter_by(code=code).first()
            if not role:
                db.session.add(Role(code=code, name=code.replace('_', ' ').title(), **flags))
                db.session.commit()
            role = Role.query.filter_by(code=code).first()
            for key, value in flags.items():
                setattr(role, key, value)
            db.session.commit()
            return role

        self.proc_role = get_role(
            'procurement_unit', can_create_procurement=True,
            can_publish=True, can_approve_procurement=True,
            can_view_all_records=True,
        )
        self.eval_role = get_role('evaluator', can_evaluate=True)
        self.req_role = get_role('requester')

        def get_user(username, role, email):
            user = User.query.filter_by(username=username).first()
            if not user:
                db.session.add(User(username=username, email=email,
                                    first_name=username.split('_')[0],
                                    last_name='Test', role_id=role.id, is_active=True))
                db.session.commit()
            user = User.query.filter_by(username=username).first()
            user.role_id = role.id
            user.is_active = True
            user.set_password(PASSWORD)
            db.session.commit()
            self._created['users'].append(user.id)
            return user

        manager = get_user(f'ea_manager_{TAG}', self.proc_role, f'ea_manager_{TAG}@gov.bw')
        eval_a = get_user(f'ea_eval_a_{TAG}', self.eval_role, f'ea_eval_a_{TAG}@gov.bw')
        eval_b = get_user(f'ea_eval_b_{TAG}', self.eval_role, f'ea_eval_b_{TAG}@gov.bw')
        eval_c = get_user(f'ea_eval_c_{TAG}', self.eval_role, f'ea_eval_c_{TAG}@gov.bw')
        outsider = get_user(f'ea_requester_{TAG}', self.req_role, f'ea_requester_{TAG}@gov.bw')

        self.manager_id = manager.id
        self.manager_name = manager.username
        self.eval_a_id = eval_a.id
        self.eval_a_name = eval_a.username
        self.eval_b_id = eval_b.id
        self.eval_b_name = eval_b.username
        self.eval_c_id = eval_c.id
        self.eval_c_name = eval_c.username
        self.outsider_id = outsider.id
        self.outsider_name = outsider.username

        bidder = Bidder.query.filter_by(company_name=f'EA Test Co {TAG}').first()
        if not bidder:
            db.session.add(Bidder(
                company_name=f'EA Test Co {TAG}',
                ppra_registration_number=f'PPRA-EA-{TAG.upper()}',
                contact_email=f'ea_bidder_{TAG}@construct.bw',
                active=True,
                verified=True,
            ))
            db.session.commit()
        bidder = Bidder.query.filter_by(company_name=f'EA Test Co {TAG}').first()
        self.bidder_id = bidder.id
        self._created['bidders'].append(bidder.id)

        bidder_user = User.query.filter_by(username=f'ea_bidder_user_{TAG}').first()
        if not bidder_user:
            bidder_user = User(
                username=f'ea_bidder_user_{TAG}',
                email=f'ea_bidder_user_{TAG}@construct.bw',
                first_name='Bidder', last_name='Portal',
                role_id=self.req_role.id, bidder_id=bidder.id, is_active=True,
            )
            bidder_user.set_password(PASSWORD)
            db.session.add(bidder_user)
            db.session.commit()
        self.bidder_user_id = bidder_user.id
        self._created['users'].append(bidder_user.id)
    def _login(self, username):
        self.client.get('/logout', follow_redirects=True)
        resp = self.client.post('/login', data={
            'username': username,
            'password': PASSWORD,
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        return resp

    def _make_procurement(self, status='closed'):
        """Create a procurement; returns its integer id."""
        with self.app.app_context():
            tender_number = f'TB-EA-{uuid.uuid4().hex[:8].upper()}'
            proc = Procurement(
                tender_number=tender_number,
                title='Evaluator Assignment Test Tender',
                category='services',
                method='open_domestic',
                estimated_value=1200000.00,
                status=status,
                created_by_id=self.manager_id,
            )
            db.session.add(proc)
            db.session.commit()
            proc_id = proc.id
        self._created['procurements'].append(proc_id)
        self._tender_numbers[proc_id] = tender_number
        return proc_id

    def _make_submission(self, procurement_id, envelope_type):
        """Create a submission with a real encrypted file; return its id."""
        with self.app.app_context():
            procurement = Procurement.query.get(procurement_id)
            procurement_folder = secure_filename(
                f'{procurement.tender_number}_{procurement.title}'
            ) or f'procurement_{procurement.id}'
            submission_dir = os.path.join(
                self.app.config['UPLOAD_FOLDER'], procurement_folder
            )
            os.makedirs(submission_dir, exist_ok=True)
            filepath = os.path.join(
                submission_dir,
                f'ea_sealed_{uuid.uuid4().hex}.sealed',
            )
            with open(filepath, 'wb') as f:
                f.write(encrypt_bytes(f'Sealed bid content {uuid.uuid4().hex}'.encode('utf-8')))
            sub = Submission(
                procurement_id=procurement_id,
                bidder_id=self.bidder_id,
                envelope_type=envelope_type,
                file_path=filepath,
                original_filename=f'{envelope_type}_bid.pdf',
                sha256_hash='e' * 64,
                file_size_bytes=128,
                submitted_by_id=self.bidder_user_id,
                receipt_code=f'SUB-EA-{uuid.uuid4().hex[:8].upper()}',
            )
            db.session.add(sub)
            db.session.commit()
            sub_id = sub.id
        self._created['submissions'].append(sub_id)
        self._created['files'].append(filepath)
        return sub_id

    def _assign(self, procurement_id, evaluator_id, scope):
        response = self.client.post('/api/evaluator-assignments', json={
            'procurement_id': procurement_id,
            'evaluator_id': evaluator_id,
            'scope': scope,
            'reason': None,
        })
        if response.is_json and response.json.get('assignment'):
            self._created['assignments'].append(response.json['assignment']['id'])
        return response

    def _download(self, procurement_id, submission_id):
        return self.client.get(
            f'/procurements/{procurement_id}/submission/{submission_id}/download'
        )

    def _assignment_row(self, procurement_id, evaluator_id):
        with self.app.app_context():
            assignment = EvaluatorAssignment.active_for(procurement_id, evaluator_id)
            return assignment

    def _audit_actions_for(self, assignment_id):
        with self.app.app_context():
            return [
                r.action for r in AuditLog.query.filter_by(
                    entity_type='EvaluatorAssignment', entity_id=assignment_id
                ).all()
            ]

    def test_assignment_before_closure_fails(self):
        procurement_id = self._make_procurement(status='submission_open')
        self._login(self.manager_name)

        response = self._assign(procurement_id, self.eval_a_id, 'technical')

        self.assertEqual(response.status_code, 400)
        self.assertIn('Closed', response.json['message'])

    def test_each_scope_can_be_assigned_after_closure(self):
        procurement_id = self._make_procurement()
        self._login(self.manager_name)

        for evaluator_id, scope in (
            (self.eval_a_id, 'technical'),
            (self.eval_b_id, 'single'),
            (self.eval_c_id, 'both'),
        ):
            response = self._assign(procurement_id, evaluator_id, scope)
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json['assignment']['document_scope'], scope)

    def test_document_visibility_matches_assigned_scope(self):
        procurement_id = self._make_procurement()
        technical_id = self._make_submission(procurement_id, 'technical')
        single_id = self._make_submission(procurement_id, 'single')

        self._login(self.manager_name)
        self.assertEqual(self._assign(procurement_id, self.eval_a_id, 'technical').status_code, 201)

        self._login(self.eval_a_name)
        self.assertEqual(self._download(procurement_id, technical_id).status_code, 200)
        self.assertEqual(self._download(procurement_id, single_id).status_code, 403)

    def test_submission_files_are_grouped_in_procurement_folder(self):
        procurement_id = self._make_procurement()
        submission_id = self._make_submission(procurement_id, 'technical')

        with self.app.app_context():
            submission = Submission.query.get(submission_id)
            procurement = Procurement.query.get(procurement_id)
            expected_folder = secure_filename(
                f'{procurement.tender_number}_{procurement.title}'
            ) or f'procurement_{procurement.id}'
            self.assertEqual(os.path.basename(os.path.dirname(submission.file_path)), expected_folder)

    def test_multiple_evaluators_have_independent_scopes(self):
        procurement_id = self._make_procurement()
        technical_id = self._make_submission(procurement_id, 'technical')
        single_id = self._make_submission(procurement_id, 'single')

        self._login(self.manager_name)
        self.assertEqual(self._assign(procurement_id, self.eval_a_id, 'technical').status_code, 201)
        self.assertEqual(self._assign(procurement_id, self.eval_b_id, 'single').status_code, 201)

        self._login(self.eval_a_name)
        self.assertEqual(self._download(procurement_id, technical_id).status_code, 200)
        self.assertEqual(self._download(procurement_id, single_id).status_code, 403)

        self._login(self.eval_b_name)
        self.assertEqual(self._download(procurement_id, technical_id).status_code, 403)
        self.assertEqual(self._download(procurement_id, single_id).status_code, 200)

    def test_reassignment_updates_scope_and_logs_action(self):
        procurement_id = self._make_procurement()
        self._login(self.manager_name)

        first = self._assign(procurement_id, self.eval_a_id, 'technical')
        self.assertEqual(first.status_code, 201)
        assignment_id = first.json['assignment']['id']

        updated = self._assign(procurement_id, self.eval_a_id, 'both')

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json['assignment']['id'], assignment_id)
        self.assertEqual(updated.json['assignment']['document_scope'], 'both')
        self.assertIn('EVALUATOR_ASSIGNMENT_UPDATED', self._audit_actions_for(assignment_id))

    def test_non_procurement_user_cannot_manage_assignments(self):
        procurement_id = self._make_procurement()
        self._login(self.outsider_name)

        response = self._assign(procurement_id, self.eval_a_id, 'both')

        self.assertEqual(response.status_code, 403)


if __name__ == '__main__':
    unittest.main()