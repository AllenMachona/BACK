from collections import defaultdict
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models.procurement import Procurement
from app.models.evaluation import Evaluation
from app.models.committee import EvaluationCriteria, CommitteeMember
from app.utils.decorators import permission_required
from app.utils.audit import log_action

evaluations_bp = Blueprint('evaluations', __name__, url_prefix='/evaluations')

EVALUABLE_STATUSES = [
    'closed', 'technical_opening', 'compliance_evaluation',
    'technical_evaluation', 'financial_opening', 'financial_evaluation',
]


@evaluations_bp.route('/')
@login_required
@permission_required('can_evaluate')
def index():
    procurements = Procurement.query.filter(Procurement.status.in_(EVALUABLE_STATUSES)).order_by(
        Procurement.updated_at.desc()
    ).all()
    if len(procurements) == 1:
        return redirect(url_for('evaluations.detail', procurement_id=procurements[0].id))
    return render_template('evaluation_select.html', procurements=procurements)


@evaluations_bp.route('/<int:procurement_id>')
@login_required
@permission_required('can_evaluate')
def detail(procurement_id):
    procurement = Procurement.query.get_or_404(procurement_id)

    criteria = procurement.criteria.order_by(EvaluationCriteria.sequence).all()

    evaluations = procurement.evaluations.all()
    bids_received = procurement.submissions.filter_by(status='submitted').count()
    compliant = len({e.bidder_id for e in evaluations if e.evaluation_stage == 'compliance' and e.passed})
    non_compliant = len({e.bidder_id for e in evaluations if e.evaluation_stage == 'compliance' and e.passed is False})
    committee_count = procurement.committee_members.count()

    # Build a per-bidder scoring matrix from real Evaluation rows.
    matrix = defaultdict(lambda: {'compliance': None, 'technical_scores': {}, 'technical_total': None, 'status': 'Pending'})
    for e in evaluations:
        row = matrix[e.bidder]
        if e.evaluation_stage == 'compliance':
            row['compliance'] = 'Pass' if e.passed else ('Fail' if e.passed is False else None)
            if e.passed is False:
                row['status'] = 'Eliminated'
        elif e.evaluation_stage == 'technical':
            row['technical_scores'][e.id] = e.score
            if row['status'] != 'Eliminated':
                row['status'] = 'Qualified' if not e.eliminated else 'Eliminated'

    return render_template(
        'evaluation.html',
        procurement=procurement,
        criteria=criteria,
        bids_received=bids_received,
        compliant=compliant,
        non_compliant=non_compliant,
        committee_count=committee_count,
        matrix=matrix,
    )


@evaluations_bp.route('/<int:procurement_id>/score', methods=['POST'])
@login_required
@permission_required('can_evaluate')
def submit_score(procurement_id):
    procurement = Procurement.query.get_or_404(procurement_id)

    is_member = CommitteeMember.query.filter_by(
        procurement_id=procurement.id, user_id=current_user.id
    ).first()
    if not is_member:
        flash('You are not an appointed committee member for this procurement.', 'danger')
        return redirect(url_for('evaluations.detail', procurement_id=procurement_id))

    bidder_id = request.form.get('bidder_id', type=int)
    stage = request.form.get('stage')
    score = request.form.get('score', type=float)
    passed = request.form.get('passed')
    comments = request.form.get('comments', '')

    existing = Evaluation.query.filter_by(
        procurement_id=procurement_id, bidder_id=bidder_id, evaluator_id=current_user.id, evaluation_stage=stage
    ).first()
    if existing:
        flash('You have already submitted a score for this bidder at this stage.', 'warning')
        return redirect(url_for('evaluations.detail', procurement_id=procurement_id))

    evaluation = Evaluation(
        procurement_id=procurement_id, bidder_id=bidder_id, evaluator_id=current_user.id,
        evaluation_stage=stage, score=score, passed=(passed == 'true') if passed else None, comments=comments,
    )
    db.session.add(evaluation)
    db.session.commit()

    log_action('EVALUATION_SCORE_SUBMITTED', entity_type='Evaluation', entity_id=evaluation.id,
               new_value={'bidder_id': bidder_id, 'stage': stage, 'score': score})
    flash('Score recorded.', 'success')
    return redirect(url_for('evaluations.detail', procurement_id=procurement_id))
