"""Populates the database with roles, demo users, and a couple of sample
procurements so the app can be explored immediately after setup — WITHOUT
any of this data being hardcoded into the templates or routes themselves.
Delete the demo accounts/records before using this for anything real.

Run with: python seed.py
"""
from datetime import datetime, timedelta, date
from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.role import Role  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.bidder import Bidder  # noqa: E402
from app.models.procurement import Procurement  # noqa: E402
from app.models.committee import CommitteeMember, EvaluationCriteria  # noqa: E402
from app.models.submission import Submission  # noqa: E402
from app.models.evaluation import Evaluation  # noqa: E402

DEMO_PASSWORD = 'ChangeMe123!'

ROLES = [
    dict(code='system_admin', name='System Administrator',
         can_admin_system=True, can_view_all_records=True),
    dict(code='accounting_officer', name='Accounting Officer',
         can_approve_procurement=True, can_award=True, can_view_all_records=True),
    dict(code='procurement_oversight', name='Procurement Oversight',
         can_approve_procurement=True, can_view_all_records=True),
    dict(code='procurement_unit', name='Procurement Unit',
         can_create_procurement=True, can_publish=True, can_view_all_records=True),
    dict(code='user_department', name='User Department',
         can_create_procurement=True),
    dict(code='committee_chair', name='Committee Chair', can_evaluate=True),
    dict(code='committee_secretary', name='Committee Secretary', can_evaluate=True),
    dict(code='evaluator', name='Evaluator', can_evaluate=True),
    dict(code='opening_panel', name='Opening Panel', can_open_bids=True),
    dict(code='bidder', name='Bidder', can_bid=True),
]

USERS = [
    dict(username='admin', email='admin@pe.gov.bw', first_name='System', last_name='Administrator',
         role_code='system_admin', department='ICT'),
    dict(username='j.molefe', email='j.molefe@pe.gov.bw', first_name='John', last_name='Molefe',
         role_code='accounting_officer', department='Head Office', delegation_limit=20_000_000),
    dict(username='s.kgosi', email='s.kgosi@pe.gov.bw', first_name='Sarah', last_name='Kgosi',
         role_code='procurement_oversight', department='Quality Assurance'),
    dict(username='d.tlou', email='d.tlou@pe.gov.bw', first_name='David', last_name='Tlou',
         role_code='procurement_unit', department='Procurement'),
    dict(username='g.motsumi', email='g.motsumi@pe.gov.bw', first_name='Grace', last_name='Motsumi',
         role_code='committee_secretary', department='Legal'),
    dict(username='p.seleka', email='p.seleka@pe.gov.bw', first_name='Paul', last_name='Seleka',
         role_code='opening_panel', department='Finance'),
    dict(username='p.seleka2', email='p.seleka2@pe.gov.bw', first_name='Kagiso', last_name='Ramotswe',
         role_code='opening_panel', department='Finance'),
    dict(username='k.motsumi', email='k.motsumi@pe.gov.bw', first_name='K.', last_name='Motsumi',
         role_code='committee_chair', department='Engineering'),
    dict(username='n.kgosi', email='n.kgosi@pe.gov.bw', first_name='Naledi', last_name='Kgosi',
         role_code='evaluator', department='Engineering'),
]


