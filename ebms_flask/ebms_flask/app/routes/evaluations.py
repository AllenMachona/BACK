from collections import defaultdict
import os
import secrets
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models.procurement import Procurement
from app.models.evaluation import Evaluation
from app.models.committee import EvaluationCriteria, CommitteeMember
from app.models.evaluator_assignment import EvaluatorAssignment
from app.models.evaluator_feedback import EvaluatorFeedback
from app.utils.decorators import permission_required
from app.utils.audit import log_action
from app.utils.evaluator_assignment import EvaluatorAssignmentService

evaluations_bp = Blueprint('evaluations', __name__, url_prefix='/evaluations')

EVALUABLE_STATUSES = [
    'under_evaluation', 'closed', 'technical_opening', 'compliance_evaluation',
    'technical_evaluation', 'financial_opening', 'financial_evaluation',
]


def _is_full_visibility(user):
    """Procurement staff / system admin see everything (bypass scope gate)."""
    return bool(user.role and user.role.can_view_all_records)


@evaluations_bp.route('/')
@login_required
@permission_required('can_evaluate')
def index():
    procurements = Procurement.query.filter(Procurement.status.in_(EVALUABLE_STATUSES)).order_by(
        Procurement.updated_at.desc()
    ).all()

    # Evaluators only see procurements they have been assigned to.
    if not _is_full_visibility(current_user):
        assigned_ids = EvaluatorAssignmentService.assigned_procurement_ids(current_user.id)
        procurements = [p for p in procurements if p.id in assigned_ids]

    if len(procurements) == 1:
        return redirect(url_for('evaluations.detail', procurement_id=procurements[0].id))
    return render_template('evaluation_select.html', procurements=procurements)


@evaluations_bp.route('/<int:procurement_id>')
@login_required
@permission_required('can_evaluate')
def detail(procurement_id):
    procurement = Procurement.query.get_or_404(procurement_id)

    # Assignment gate: evaluators may only open procurements they are assigned to.
    assignment = EvaluatorAssignment.active_for(procurement.id, current_user.id)
    if not _is_full_visibility(current_user) and not assignment:
        log_action('EVALUATOR_PROCUREMENT_ACCESS_BLOCKED', entity_type='Procurement',
                   entity_id=procurement.id,
                   reason=f'User {current_user.id} attempted to open an unassigned evaluation')
        abort(403)

    criteria = procurement.criteria.order_by(EvaluationCriteria.sequence).all()

    # Document-type scope: which submission envelopes may this evaluator see?
    allowed_envelopes = None
    if assignment is not None:
        allowed_envelopes = set(EvaluatorAssignment.SCOPE_ENVELOPES[assignment.document_scope])

    evaluator_scope_label = assignment.scope_label() if assignment else None

    evaluations = procurement.evaluations.all()
    submitted_rows = procurement.submissions.filter_by(status='submitted').all()

    def _visible(submission_row):
        if allowed_envelopes is None:
            return True
        return submission_row.envelope_type in allowed_envelopes

    visible_submissions = [submission for submission in submitted_rows if _visible(submission)]

    bids_received = sum(1 for s in submitted_rows if _visible(s))
    compliant = len({e.bidder_id for e in evaluations if e.evaluation_stage == 'compliance' and e.passed})
    non_compliant = len({e.bidder_id for e in evaluations if e.evaluation_stage == 'compliance' and e.passed is False})
    committee_count = procurement.committee_members.count()

    # Build a per-bidder scoring matrix from real Evaluation rows.
    matrix = defaultdict(lambda: {'compliance': None, 'technical_scores': {}, 'technical_total': None, 'status': 'Pending'})
    for e in evaluations:
        if allowed_envelopes is not None:
            # A bidder is only visible to this evaluator when the bidder has a
            # submission envelope inside the evaluator's granted scope.
            bidder_visible = any(
                s.bidder_id == e.bidder_id and _visible(s)
                for s in submitted_rows
            )
            if not bidder_visible:
                continue
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
        evaluator_scope_label=evaluator_scope_label,
        visible_submissions=visible_submissions,
        can_submit_feedback=bool(assignment),
    )


@evaluations_bp.route('/<int:procurement_id>/feedback', methods=['POST'])
@login_required
@permission_required('can_evaluate')
def submit_feedback(procurement_id):
    procurement = Procurement.query.get_or_404(procurement_id)
    assignment = EvaluatorAssignment.active_for(procurement.id, current_user.id)
    if not assignment:
        abort(403)

    feedback_file = request.files.get('feedback_file')
    if not feedback_file or not feedback_file.filename:
        flash('Attach a feedback document before submitting.', 'danger')
        return redirect(url_for('evaluations.detail', procurement_id=procurement.id))

    plaintext = feedback_file.read()
    if not plaintext:
        flash('The feedback document is empty.', 'danger')
        return redirect(url_for('evaluations.detail', procurement_id=procurement.id))

    procurement_folder = secure_filename(
        f'{procurement.tender_number}_{procurement.title}'
    ) or f'procurement_{procurement.id}'
    feedback_dir = os.path.join(
        current_app.config['UPLOAD_FOLDER'], procurement_folder, 'evaluation_feedback'
    )
    os.makedirs(feedback_dir, exist_ok=True)
    filename = secure_filename(
        f'{current_user.id}_{secrets.token_hex(4)}_{feedback_file.filename}.sealed'
    )
    filepath = os.path.join(feedback_dir, filename)

    from app.utils.crypto import encrypt_bytes
    with open(filepath, 'wb') as encrypted_file:
        encrypted_file.write(encrypt_bytes(plaintext))

    feedback = EvaluatorFeedback(
        procurement_id=procurement.id,
        evaluator_id=current_user.id,
        feedback_text=request.form.get('feedback_text', '').strip() or None,
        file_path=filepath,
        original_filename=feedback_file.filename,
    )
    db.session.add(feedback)
    db.session.commit()
    log_action(
        'EVALUATOR_FEEDBACK_SUBMITTED',
        entity_type='EvaluatorFeedback',
        entity_id=feedback.id,
        new_value={'procurement_id': procurement.id, 'filename': feedback.original_filename},
    )
    flash('Feedback document submitted to the Procurement team.', 'success')
    return redirect(url_for('evaluations.detail', procurement_id=procurement.id))


@evaluations_bp.route('/<int:procurement_id>/score', methods=['POST'])
@login_required
@permission_required('can_evaluate')
def submit_score(procurement_id):
    procurement = Procurement.query.get_or_404(procurement_id)

    assignment = EvaluatorAssignment.active_for(procurement.id, current_user.id)
    is_member = CommitteeMember.query.filter_by(
        procurement_id=procurement.id, user_id=current_user.id
    ).first()
    if not is_member and not assignment and not _is_full_visibility(current_user):
        flash('You are not an appointed evaluator for this procurement.', 'danger')
        return redirect(url_for('evaluations.detail', procurement_id=procurement_id))

    bidder_id = request.form.get('bidder_id', type=int)
    stage = request.form.get('stage')
    score = request.form.get('score', type=float)
    passed = request.form.get('passed')
    comments = request.form.get('comments', '')

    # Document-scope gate: an evaluator may only score stages their assigned
    # scope covers (technical -> technical envelopes, financial -> single).
    if assignment and not EvaluatorAssignmentService.can_submit_stage(
        procurement.id, current_user.id, stage
    ):
        flash('Your assigned document scope does not allow scoring this evaluation stage.', 'danger')
        return redirect(url_for('evaluations.detail', procurement_id=procurement_id))

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
