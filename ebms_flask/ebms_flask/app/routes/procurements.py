import random
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models.procurement import Procurement
from app.models.communication import Communication
from app.models.complaint import Complaint
from app.utils.decorators import permission_required
from app.utils.audit import log_action
from app.utils.notify import notify_bidders_on_procurement

procurements_bp = Blueprint('procurements', __name__, url_prefix='/procurements')

# Legal status transitions (SOAR Appendix C). Kept as one explicit map so
# every route enforces the same lifecycle instead of re-implementing checks.
TRANSITIONS = {
    'draft': ['internal_review', 'cancelled'],
    'internal_review': ['approved_for_publication', 'draft', 'cancelled'],
    'approved_for_publication': ['published', 'cancelled'],
    'published': ['clarification_period', 'submission_open', 'cancelled'],
    'clarification_period': ['submission_open', 'cancelled'],
    'submission_open': ['closed', 'cancelled'],
    'closed': ['technical_opening', 'cancelled'],
    'technical_opening': ['compliance_evaluation'],
    'compliance_evaluation': ['technical_evaluation', 'cancelled'],
    'technical_evaluation': ['technical_outcome_approved', 'cancelled'],
    'technical_outcome_approved': ['financial_opening'],
    'financial_opening': ['financial_evaluation'],
    'financial_evaluation': ['award_pending_approval', 'cancelled'],
    'award_pending_approval': ['award_published', 'cancelled'],
    'award_published': ['cooling_off'],
    'cooling_off': ['complaint_hold', 'ready_for_contract'],
    'complaint_hold': ['ready_for_contract', 'cancelled'],
    'ready_for_contract': ['archived'],
    'cancelled': ['archived'],
    'archived': [],
}

NOTIFIABLE = {
    'published': lambda p: (
        f'Tender published: {p.tender_number}',
        f'{p.title} has been published and is now visible to registered bidders.',
    ),
    'submission_open': lambda p: (
        f'Submissions open: {p.tender_number}',
        f'Bid submission is now open for {p.title}. Deadline: {p.submission_deadline}.',
    ),
    'award_published': lambda p: (
        f'Award decision published: {p.tender_number}',
        f'The award decision for {p.title} has been published. Cooling-off period is now in effect.',
    ),
    'cancelled': lambda p: (
        f'Tender cancelled: {p.tender_number}',
        f'{p.title} has been cancelled. Reason: {p.cancelled_reason or "not specified"}.',
    ),
}


def generate_tender_number():
    year = datetime.utcnow().year
    while True:
        candidate = f"TB-{year}-{random.randint(100, 999)}"
        if not Procurement.query.filter_by(tender_number=candidate).first():
            return candidate


@procurements_bp.route('/')
@login_required
def list_procurements():
    if current_user.has_role('bidder'):
        abort(403)
    procurements = Procurement.query.order_by(Procurement.created_at.desc()).all()
    return render_template('procurement_list.html', procurements=procurements)


@procurements_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('can_create_procurement')
def create():
    if request.method == 'POST':
        try:
            estimated_value = float(request.form['estimated_value'])
        except (KeyError, ValueError):
            flash('A valid estimated value is required.', 'danger')
            return render_template('procurement_create.html')

        deadline_raw = request.form.get('submission_deadline')
        deadline = datetime.fromisoformat(deadline_raw) if deadline_raw else None

        procurement = Procurement(
            tender_number=generate_tender_number(),
            title=request.form['title'],
            description=request.form.get('description'),
            category=request.form['category'],
            ppra_code=request.form.get('ppra_code'),
            method=request.form['method'],
            evaluation_method=request.form.get('evaluation_method'),
            envelope_type=request.form.get('envelope_type', 'single'),
            estimated_value=estimated_value,
            user_department=request.form.get('user_department'),
            submission_deadline=deadline,
            created_by_id=current_user.id,
            status='draft',
        )
        db.session.add(procurement)
        db.session.commit()

        log_action('PROCUREMENT_CREATED', entity_type='Procurement', entity_id=procurement.id,
                   new_value={'tender_number': procurement.tender_number, 'title': procurement.title})
        flash(f'Procurement {procurement.tender_number} created as Draft.', 'success')
        return redirect(url_for('procurements.detail', procurement_id=procurement.id))

    return render_template('procurement_create.html')


@procurements_bp.route('/<int:procurement_id>')
@login_required
def detail(procurement_id):
    procurement = Procurement.query.get_or_404(procurement_id)

    if current_user.has_role('bidder'):
        if procurement.status in ('draft', 'internal_review', 'approved_for_publication'):
            abort(404)

    committee = procurement.committee_members.all()
    communications = procurement.communications.order_by(Communication.created_at.desc()).limit(10).all()
    complaints = procurement.complaints.order_by(Complaint.created_at.desc()).all()
    submission_count = procurement.submissions.filter_by(status='submitted').count()
    next_status = TRANSITIONS.get(procurement.status, [None])[0] if TRANSITIONS.get(procurement.status) else None

    return render_template(
        'procurement_detail.html',
        procurement=procurement,
        committee=committee,
        communications=communications,
        complaints=complaints,
        submission_count=submission_count,
        next_status=next_status,
    )


@procurements_bp.route('/<int:procurement_id>/transition', methods=['POST'])
@login_required
def transition(procurement_id):
    procurement = Procurement.query.get_or_404(procurement_id)

    if not (current_user.role and (current_user.role.can_approve_procurement or current_user.role.can_publish
                                    or current_user.role.can_admin_system)):
        abort(403)

    to_status = request.form.get('to_status')
    allowed = TRANSITIONS.get(procurement.status, [])
    if to_status not in allowed:
        flash(f'Cannot move from {procurement.status_label()} to that status.', 'danger')
        return redirect(url_for('procurements.detail', procurement_id=procurement.id))

    if to_status == 'cancelled':
        reason = request.form.get('cancelled_reason', '').strip()
        if not reason:
            flash('A cancellation reason is required (SOAR 7.14).', 'danger')
            return redirect(url_for('procurements.detail', procurement_id=procurement.id))
        procurement.cancelled = True
        procurement.cancelled_reason = reason
        procurement.cancelled_at = datetime.utcnow()

    if to_status == 'submission_open':
        deadline_raw = request.form.get('submission_deadline')
        if deadline_raw:
            procurement.submission_deadline = datetime.fromisoformat(deadline_raw)
        elif not procurement.submission_deadline:
            flash('Set a submission deadline before opening submissions.', 'danger')
            return redirect(url_for('procurements.detail', procurement_id=procurement.id))

    previous_status = procurement.status
    procurement.status = to_status
    db.session.commit()

    log_action('PROCUREMENT_STATUS_CHANGED', entity_type='Procurement', entity_id=procurement.id,
               previous_value={'status': previous_status}, new_value={'status': to_status})

    if to_status in NOTIFIABLE:
        title, body = NOTIFIABLE[to_status](procurement)
        try:
            notify_bidders_on_procurement(procurement, 'status_change', title, body)
        except Exception as exc:
            print(f"Notification dispatch failed (non-fatal): {exc}")

    flash(f'Procurement moved to {to_status.replace("_", " ").title()}.', 'success')
    return redirect(url_for('procurements.detail', procurement_id=procurement.id))