from datetime import datetime, timedelta

from app import create_app
from app.extensions import db
from app.models.award import Award
from app.models.bidder import Bidder
from app.models.evaluation import Evaluation
from app.models.procurement import Procurement
from app.models.submission import Submission
from app.models.user import User


def ensure_user(username, email, first_name, last_name, role_code, department):
    user = User.query.filter_by(username=username).first()
    if user:
        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.department = department
        return user

    role = user_role_for(role_code)
    if not role:
        raise RuntimeError(f"Missing role: {role_code}")

    user = User(
        username=username,
        email=email,
        first_name=first_name,
        last_name=last_name,
        role_id=role.id,
        department=department,
        is_active=True,
    )
    user.set_password('ChangeMe123!')
    db.session.add(user)
    db.session.flush()
    return user


def user_role_for(code):
    from app.models.role import Role

    return Role.query.filter_by(code=code).first()


def ensure_bidder(company_name, ppra_registration_number, ppra_grade, category, email):
    bidder = Bidder.query.filter_by(ppra_registration_number=ppra_registration_number).first()
    if bidder:
        bidder.company_name = company_name
        bidder.ppra_grade = ppra_grade
        bidder.category = category
        bidder.contact_email = email
        bidder.active = True
        bidder.verified = True
        return bidder

    bidder = Bidder(
        company_name=company_name,
        ppra_registration_number=ppra_registration_number,
        ppra_grade=ppra_grade,
        category=category,
        contact_email=email,
        active=True,
        verified=True,
    )
    db.session.add(bidder)
    db.session.flush()
    return bidder


