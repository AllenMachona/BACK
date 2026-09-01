import unittest
from datetime import datetime, timedelta

from app import create_app
from app.extensions import db
from app.models.award import Award
from app.models.complaint import Complaint
from app.models.procurement import Procurement


class Phase4AwardAndComplaintTests(unittest.TestCase):
    def test_award_cooling_off_is_active_while_valid(self):
        award = Award(cooling_off_expiry=datetime.utcnow() + timedelta(days=5))
        self.assertTrue(award.cooling_off_active())

    def test_procurement_blocks_contract_stage_while_complaint_is_live(self):
        procurement = Procurement(status='award_published')
        procurement.complaints = [Complaint(status='under_review')]
        self.assertFalse(procurement.can_transition_to_contract())

    def test_procurement_allows_contract_when_complaint_is_resolved(self):
        procurement = Procurement(status='award_published')
        procurement.complaints = [Complaint(status='dismissed')]
        self.assertTrue(procurement.can_transition_to_contract())

    def test_pou_ao_publish_workflow_accepts_forward_and_final_choice_actions(self):
        app = create_app()
        with app.app_context():
            procurement = Procurement.query.filter_by(tender_number='TB-SIM-AWARD-2026-001').first()
            if procurement is None:
                self.fail('Missing simulation procurement for award workflow test')

            award = procurement.award
            if award is not None:
                award.pre_decision_at = None
                award.pre_decision_by_id = None
                award.ao_decision_at = None
                award.ao_decision_by_id = None
                award.ao_decision_reason = None
                award.published_at = None
                award.published_by_id = None
                db.session.commit()

            with app.test_client() as client:
                resp = client.post('/login', data={'username': 'pou_user', 'password': 'ChangeMe123!'}, follow_redirects=True)
                self.assertEqual(resp.status_code, 200)

                resp = client.post(
                    f'/procurements/{procurement.id}/award',
                    data={
                        'action': 'forward_to_accounting_officer',
                        'winning_bidder_id': '7',
                        'award_value': '345000',
                        'decision_reason': 'POU recommendation for testing',
                        'decision_notes': 'Pre decision sent to AO',
                        'score_reasons': 'Excellent technical fit and value for money',
                    },
                    follow_redirects=False,
                )
                self.assertEqual(resp.status_code, 302)
                award = Procurement.query.get(procurement.id).award
                self.assertIsNotNone(award)
                self.assertIsNotNone(award.pre_decision_at)

                client.get('/logout', follow_redirects=True)
                resp = client.post('/login', data={'username': 'j.molefe', 'password': 'ChangeMe123!'}, follow_redirects=True)
                self.assertEqual(resp.status_code, 200)

                resp = client.post(
                    f'/procurements/{procurement.id}/award',
                    data={
                        'action': 'finalise_award_choice',
                        'winning_bidder_id': '7',
                        'award_value': '345000',
                        'decision_reason': 'AO approved POU recommendation',
                        'decision_notes': 'Final decision forwarded to POU',
                        'ao_decision_reason': 'Final decision approved by Accounting Officer',
                    },
                    follow_redirects=False,
                )
                self.assertEqual(resp.status_code, 302)
                award = Procurement.query.get(procurement.id).award
                self.assertIsNotNone(award.ao_decision_at)

                client.get('/logout', follow_redirects=True)
                resp = client.post('/login', data={'username': 'pou_user', 'password': 'ChangeMe123!'}, follow_redirects=True)
                self.assertEqual(resp.status_code, 200)

                resp = client.post(
                    f'/procurements/{procurement.id}/award',
                    data={'action': 'publish_award'},
                    follow_redirects=False,
                )
                self.assertEqual(resp.status_code, 302)
                award = Procurement.query.get(procurement.id).award
                self.assertIsNotNone(award.published_at)
                self.assertEqual(Procurement.query.get(procurement.id).status, 'award_published')


if __name__ == '__main__':
    unittest.main()