def run():
    app = create_app()
    with app.app_context():
        db.create_all()

        role_map = {}
        for r in ROLES:
            role = Role.query.filter_by(code=r['code']).first()
            if not role:
                role = Role(**r)
                db.session.add(role)
                db.session.flush()
            role_map[r['code']] = role
        db.session.commit()

        user_map = {}
        for u in USERS:
            existing = User.query.filter_by(username=u['username']).first()
            if existing:
                user_map[u['username']] = existing
                continue
            user = User(
                username=u['username'], email=u['email'], first_name=u['first_name'], last_name=u['last_name'],
                role_id=role_map[u['role_code']].id, department=u.get('department'),
                delegation_limit=u.get('delegation_limit', 0),
            )
            user.set_password(DEMO_PASSWORD)
            db.session.add(user)
            db.session.flush()
            user_map[u['username']] = user
        db.session.commit()

        # Demo bidder company + portal user
        bidder = Bidder.query.filter_by(ppra_registration_number='PPRA/WRK/2019/0045').first()
        if not bidder:
            bidder = Bidder(
                company_name='Mokwena Construction (Pty) Ltd',
                ppra_registration_number='PPRA/WRK/2019/0045',
                ppra_grade='A', category='WRK-EDU',
                contact_email='bids@mokwenaconstruction.co.bw',
                registration_expiry=date(2027, 3, 15),
                verified=True,
            )
            db.session.add(bidder)
            db.session.flush()

        bidder_user = User.query.filter_by(username='bidder1').first()
        if not bidder_user:
            bidder_user = User(
                username='bidder1', email='bids@mokwenaconstruction.co.bw',
                first_name='Karabo', last_name='Mokwena',
                role_id=role_map['bidder'].id, bidder_id=bidder.id,
            )
            bidder_user.set_password(DEMO_PASSWORD)
            db.session.add(bidder_user)
        db.session.commit()

        # A second bidder company, useful for demonstrating the scoring matrix with >1 bidder
        bidder2 = Bidder.query.filter_by(ppra_registration_number='PPRA/WRK/2020/0091').first()
        if not bidder2:
            bidder2 = Bidder(
                company_name='Tlou Protection Services',
                ppra_registration_number='PPRA/WRK/2020/0091',
                ppra_grade='B', category='SRV-SEC',
                contact_email='info@tlouprotection.co.bw',
                registration_expiry=date(2026, 12, 1),
                verified=True,
            )
            db.session.add(bidder2)
            db.session.commit()

        # Demo procurement in SUBMISSION_OPEN, ready to receive a bid
        if not Procurement.query.filter_by(tender_number='TB-2026-089').first():
            p1 = Procurement(
                tender_number='TB-2026-089',
                title='Construction of Primary School in Gaborone',
                description='Construction of a new primary school building including classrooms, '
                             'administrative block, library, and sanitation facilities in Gaborone West.',
                category='works', ppra_code='WRK-EDU-001', method='open_domestic',
                evaluation_method='quality_cost', envelope_type='dual',
                estimated_value=12_500_000, user_department='Ministry of Basic Education',
                submission_deadline=datetime.utcnow() + timedelta(days=18),
                status='submission_open',
                created_by_id=user_map['d.tlou'].id,
            )
            db.session.add(p1)
            db.session.flush()

            db.session.add(EvaluationCriteria(
                procurement_id=p1.id, criteria_type='compliance', name='Valid PPRA Registration',
                scoring_method='pass_fail', is_mandatory=True, locked=True, sequence=1,
            ))
            db.session.add(EvaluationCriteria(
                procurement_id=p1.id, criteria_type='technical', name='Company Experience & Track Record',
                weight=30, max_score=30, scoring_method='points', locked=True, sequence=2,
            ))
            db.session.add(EvaluationCriteria(
                procurement_id=p1.id, criteria_type='financial', name='Price Competitiveness',
                weight=10, max_score=10, scoring_method='formula', locked=False, sequence=3,
            ))

        # A second demo procurement already in TECHNICAL_EVALUATION, with real
        # committee, submissions, and scores — so the Evaluation screen has
        # something substantive to show without any hardcoded template data.
        if not Procurement.query.filter_by(tender_number='TB-2026-086').first():
            p2 = Procurement(
                tender_number='TB-2026-086',
                title='Security Services for Government Buildings',
                description='Provision of security guarding services across Head Office government buildings.',
                category='services', ppra_code='SRV-SEC-014', method='restricted',
                evaluation_method='weighted', envelope_type='single',
                estimated_value=3_200_000, user_department='Ministry of Basic Education',
                submission_deadline=datetime.utcnow() - timedelta(days=5),
                status='technical_evaluation',
                created_by_id=user_map['d.tlou'].id,
            )
            db.session.add(p2)
            db.session.flush()

            db.session.add(CommitteeMember(
                procurement_id=p2.id, user_id=user_map['k.motsumi'].id,
                appointment_instrument_ref='APPT-2026-014', appointment_date=date.today(),
                role='chair', confidentiality_signed=True, access_granted=True,
            ))
            db.session.add(CommitteeMember(
                procurement_id=p2.id, user_id=user_map['n.kgosi'].id,
                appointment_instrument_ref='APPT-2026-014', appointment_date=date.today(),
                role='member', confidentiality_signed=True, access_granted=True,
            ))
            db.session.add(CommitteeMember(
                procurement_id=p2.id, user_id=user_map['g.motsumi'].id,
                appointment_instrument_ref='APPT-2026-014', appointment_date=date.today(),
                role='secretary', is_voting_member=False, confidentiality_signed=True, access_granted=True,
            ))

            db.session.add(EvaluationCriteria(
                procurement_id=p2.id, criteria_type='compliance', name='Valid PPRA Registration',
                scoring_method='pass_fail', is_mandatory=True, locked=True, sequence=1,
            ))
            db.session.add(EvaluationCriteria(
                procurement_id=p2.id, criteria_type='technical', name='Experience & Track Record',
                weight=30, max_score=30, scoring_method='points', locked=True, sequence=2,
            ))

            db.session.flush()

            sub1 = Submission(
                procurement_id=p2.id, bidder_id=bidder.id, envelope_type='single',
                original_filename='mokwena_bid.pdf', sha256_hash='demo0000000000000000000000000000',
                file_size_bytes=204800, submitted_by_id=bidder_user.id,
                receipt_code='SUB-20260715-A7B3C9D2', declaration_accepted=True,
                submitted_at=datetime.utcnow() - timedelta(days=10),
            )
            sub2 = Submission(
                procurement_id=p2.id, bidder_id=bidder2.id, envelope_type='single',
                original_filename='tlou_bid.pdf', sha256_hash='demo0000000000000000000000000001',
                file_size_bytes=189440, submitted_by_id=bidder_user.id,
                receipt_code='SUB-20260714-E4F5G6H7', declaration_accepted=True,
                submitted_at=datetime.utcnow() - timedelta(days=11),
            )
            db.session.add_all([sub1, sub2])

            db.session.add(Evaluation(
                procurement_id=p2.id, bidder_id=bidder.id, evaluator_id=user_map['k.motsumi'].id,
                evaluation_stage='compliance', passed=True, comments='Registration verified.',
            ))
            db.session.add(Evaluation(
                procurement_id=p2.id, bidder_id=bidder2.id, evaluator_id=user_map['k.motsumi'].id,
                evaluation_stage='compliance', passed=True, comments='Registration verified.',
            ))
            db.session.add(Evaluation(
                procurement_id=p2.id, bidder_id=bidder.id, evaluator_id=user_map['k.motsumi'].id,
                evaluation_stage='technical', score=28, comments='Strong track record.',
            ))
            db.session.add(Evaluation(
                procurement_id=p2.id, bidder_id=bidder2.id, evaluator_id=user_map['k.motsumi'].id,
                evaluation_stage='technical', score=25, comments='Good, slightly less experience.',
            ))

        db.session.commit()
        print(f"Seed complete. All demo users share the password: {DEMO_PASSWORD}")
        print("Try: admin / d.tlou / j.molefe / k.motsumi / p.seleka / bidder1 (all same password)")


if __name__ == '__main__':
    run()