def main():
    app = create_app()
    with app.app_context():
        procurement_unit = User.query.filter_by(username='d.tlou').first()
        if not procurement_unit:
            procurement_unit = ensure_user('d.tlou', 'd.tlou@pe.gov.bw', 'David', 'Tlou', 'procurement_unit', 'Procurement')

        pou_user = User.query.filter_by(username='pou_user').first()
        if not pou_user:
            pou_user = ensure_user('pou_user', 'pou@pe.gov.bw', 'POU', 'Officer', 'pou', 'Procurement Oversight Unit')

        ao_user = User.query.filter_by(username='j.molefe').first()
        if not ao_user:
            ao_user = ensure_user('j.molefe', 'j.molefe@pe.gov.bw', 'John', 'Molefe', 'accounting_officer', 'Head Office')

        evaluator = User.query.filter_by(username='n.kgosi').first()
        if not evaluator:
            evaluator = ensure_user('n.kgosi', 'n.kgosi@pe.gov.bw', 'Naledi', 'Kgosi', 'evaluator', 'Engineering')

        bidder_1 = ensure_bidder('Alpha Contractors Ltd', 'PPRA-SIM-001', 'A', 'WRK-EDU', 'alpha@example.com')
        bidder_2 = ensure_bidder('Bravo Supplies Botswana', 'PPRA-SIM-002', 'A', 'SUP', 'bravo@example.com')
        bidder_3 = ensure_bidder('Charlie Works & Services', 'PPRA-SIM-003', 'B', 'SRV', 'charlie@example.com')

        procurement = Procurement.query.filter_by(tender_number='TB-SIM-AWARD-2026-001').first()
        if not procurement:
            procurement = Procurement(
                tender_number='TB-SIM-AWARD-2026-001',
                title='Simulation: Supply and Delivery of Office Equipment',
                description='Demo procurement created to test the award workflow with evaluator scores.',
                category='supplies',
                procurement_entity='Ministry of Transport',
                user_department='Ministry of Transport',
                ppra_code='211',
                ppra_sub_code='05',
                method='open_domestic',
                evaluation_method='quality_cost_based',
                estimated_value=520000.00,
                tender_fee=0.00,
                status='award_pending_approval',
                created_by_id=procurement_unit.id,
                submission_deadline=datetime.utcnow() - timedelta(days=10),
                clarification_deadline=datetime.utcnow() - timedelta(days=8),
                opening_scheduled_at=datetime.utcnow() - timedelta(days=7),
            )
            db.session.add(procurement)
            db.session.flush()

        for bidder in (bidder_1, bidder_2, bidder_3):
            submission = Submission.query.filter_by(procurement_id=procurement.id, bidder_id=bidder.id).first()
            if not submission:
                submission = Submission(
                    procurement_id=procurement.id,
                    bidder_id=bidder.id,
                    envelope_type='single',
                    file_path='demo/simulated_bid',
                    original_filename=f'{bidder.company_name}.sealed',
                    sha256_hash='simulated',
                    file_size_bytes=1024,
                    submitted_by_id=procurement_unit.id,
                    status='submitted',
                    receipt_code=f'SIM-{bidder.id}',
                    declaration_accepted=True,
                    submitted_at=datetime.utcnow() - timedelta(days=2),
                )
                db.session.add(submission)
                db.session.flush()

        scores = {
            bidder_1.id: 92.5,
            bidder_2.id: 86.0,
            bidder_3.id: 78.0,
        }
        for bidder in (bidder_1, bidder_2, bidder_3):
            evaluation = Evaluation.query.filter_by(procurement_id=procurement.id, bidder_id=bidder.id).first()
            if not evaluation:
                evaluation = Evaluation(
                    procurement_id=procurement.id,
                    bidder_id=bidder.id,
                    evaluator_id=evaluator.id,
                    evaluation_stage='technical',
                    score=scores[bidder.id],
                    comments=f'Demo evaluation for {bidder.company_name}',
                    evidence_references='Demo evidence reference',
                    is_consensus=True,
                    consensus_reached=True,
                    consensus_score=scores[bidder.id],
                    passed=True,
                    approved_by=evaluator.id,
                    approved_at=datetime.utcnow() - timedelta(days=1),
                )
                db.session.add(evaluation)
            else:
                evaluation.evaluator_id = evaluator.id
                evaluation.score = scores[bidder.id]
                evaluation.comments = f'Demo evaluation for {bidder.company_name}'
                evaluation.evidence_references = 'Demo evidence reference'
                evaluation.is_consensus = True
                evaluation.consensus_reached = True
                evaluation.consensus_score = scores[bidder.id]
                evaluation.passed = True
                evaluation.approved_by = evaluator.id
                evaluation.approved_at = datetime.utcnow() - timedelta(days=1)

        award = procurement.award
        if not award:
            award = Award(procurement_id=procurement.id, created_by_id=procurement_unit.id)
            db.session.add(award)

        winning_bidder = bidder_1
        award.winning_bidder_id = winning_bidder.id
        award.award_value = 345000.00
        award.decision_reason = 'Highest combined technical score and acceptable price profile.'
        award.decision_notes = 'This simulation is intended for testing the POU/AO award workflow.'
        award.pre_decision_at = datetime.utcnow() - timedelta(days=1)
        award.pre_decision_by_id = pou_user.id
        award.ao_decision_at = datetime.utcnow() - timedelta(hours=6)
        award.ao_decision_by_id = ao_user.id
        award.ao_decision_reason = 'Accounting Officer accepted the recommended award to Alpha Contractors Ltd.'
        award.cooling_off_expiry = datetime.utcnow() + timedelta(days=10)
        award.published_at = None
        award.published_by_id = None
        procurement.status = 'award_pending_approval'

        db.session.commit()

        print('SIMULATION_CREATED')
        print(f'PROCUREMENT_ID={procurement.id}')
        print(f'TENDER_NUMBER={procurement.tender_number}')
        print(f'WINNING_BIDDER={winning_bidder.company_name}')
        print(f'STATUS={procurement.status}')
        print('PARTICIPANTS=' + ', '.join(f'{b.id}:{b.company_name}' for b in (bidder_1, bidder_2, bidder_3)))
        print('EVALUATION_SCORES=' + ', '.join(f'{b.id}:{scores[b.id]}' for b in (bidder_1, bidder_2, bidder_3)))


if __name__ == '__main__':
    main()
