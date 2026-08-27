"""Demo seed for the award lifecycle — two "cycles" so you can see both ends.

Cycle A (TB-2026-AWD-A) - Awaiting recommendation
    Tender in 'financial_evaluation' with two scored bidders but NO award yet.
    Opening its award workspace shows "Awaiting recommendation" so you can
    click through Save recommendation -> Publish award live.

Cycle B (TB-2026-AWD-B) - Awaiting recommendation
    A second tender with different scores and its own evaluator document, ready
    for another complete bidder-selection click-through.

Run from the app directory with the venv active:
    python demo_awards.py
Idempotent: re-running refreshes rather than duplicating.
"""
import os
from datetime import datetime, timedelta, date
from decimal import Decimal

from dotenv import load_dotenv
load_dotenv()

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.role import Role  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.bidder import Bidder  # noqa: E402
from app.models.procurement import Procurement  # noqa: E402
from app.models.submission import Submission  # noqa: E402
from app.models.evaluation import Evaluation  # noqa: E402
from app.models.award import Award  # noqa: E402
from app.models.evaluator_feedback import EvaluatorFeedback  # noqa: E402
from app.utils.crypto import encrypt_bytes  # noqa: E402

DEMO_PASSWORD = 'ChangeMe123!'
def _ensure_role(code, **kwargs):
    role = Role.query.filter_by(code=code).first()
    if not role:
        role = Role(code=code, **kwargs)
        db.session.add(role)
        db.session.flush()
    else:
        for key, value in kwargs.items():
            setattr(role, key, value)
    return role


def _ensure_user(username, role_code, first, last, email, bidder=None):
    user = User.query.filter_by(username=username).first()
    if user:
        return user
    role = _ensure_role(code=role_code, name=role_code.replace('_', ' ').title())
    user = User(username=username, email=email, first_name=first, last_name=last,
                role_id=role.id, bidder_id=bidder.id if bidder else None)
    user.set_password(DEMO_PASSWORD)
    db.session.add(user)
    db.session.flush()
    return user


def _ensure_bidder(ppr, company, category, email, grade):
    b = Bidder.query.filter_by(ppra_registration_number=ppr).first()
    if b:
        return b
    b = Bidder(company_name=company, ppra_registration_number=ppr, ppra_grade=grade,
               category=category, contact_email=email,
               registration_expiry=date(2028, 1, 1), verified=True)
    db.session.add(b)
    db.session.flush()
    return b


def _proc(number, title, status, value, created_by):
    p = Procurement.query.filter_by(tender_number=number).first()
    if p:
        return p
    p = Procurement(
        tender_number=number, title=title, category='works',
        procurement_entity='Ministry of Infrastructure',
        ppra_code='105', ppra_sub_code='00', method='open_domestic',
        evaluation_method='weighted', envelope_type='single',
        estimated_value=Decimal(str(value)),
        user_department='Infrastructure',
        submission_deadline=datetime.utcnow() - timedelta(days=5),
        status=status,
        created_by_id=created_by.id,
    )
    db.session.add(p)
    db.session.flush()
    return p


def _submission(proc, bidder, user, receipt):
    existing = Submission.query.filter_by(receipt_code=receipt).first()
    if existing:
        return existing
    s = Submission(
        procurement_id=proc.id, bidder_id=bidder.id, envelope_type='single',
        original_filename=f'{bidder.company_name.split()[0].lower()}_bid.pdf',
        sha256_hash='demo' + receipt[-12:].lower(), file_size_bytes=200000,
        submitted_by_id=user.id, receipt_code=receipt, declaration_accepted=True,
        submitted_at=datetime.utcnow() - timedelta(days=10),
        status='submitted',
    )
    db.session.add(s)
    return s


def _evaluation(proc, bidder, evaluator, score, comments):
    existing = Evaluation.query.filter_by(
        procurement_id=proc.id, bidder_id=bidder.id,
        evaluation_stage='financial').first()
    if existing:
        return existing
    e = Evaluation(
        procurement_id=proc.id, bidder_id=bidder.id, evaluator_id=evaluator.id,
        evaluation_stage='financial', passed=True,
        score=Decimal(str(score)), comments=comments,
    )
    db.session.add(e)
    return e

