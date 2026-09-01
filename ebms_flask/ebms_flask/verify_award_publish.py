from app import create_app
from app.models.procurement import Procurement
from app.extensions import db

app = create_app()

with app.app_context():
    procurement = Procurement.query.filter_by(tender_number='TB-SIM-AWARD-2026-001').first()
    if not procurement:
        raise RuntimeError('Missing simulation procurement')

    award = procurement.award
    if award:
        award.pre_decision_at = None
        award.pre_decision_by_id = None
        award.ao_decision_at = None
        award.ao_decision_by_id = None
        award.ao_decision_reason = None
        award.published_at = None
        award.published_by_id = None
        db.session.commit()

    with app.test_client() as client:
        login_pou = client.post('/login', data={'username': 'pou_user', 'password': 'ChangeMe123!'}, follow_redirects=True)
        assert login_pou.status_code == 200, login_pou.status_code

        resp_pre = client.post(
            f'/procurements/{procurement.id}/award',
            data={
                'action': 'save_pre_decision',
                'winning_bidder_id': '7',
                'award_value': '345000',
                'decision_reason': 'POU recommendation for testing',
                'decision_notes': 'Pre decision sent to AO',
            },
            follow_redirects=False,
        )
        assert resp_pre.status_code == 302, resp_pre.status_code
        award = Procurement.query.get(procurement.id).award
        assert award is not None and award.pre_decision_at is not None
        assert award.ao_decision_at is None

        client.get('/logout', follow_redirects=True)
        login_ao = client.post('/login', data={'username': 'j.molefe', 'password': 'ChangeMe123!'}, follow_redirects=True)
        assert login_ao.status_code == 200, login_ao.status_code

        resp_ao = client.post(
            f'/procurements/{procurement.id}/award',
            data={
                'action': 'submit_final_decision',
                'winning_bidder_id': '7',
                'award_value': '345000',
                'decision_reason': 'AO approved POU recommendation',
                'decision_notes': 'Final decision forwarded to POU',
                'ao_decision_reason': 'Final decision approved by Accounting Officer',
            },
            follow_redirects=False,
        )
        assert resp_ao.status_code == 302, resp_ao.status_code
        award = Procurement.query.get(procurement.id).award
        assert award is not None and award.ao_decision_at is not None

        client.get('/logout', follow_redirects=True)
        login_pou_again = client.post('/login', data={'username': 'pou_user', 'password': 'ChangeMe123!'}, follow_redirects=True)
        assert login_pou_again.status_code == 200, login_pou_again.status_code

        resp_publish = client.post(
            f'/procurements/{procurement.id}/award',
            data={'action': 'publish_final_decision'},
            follow_redirects=False,
        )
        assert resp_publish.status_code == 302, resp_publish.status_code

        award = Procurement.query.get(procurement.id).award
        assert award is not None and award.published_at is not None
        assert Procurement.query.get(procurement.id).status == 'award_published'

        print('AWARD_WORKFLOW_VERIFIED')
        print(f'PRE_DECISION={award.pre_decision_at is not None}')
        print(f'AO_DECISION={award.ao_decision_at is not None}')
        print(f'PUBLISHED={award.published_at is not None}')
        print(f'STATUS={Procurement.query.get(procurement.id).status}')