def _feedback(proc, evaluator, filename, text):
    existing = EvaluatorFeedback.query.filter_by(
        procurement_id=proc.id, evaluator_id=evaluator.id, original_filename=filename
    ).first()
    if existing:
        return existing
    folder = os.path.join('uploads', 'demo_award_feedback')
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f'{proc.tender_number}_{filename}.sealed')
    with open(path, 'wb') as feedback_file:
        feedback_file.write(encrypt_bytes(text.encode('utf-8')))
    record = EvaluatorFeedback(
        procurement_id=proc.id,
        evaluator_id=evaluator.id,
        feedback_text=text,
        file_path=path,
        original_filename=filename,
    )
    db.session.add(record)
    return record

def run():
    app = create_app()
    with app.app_context():
        # ---- Roles / accounts ------------------------------------------------
        accounting = _ensure_role(code='accounting_officer', name='Accounting Officer',
                                  can_approve_procurement=True, can_award=True,
                                  can_view_all_records=True)
        evaluator_role = _ensure_role(code='evaluator', name='Evaluator',
                                      can_evaluate=True)
        _ensure_role(code='bidder', name='Bidder', can_bid=True)

        award_officer = _ensure_user('j.molefe', 'accounting_officer',
                                     'John', 'Molefe', 'j.molefe@pe.gov.bw')
        evaluator = _ensure_user('n.kgosi', 'evaluator',
                                 'Naledi', 'Kgosi', 'n.kgosi@pe.gov.bw')

        # Two bidders (reusing seeded companies) + portal users
        b1 = _ensure_bidder('PPRA/WRK/2019/0045', 'Mokwena Construction (Pty) Ltd',
                            'WRK-EDU', 'bids@mokwenaconstruction.co.bw', 'A')
        b2 = _ensure_bidder('PPRA/WRK/2020/0091', 'Tlou Protection Services',
                            'SRV-SEC', 'info@tlouprotection.co.bw', 'B')
        ub1 = _ensure_user('demo.award.bidder1', 'bidder', 'Karabo', 'Mokwena',
                           'demo.award1@demo.co.bw', bidder=b1)
        ub2 = _ensure_user('demo.award.bidder2', 'bidder', 'Neo', 'Tlou',
                           'demo.award2@demo.co.bw', bidder=b2)

        # ---- Cycle A: awaiting recommendation (no award record yet) ----------
        pA = _proc('TB-2026-AWD-A', 'Installation of Solar Street Lighting',
                   'financial_evaluation', 4_800_000, award_officer)
        _submission(pA, b1, ub1, 'SUB-AWD-A-001')
        _submission(pA, b2, ub2, 'SUB-AWD-A-002')
        _evaluation(pA, b1, evaluator, 82, 'Lowest compliant offer; strong track record.')
        _evaluation(pA, b2, evaluator, 74, 'Compliant but higher cost.')
        _feedback(pA, evaluator, 'solar_lighting_evaluation.pdf',
              'Evaluator recommendation: Mokwena Construction scored highest after compliance and value review.')

        # ---- Cycle B: second practice tender awaiting selection ---------------
        pB = _proc('TB-2026-AWD-B', 'Supply of Office Furniture (Gaborone)',
               'financial_evaluation', 1_250_000, award_officer)
        _submission(pB, b1, ub1, 'Sub-AWD-B-1')
        _submission(pB, b2, ub2, 'Sub-AWD-B-2')
        _evaluation(pB, b1, evaluator, 88, 'Best value for money.')
        _evaluation(pB, b2, evaluator, 71, 'Higher cost assessed.')
        _feedback(pB, evaluator, 'office_furniture_evaluation.pdf',
                  'Evaluator recommendation: Mokwena Construction scored highest on quality and price.')

        # Remove an older Cycle B award so this demo is always ready to practice.
        awB = Award.query.filter_by(procurement_id=pB.id).first()
        if awB:
            db.session.delete(awB)
        pA.status = 'financial_evaluation'
        pB.status = 'financial_evaluation'

        db.session.commit()
        print('Demo created.')
        print(f'  Cycle A (awaiting):   {pA.tender_number}  /procurements/{pA.id}/award')
        print(f'  Demo B (awaiting):      {pB.tender_number}  /procurements/{pB.id}/award')
        print(f'Log in as j.molefe (password: {DEMO_PASSWORD}) and open either procurement, then click View Award Bidders.')


if __name__ == '__main__':
    run()