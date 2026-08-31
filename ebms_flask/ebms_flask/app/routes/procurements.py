import io
import mimetypes
import os
import random
import secrets
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, send_file, send_from_directory, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models.procurement import Procurement
from app.models.communication import Communication
from app.models.clarification import ClarificationVisibility
from app.models.complaint import Complaint
from app.models.submission import Submission
from app.models.user import User
from app.models.role import Role
from app.models.bidder import Bidder
from app.models.payment import BidderPayment, BidderDocumentAccess
from app.models.evaluator_assignment import EvaluatorAssignment
from app.models.evaluator_feedback import EvaluatorFeedback
from app.models.budget_entry import BudgetEntry
from app.models.bidder_performance import BidderPerformance
from app.models.award import Award
from app.models.history import ProcurementHistory
from app.utils.decorators import permission_required, role_required
from app.utils.audit import log_action
from app.utils.crypto import decrypt_bytes
from app.utils.notify import notify_user, notify_bidders_on_procurement
from app.utils.clarification_access import ClarificationAccessService
from app.utils.evaluator_assignment import EvaluatorAssignmentService

procurements_bp = Blueprint('procurements', __name__, url_prefix='/procurements')


def _bidder_can_access_procurement(procurement):
    """Allow bidders into their workspace only for open or participated tenders."""
    if not current_user.bidder_id:
        return False
    if procurement.status in ('published', 'submission_open', 'clarification_period'):
        return True
    return bool(
        Submission.query.filter_by(
            procurement_id=procurement.id,
            bidder_id=current_user.bidder_id,
        ).first()
        or BidderPayment.query.filter_by(
            procurement_id=procurement.id,
            bidder_id=current_user.bidder_id,
        ).first()
    )


def _save_procurement_document(file_storage, tender_number, doc_type):
    if not file_storage or not file_storage.filename:
        return None, None
    token = secrets.token_hex(4)
    filename = secure_filename(f"{tender_number}_{doc_type}_{token}_{file_storage.filename}")
    doc_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'procurement_documents')
    os.makedirs(doc_dir, exist_ok=True)
    filepath = os.path.join(doc_dir, filename)
    file_storage.save(filepath)
    return filepath, file_storage.filename

# Legal status transitions (SOAR Appendix C). Kept as one explicit map so
# every route enforces the same lifecycle instead of re-implementing checks.
TRANSITIONS = {
    'draft': ['published', 'cancelled'],
    'internal_review': ['approved_for_publication', 'draft', 'cancelled'],
    'approved_for_publication': ['published', 'cancelled'],
    'published': ['submission_open', 'cancelled'],
    'clarification_period': ['submission_open', 'cancelled'],
    'submission_open': ['closed', 'cancelled'],
    'closed': ['under_evaluation', 'submission_open', 'cancelled'],
    'under_evaluation': ['submission_open', 'cancelled'],
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
    'closed': lambda p: (
        f'Submissions closed: {p.tender_number}',
        f'Bid submissions for {p.title} are now closed and the procurement is moving to evaluation preparation.',
    ),
    'under_evaluation': lambda p: (
        f'Procurement under evaluation: {p.tender_number}',
        f'Bid submissions for {p.title} are now under evaluation.',
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

    query = Procurement.query
    search_term = (request.args.get('q') or '').strip()
    status_filter = (request.args.get('status') or 'all').strip().lower()
    category_filter = (request.args.get('category') or 'all').strip().lower()
    method_filter = (request.args.get('method') or 'all').strip().lower()
    evaluation_filter = (request.args.get('evaluation_method') or 'all').strip().lower()
    envelope_filter = (request.args.get('envelope_type') or 'all').strip().lower()
    entity_filter = (request.args.get('entity') or '').strip()
    ppra_filter = (request.args.get('ppra_code') or '').strip()
    min_value = request.args.get('min_value', type=float)
    max_value = request.args.get('max_value', type=float)
    deadline_from = (request.args.get('deadline_from') or '').strip()
    deadline_to = (request.args.get('deadline_to') or '').strip()

    if search_term:
        like_term = f'%{search_term}%'
        query = query.filter(
            (Procurement.tender_number.ilike(like_term)) |
            (Procurement.title.ilike(like_term)) |
            (Procurement.description.ilike(like_term)) |
            (Procurement.procurement_entity.ilike(like_term)) |
            (Procurement.user_department.ilike(like_term)) |
            (Procurement.ppra_code.ilike(like_term))
        )
    if status_filter != 'all':
        query = query.filter(Procurement.status == status_filter)
    if category_filter != 'all':
        query = query.filter(Procurement.category == category_filter)
    if method_filter != 'all':
        query = query.filter(Procurement.method == method_filter)
    if evaluation_filter != 'all':
        query = query.filter(Procurement.evaluation_method == evaluation_filter)
    if envelope_filter != 'all':
        query = query.filter(Procurement.envelope_type == envelope_filter)
    if entity_filter:
        like_entity = f'%{entity_filter}%'
        query = query.filter(
            (Procurement.procurement_entity.ilike(like_entity)) |
            (Procurement.user_department.ilike(like_entity))
        )
    if ppra_filter:
        query = query.filter(Procurement.ppra_code.ilike(f'%{ppra_filter}%'))
    if min_value is not None:
        query = query.filter(Procurement.estimated_value >= min_value)
    if max_value is not None:
        query = query.filter(Procurement.estimated_value <= max_value)
    if deadline_from:
        try:
            query = query.filter(Procurement.submission_deadline >= datetime.fromisoformat(deadline_from))
        except ValueError:
            deadline_from = ''
    if deadline_to:
        try:
            query = query.filter(Procurement.submission_deadline <= datetime.fromisoformat(deadline_to).replace(hour=23, minute=59, second=59))
        except ValueError:
            deadline_to = ''

    page = max(request.args.get('page', 1, type=int), 1)
    procurement_page = query.order_by(Procurement.created_at.desc()).paginate(
        page=page, per_page=25, error_out=False
    )
    procurements = procurement_page.items
    return render_template(
        'procurement_list.html',
        procurements=procurements,
        search_term=search_term,
        status_filter=status_filter,
        category_filter=category_filter,
        method_filter=method_filter,
        evaluation_filter=evaluation_filter,
        envelope_filter=envelope_filter,
        entity_filter=entity_filter,
        ppra_filter=ppra_filter,
        min_value=request.args.get('min_value', ''),
        max_value=request.args.get('max_value', ''),
        deadline_from=deadline_from,
        deadline_to=deadline_to,
        page=procurement_page.page,
        total_pages=procurement_page.pages,
        total_results=procurement_page.total,
    )


@procurements_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('can_create_procurement')
def create():
    from app.models.request import FormDRequest, FormERequest, FormDERequest

    ppra_codes = Procurement.ppra_code_options()
    ppra_sub_codes = Procurement.ppra_sub_code_options()
    ppra_code_labels = Procurement.ppra_code_labels()

    # Optional combined Form D & E request that spawned this creation. The
    # request's documents and justification carry over into the record, and the
    # request is linked + marked converted once the procurement is created.
    request_id = request.args.get('request_id', type=int) or request.form.get('request_id', type=int)
    request_type = request.args.get('request_type') or request.form.get('request_type') or 'de'
    request_models = {'form_d': FormDRequest, 'form_e': FormERequest, 'de': FormDERequest}
    if request_type not in request_models:
        request_type = 'de'
    source_request = None
    if request_id:
        source_request = request_models[request_type].query.get_or_404(request_id)
        if source_request.status == 'converted' and source_request.procurement_id:
            flash('This request has already been converted — see its linked procurement record.', 'warning')
            return redirect(url_for('procurements.detail', procurement_id=source_request.procurement_id))

    source_form_d_path = None
    source_form_d_name = None
    source_form_e_path = None
    source_form_e_name = None
    if source_request:
        if request_type == 'de':
            source_form_d_path = source_request.form_d_file_path
            source_form_d_name = source_request.form_d_filename
            source_form_e_path = source_request.form_e_file_path
            source_form_e_name = source_request.form_e_filename
        elif request_type == 'form_d':
            source_form_d_path = source_request.submitted_form_path
            source_form_d_name = source_request.submitted_form_filename
        elif request_type == 'form_e':
            source_form_e_path = source_request.submitted_form_path
            source_form_e_name = source_request.submitted_form_filename

    if request.method == 'POST':
        envelope_type = (request.form.get('envelope_type') or '').strip().lower()
        if envelope_type not in ('single', 'dual'):
            flash('Please select whether this procurement uses a single or dual envelope.', 'danger')
            return render_template('procurement_create.html', ppra_codes=ppra_codes, ppra_sub_codes=ppra_sub_codes,
                                   ppra_code_labels=ppra_code_labels, source_request=source_request,
                                   request_type=request_type, form=request.form)

        try:
            estimated_value = float(request.form['estimated_value'])
        except (KeyError, ValueError):
            flash('A valid estimated value is required.', 'danger')
            return render_template('procurement_create.html', ppra_codes=ppra_codes, ppra_sub_codes=ppra_sub_codes,
                                   ppra_code_labels=ppra_code_labels, source_request=source_request,
                                   request_type=request_type, form=request.form)

        tender_fee = 0.0
        if request.form.get('tender_fee'):
            try:
                tender_fee = float(request.form.get('tender_fee'))
            except ValueError:
                tender_fee = 0.0

        procurement_entity = request.form.get('procurement_entity') or request.form.get('user_department')
        if not procurement_entity:
            flash('A procurement entity is required.', 'danger')
            return render_template('procurement_create.html', ppra_codes=ppra_codes, ppra_sub_codes=ppra_sub_codes,
                                   ppra_code_labels=ppra_code_labels, source_request=source_request,
                                   request_type=request_type, form=request.form)

        advertisement = request.files.get('advertisement_document')
        rfq_upload = request.files.get('rfq_document')
        itt_upload = request.files.get('itt_document')
        rfq_only = bool(
            rfq_upload and rfq_upload.filename and
            (not itt_upload or not itt_upload.filename)
        )
        if not rfq_only and (not advertisement or not advertisement.filename):
            flash('An advertisement document is required before creating the procurement.', 'danger')
            return render_template('procurement_create.html', ppra_codes=ppra_codes, ppra_sub_codes=ppra_sub_codes,
                                   ppra_code_labels=ppra_code_labels, source_request=source_request,
                                   request_type=request_type, form=request.form)

        ppra_base = request.form.get('ppra_code', '').strip()
        ppra_sub_code = request.form.get('ppra_sub_code', '').strip()
        ppra_description = (request.form.get('ppra_description') or '').strip()
        auto_ppra_description = Procurement.ppra_description(ppra_base, ppra_sub_code)
        if not ppra_description:
            ppra_description = auto_ppra_description
        ppra_code = ppra_base
        if ppra_sub_code and ppra_sub_code not in ('00', 'none'):
            ppra_code = f'{ppra_base}-{ppra_sub_code}'

        from app.models.site_setting import SiteSetting
        direct_threshold = float(SiteSetting.get('direct_procurement_threshold', '500000'))
        open_threshold = float(SiteSetting.get('open_procurement_threshold', '500000'))
        governance = Procurement(
            tender_number='TBD',
            title=request.form['title'],
            description=(request.form.get('description') or ppra_description or auto_ppra_description).strip() if (request.form.get('description') or ppra_description or auto_ppra_description) else None,
            category=request.form['category'],
            procurement_entity=procurement_entity,
            ppra_code=ppra_code,
            ppra_sub_code=ppra_sub_code if ppra_sub_code and ppra_sub_code not in ('00', 'none') else None,
            method=request.form['method'],
            evaluation_method=request.form.get('evaluation_method'),
            envelope_type=envelope_type,
            estimated_value=estimated_value,
            tender_fee=tender_fee,
            user_department=procurement_entity,
            status='draft',
        ).check_governance_rules(direct_threshold=direct_threshold, open_threshold=open_threshold)

        if governance['errors']:
            flash('Direct procurement exceeds the approved threshold and is not permitted.', 'danger')
            return render_template('procurement_create.html', ppra_codes=ppra_codes, ppra_sub_codes=ppra_sub_codes,
                                   ppra_code_labels=ppra_code_labels, source_request=source_request,
                                   request_type=request_type, form=request.form)

        if governance['warnings']:
            flash('Governance check noted a review risk: lot splitting or high-value procedure review required.', 'warning')

        deadline_raw = request.form.get('submission_deadline')
        clarification_deadline_raw = request.form.get('clarification_deadline')
        try:
            deadline = datetime.fromisoformat(deadline_raw) if deadline_raw else None
        except ValueError:
            flash('Please enter a valid submission deadline.', 'danger')
            return render_template('procurement_create.html', ppra_codes=ppra_codes, ppra_sub_codes=ppra_sub_codes,
                                   ppra_code_labels=ppra_code_labels, source_request=source_request,
                                   request_type=request_type, form=request.form)
        if deadline and deadline.date() <= datetime.utcnow().date():
            flash('The submission deadline must be tomorrow or a later date.', 'danger')
            return render_template('procurement_create.html', ppra_codes=ppra_codes, ppra_sub_codes=ppra_sub_codes,
                                   ppra_code_labels=ppra_code_labels, source_request=source_request,
                                   request_type=request_type, form=request.form)
        try:
            clarification_deadline = datetime.fromisoformat(clarification_deadline_raw) if clarification_deadline_raw else None
        except ValueError:
            flash('Please enter a valid clarification deadline.', 'danger')
            return render_template('procurement_create.html', ppra_codes=ppra_codes, ppra_sub_codes=ppra_sub_codes,
                                   ppra_code_labels=ppra_code_labels, source_request=source_request,
                                   request_type=request_type, form=request.form)
        if clarification_deadline and clarification_deadline.date() <= datetime.utcnow().date():
            flash('The clarification deadline must be tomorrow or a later date.', 'danger')
            return render_template('procurement_create.html', ppra_codes=ppra_codes, ppra_sub_codes=ppra_sub_codes,
                                   ppra_code_labels=ppra_code_labels, source_request=source_request,
                                   request_type=request_type, form=request.form)

        tender_number = generate_tender_number()

        # Handle document uploads. When created from a combined Form D & E
        # request, the request's attached forms are carried over automatically
        # (they may still be replaced on this screen).
        form_d_path, form_d_name = _save_procurement_document(request.files.get('form_d_document'), tender_number, 'form_d')
        if source_form_d_path and not form_d_path:
            form_d_path, form_d_name = source_form_d_path, source_form_d_name
        form_e_path, form_e_name = _save_procurement_document(request.files.get('form_e_document'), tender_number, 'form_e')
        if source_form_e_path and not form_e_path:
            form_e_path, form_e_name = source_form_e_path, source_form_e_name
        itt_path, itt_name = _save_procurement_document(request.files.get('itt_document'), tender_number, 'itt')
        rfq_path, rfq_name = _save_procurement_document(request.files.get('rfq_document'), tender_number, 'rfq')

        procurement = Procurement(
            tender_number=tender_number,
            title=request.form['title'],
            description=request.form.get('description'),
            category=request.form['category'],
            procurement_entity=procurement_entity,
            ppra_code=ppra_code,
            ppra_sub_code=ppra_sub_code if ppra_sub_code and ppra_sub_code not in ('00', 'none') else None,
            method=request.form['method'],
            evaluation_method=request.form.get('evaluation_method'),
            envelope_type=envelope_type,
            estimated_value=estimated_value,
            tender_fee=tender_fee,
            user_department=procurement_entity,
            submission_deadline=deadline,
            clarification_deadline=clarification_deadline,
            form_d_file_path=form_d_path,
            form_d_filename=form_d_name,
            form_e_file_path=form_e_path,
            form_e_filename=form_e_name,
            itt_file_path=itt_path,
            itt_filename=itt_name,
            rfq_file_path=rfq_path,
            rfq_filename=rfq_name,
            created_by_id=current_user.id,
            status='draft',
        )
        db.session.add(procurement)
        db.session.commit()

        if advertisement and advertisement.filename:
            filename = secure_filename(f"{procurement.tender_number}_{secrets.token_hex(4)}_{advertisement.filename}")
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            advertisement.save(filepath)

            doc = Communication(
                procurement_id=procurement.id,
                type='advertisement',
                content=f'Advertisement document for {procurement.title}',
                file_path=filepath,
                original_filename=advertisement.filename,
                is_public=True,
                from_user_id=current_user.id,
            )
            db.session.add(doc)
            db.session.commit()

        log_action('PROCUREMENT_CREATED', entity_type='Procurement', entity_id=procurement.id,
                   new_value={'tender_number': procurement.tender_number, 'title': procurement.title,
                              'has_form_d': bool(form_d_path), 'has_form_e': bool(form_e_path),
                              'has_itt': bool(itt_path),
                              'has_rfq': bool(rfq_path)})

        if source_request is not None:
            source_request.procurement_id = procurement.id
            source_request.status = 'converted'
            source_request.converted_by_id = current_user.id
            source_request.converted_at = datetime.utcnow()
            db.session.commit()

            log_action(f'REQUEST_{request_type.upper()}_CONVERTED', entity_type=type(source_request).__name__, entity_id=source_request.id,
                       new_value={'tender_number': procurement.tender_number, 'procurement_id': procurement.id,
                                  'status': 'converted'})
            try:
                notify_user(
                    source_request.requester, 'request_converted',
                    f'Your Form D & E request was converted ({procurement.tender_number})',
                    f'Your procurement request from {getattr(source_request, "department", None) or getattr(source_request, "procurement_entity", None) or "your department"} has been '
                    f'converted into procurement record {procurement.tender_number}. Track it under Procurements.',
                )
            except Exception as exc:
                print(f"Requester notification failed (non-fatal): {exc}")

        flash(f'Procurement {procurement.tender_number} created as Draft with submitted documents.', 'success')
        return redirect(url_for('procurements.detail', procurement_id=procurement.id))

    return render_template('procurement_create.html', ppra_codes=ppra_codes, ppra_sub_codes=ppra_sub_codes,
                           ppra_code_labels=ppra_code_labels, source_request=source_request,
                           request_type=request_type)


@procurements_bp.route('/search')
@login_required
def search():
    query = (request.args.get('q') or '').strip()
    procurements = []
    users = []
    if query:
        pattern = f'%{query}%'
        procurement_query = Procurement.query.filter(
            or_(
                Procurement.title.ilike(pattern),
                Procurement.tender_number.ilike(pattern),
                Procurement.description.ilike(pattern),
                Procurement.procurement_entity.ilike(pattern),
                Procurement.user_department.ilike(pattern),
                Procurement.ppra_code.ilike(pattern),
            )
        )
        if current_user.has_role('bidder') or current_user.bidder_id:
            procurement_query = procurement_query.filter(
                or_(
                    Procurement.status.in_(['published', 'submission_open', 'clarification_period']),
                    Procurement.id.in_(db.session.query(Submission.procurement_id).filter_by(
                        bidder_id=current_user.bidder_id
                    )),
                    Procurement.id.in_(db.session.query(BidderPayment.procurement_id).filter_by(
                        bidder_id=current_user.bidder_id
                    )),
                )
            )
        procurements = procurement_query.order_by(Procurement.created_at.desc()).all()
        if not (current_user.has_role('bidder') or current_user.bidder_id):
            users = User.query.filter(
                or_(
                    User.first_name.ilike(pattern),
                    User.last_name.ilike(pattern),
                    User.email.ilike(pattern),
                    User.department.ilike(pattern),
                )
            ).order_by(User.first_name.asc()).limit(20).all()
    return render_template('global_search.html', query=query, procurements=procurements, users=users)


@procurements_bp.route('/<int:procurement_id>')
@login_required
def detail(procurement_id):
    procurement = Procurement.query.get_or_404(procurement_id)

    if current_user.has_role('bidder') or current_user.bidder_id:
        if not _bidder_can_access_procurement(procurement):
            abort(404)
        return redirect(url_for('bidders.workspace', procurement_id=procurement.id))
    elif not current_user.can_access_procurement(procurement):
        abort(403)

    committee = procurement.committee_members.all()
    communications_query = procurement.communications.filter(
        Communication.type.in_(['clarification', 'question'])
    )
    if current_user.has_role('bidder') or current_user.bidder_id:
        communications_query = communications_query.filter(
            or_(
                Communication.visibility_type == 'public',
                Communication.id.in_(
                    db.session.query(ClarificationVisibility.communication_id).filter_by(
                        bidder_id=current_user.bidder_id
                    ).filter(ClarificationVisibility.revoked_at.is_(None))
                ),
                Communication.visibility_type.is_(None)
            )
        )
    communications = communications_query.order_by(Communication.created_at.desc()).limit(10).all()
    complaints = procurement.complaints.order_by(Complaint.created_at.desc()).all()
    submissions = procurement.submissions.options(
        selectinload(Submission.bidder)
    ).filter_by(status='submitted').order_by(Submission.submitted_at.desc()).all()
    submission_count = len(submissions)
    next_status = TRANSITIONS.get(procurement.status, [None])[0] if TRANSITIONS.get(procurement.status) else None
    if procurement.status not in ('draft', 'published') and not (
        procurement.status == 'submission_open'
        and procurement.submission_deadline
        and datetime.utcnow() >= procurement.submission_deadline
    ) and not procurement.status == 'closed':
        next_status = None

    # Payments for Procurement verification
    payments = BidderPayment.query.options(
        selectinload(BidderPayment.bidder)
    ).filter_by(procurement_id=procurement.id).order_by(BidderPayment.submitted_at.desc()).all()
    pending_payments_count = sum(1 for p in payments if p.status == 'pending')

    # Evaluator assignments UI (post-closure, visible to Procurement role).
    can_assign_evaluators = EvaluatorAssignmentService.is_manager(current_user)
    can_create_assignment = can_assign_evaluators and EvaluatorAssignmentService.is_post_closure(procurement)
    evaluator_assignments = (
        EvaluatorAssignmentService.list_for_procurement(procurement.id)
        if can_assign_evaluators else []
    )
    evaluator_candidates = (
        EvaluatorAssignmentService.eligible_evaluators()
        if can_create_assignment else []
    )
    budget_entries = procurement.budget_entries.order_by(BudgetEntry.entry_date.desc(), BudgetEntry.id.desc()).all()
    budget_spend = sum((entry.signed_amount for entry in budget_entries), Decimal('0'))
    budget_value = Decimal(str(procurement.estimated_value or 0))
    budget_remaining = budget_value - budget_spend
    performance_reviews = procurement.bidder_performance_reviews.order_by(
        BidderPerformance.reviewed_at.desc()
    ).all()

    return render_template(
        'procurement_detail.html',
        procurement=procurement,
        committee=committee,
        communications=communications,
        complaints=complaints,
        submissions=submissions,
        submission_count=submission_count,
        next_status=next_status,
        payments=payments,
        pending_payments_count=pending_payments_count,
        can_assign_evaluators=can_assign_evaluators,
        can_create_assignment=can_create_assignment,
        evaluator_assignments=evaluator_assignments,
        evaluator_candidates=evaluator_candidates,
        evaluator_feedback=procurement.evaluator_feedback.order_by(
            EvaluatorFeedback.submitted_at.desc()
        ).all(),
        can_view_procurement_workspace=_procurement_management_access(procurement),
        budget_entries=budget_entries,
        budget_spend=budget_spend,
        budget_remaining=budget_remaining,
        performance_reviews=performance_reviews,
    )


@procurements_bp.route('/<int:procurement_id>/award', methods=['GET', 'POST'])
@login_required
def award_workspace(procurement_id):
    if not (
        current_user.has_permission('can_award')
        or current_user.has_role('procurement_unit')
    ):
        abort(403)
    procurement = Procurement.query.get_or_404(procurement_id)
    if procurement.status not in (
        'under_evaluation', 'technical_opening', 'compliance_evaluation',
        'technical_evaluation', 'technical_outcome_approved', 'financial_opening',
        'financial_evaluation', 'award_pending_approval', 'award_published',
        'cooling_off', 'complaint_hold', 'ready_for_contract', 'archived',
    ):
        flash('This procurement is not ready for award review.', 'warning')
        return redirect(url_for('procurements.detail', procurement_id=procurement.id))

    submitted = procurement.submissions.filter_by(status='submitted').all()
    bidder_ids = {submission.bidder_id for submission in submitted}
    evaluations = procurement.evaluations.all()
    scores = {}
    for evaluation in evaluations:
        score = evaluation.consensus_score if evaluation.consensus_score is not None else evaluation.score
        if score is not None:
            scores.setdefault(evaluation.bidder_id, []).append(float(score))
    bidders = []
    feedback_document_count = procurement.evaluator_feedback.count()
    for bidder_id in bidder_ids:
        bidder = Bidder.query.get(bidder_id)
        bidder_scores = scores.get(bidder_id, [])
        bidder_evaluations = [e for e in evaluations if e.bidder_id == bidder_id]
        bidders.append({
            'bidder': bidder,
            'submission_count': sum(1 for submission in submitted if submission.bidder_id == bidder_id),
            'score': round(sum(bidder_scores) / len(bidder_scores), 2) if bidder_scores else None,
            'evaluation_count': len(bidder_scores),
            'written_feedback_count': sum(
                1 for e in bidder_evaluations if e.comments or e.evidence_references
            ),
            'feedback_document_count': feedback_document_count,
        })
    bidders.sort(key=lambda row: (row['score'] is not None, row['score'] or 0), reverse=True)

    award = procurement.award
    evaluator_feedback = procurement.evaluator_feedback.order_by(
        EvaluatorFeedback.submitted_at.desc()
    ).all()
    if request.method == 'POST':
        action = request.form.get('action')
        if action in ('publish', 'award_tender'):
            if action == 'publish' and (not award or procurement.status != 'award_pending_approval'):
                flash('Save an award recommendation before publishing it.', 'danger')
                return redirect(url_for('procurements.award_workspace', procurement_id=procurement.id))
            if action == 'award_tender':
                winning_bidder_id = request.form.get('winning_bidder_id', type=int)
                winner = Bidder.query.get(winning_bidder_id) if winning_bidder_id else None
                if not winner or winner.id not in bidder_ids:
                    flash('Select a bidder with a submitted bid before awarding the tender.', 'danger')
                    return redirect(url_for('procurements.award_workspace', procurement_id=procurement.id))
                try:
                    award_value = float(request.form.get('award_value') or procurement.estimated_value or 0)
                except ValueError:
                    flash('Enter a valid award value.', 'danger')
                    return redirect(url_for('procurements.award_workspace', procurement_id=procurement.id))
                if not award:
                    award = Award(procurement_id=procurement.id, created_by_id=current_user.id)
                    db.session.add(award)
                award.winning_bidder_id = winner.id
                award.award_value = award_value
                award.decision_reason = (request.form.get('decision_reason') or '').strip()
                award.decision_notes = (request.form.get('decision_notes') or '').strip() or None
                award.cooling_off_expiry = datetime.utcnow() + timedelta(days=10)
            award.published_at = datetime.utcnow()
            award.published_by_id = current_user.id
            procurement.status = 'award_published'
            db.session.commit()
            for bidder_user in User.query.filter_by(bidder_id=award.winning_bidder_id).all():
                notify_user(
                    bidder_user,
                    'award_published',
                    f'Award Published: {procurement.tender_number}',
                    f'Your bid for {procurement.title} has been selected. The cooling-off period ends on {award.cooling_off_expiry:%d %b %Y}.',
                    procurement_id=procurement.id,
                    email=False,
                )
            flash('Tender awarded successfully. The winning bidder was notified and the cooling-off period is now active.', 'success')
            return redirect(url_for('procurements.award_workspace', procurement_id=procurement.id))

        winning_bidder_id = request.form.get('winning_bidder_id', type=int)
        winner = Bidder.query.get(winning_bidder_id) if winning_bidder_id else None
        if not winner or winner.id not in bidder_ids:
            flash('Select a bidder with a submitted bid.', 'danger')
            return redirect(url_for('procurements.award_workspace', procurement_id=procurement.id))
        try:
            award_value = float(request.form.get('award_value') or procurement.estimated_value or 0)
        except ValueError:
            flash('Enter a valid award value.', 'danger')
            return redirect(url_for('procurements.award_workspace', procurement_id=procurement.id))
        if not award:
            award = Award(procurement_id=procurement.id, created_by_id=current_user.id)
            db.session.add(award)
        award.winning_bidder_id = winner.id
        award.award_value = award_value
        award.decision_reason = (request.form.get('decision_reason') or '').strip()
        award.decision_notes = (request.form.get('decision_notes') or '').strip() or None
        award.cooling_off_expiry = datetime.utcnow() + timedelta(days=10)
        procurement.status = 'award_pending_approval'
        db.session.commit()
        flash('Award recommendation saved and ready for publication.', 'success')
        return redirect(url_for('procurements.award_workspace', procurement_id=procurement.id))

    return render_template(
        'procurement_award.html',
        procurement=procurement,
        bidders=bidders,
        award=award,
        evaluator_feedback=evaluator_feedback,
    )


def _procurement_management_access(procurement):
    return bool(
        current_user.role
        and not current_user.has_role('bidder')
        and (
            current_user.can_access_procurement(procurement)
            or current_user.has_permission('can_view_all_records')
            or current_user.has_permission('can_create_procurement')
            or current_user.has_permission('can_approve_procurement')
            or current_user.has_permission('can_award')
        )
    )


def _load_budget_workspace(procurement):
    entries = procurement.budget_entries.order_by(
        BudgetEntry.entry_date.desc(), BudgetEntry.id.desc()
    ).all()
    spend = sum((entry.signed_amount for entry in entries), Decimal('0'))
    budget = Decimal(str(procurement.estimated_value or 0))
    return entries, spend, budget - spend


@procurements_bp.route('/<int:procurement_id>/budget-spend')
@login_required
def budget_spend(procurement_id):
    procurement = Procurement.query.get_or_404(procurement_id)
    if not _procurement_management_access(procurement):
        abort(403)
    budget_entries, budget_spend, budget_remaining = _load_budget_workspace(procurement)
    return render_template(
        'procurement_budget.html',
        procurement=procurement,
        budget_entries=budget_entries,
        budget_spend=budget_spend,
        budget_remaining=budget_remaining,
    )


@procurements_bp.route('/<int:procurement_id>/bidder-performance')
@login_required
def bidder_performance(procurement_id):
    procurement = Procurement.query.get_or_404(procurement_id)
    if not _procurement_management_access(procurement):
        abort(403)
    return render_template(
        'procurement_performance.html',
        procurement=procurement,
        performance_reviews=procurement.bidder_performance_reviews.order_by(
            BidderPerformance.reviewed_at.desc()
        ).all(),
        performance_bidders=Bidder.query.filter_by(active=True).order_by(
            Bidder.company_name
        ).all(),
    )


@procurements_bp.route('/<int:procurement_id>/payment-verification')
@login_required
def payment_verification(procurement_id):
    procurement = Procurement.query.get_or_404(procurement_id)
    if not _procurement_management_access(procurement):
        abort(403)
    payments = BidderPayment.query.options(
        selectinload(BidderPayment.bidder),
        selectinload(BidderPayment.reviewed_by),
    ).filter_by(procurement_id=procurement.id).order_by(BidderPayment.submitted_at.desc()).all()
    return render_template(
        'procurement_payment_verification.html',
        procurement=procurement,
        payments=payments,
    )


@procurements_bp.route('/<int:procurement_id>/sealed-bid-submissions')
@login_required
def sealed_bid_submissions(procurement_id):
    procurement = Procurement.query.get_or_404(procurement_id)
    if not _procurement_management_access(procurement):
        abort(403)
    submissions = procurement.submissions.options(
        selectinload(Submission.bidder)
    ).filter_by(status='submitted').order_by(Submission.submitted_at.desc()).all()
    return render_template(
        'procurement_sealed_bids.html',
        procurement=procurement,
        submissions=submissions,
        submission_count=len(submissions),
    )


@procurements_bp.route('/<int:procurement_id>/budget-entry', methods=['POST'])
@login_required
def add_budget_entry(procurement_id):
    procurement = Procurement.query.get_or_404(procurement_id)
    if not _procurement_management_access(procurement):
        abort(403)

    try:
        amount = Decimal((request.form.get('amount') or '').strip())
        if amount <= 0:
            raise InvalidOperation
    except InvalidOperation:
        flash('Enter a valid positive budget amount.', 'danger')
        return redirect(url_for('procurements.budget_spend', procurement_id=procurement.id))

    entry_type = (request.form.get('entry_type') or '').strip().lower()
    description = (request.form.get('description') or '').strip()
    if entry_type not in BudgetEntry.ENTRY_TYPES or not description:
        flash('Select an entry type and provide a description.', 'danger')
        return redirect(url_for('procurements.budget_spend', procurement_id=procurement.id))

    entry_date = date.today()
    if request.form.get('entry_date'):
        try:
            entry_date = date.fromisoformat(request.form['entry_date'])
        except ValueError:
            flash('Enter a valid entry date.', 'danger')
            return redirect(url_for('procurements.budget_spend', procurement_id=procurement.id))

    entry = BudgetEntry(
        procurement_id=procurement.id,
        entry_type=entry_type,
        description=description,
        amount=amount,
        reference=(request.form.get('reference') or '').strip() or None,
        entry_date=entry_date,
        created_by_id=current_user.id,
    )
    db.session.add(entry)
    db.session.commit()
    log_action('PROCUREMENT_BUDGET_ENTRY_CREATED', entity_type='BudgetEntry', entity_id=entry.id,
               new_value={'procurement_id': procurement.id, 'entry_type': entry_type, 'amount': str(amount)})
    flash('Budget transaction recorded.', 'success')
    return redirect(url_for('procurements.budget_spend', procurement_id=procurement.id))


@procurements_bp.route('/<int:procurement_id>/performance-review', methods=['POST'])
@login_required
def add_performance_review(procurement_id):
    procurement = Procurement.query.get_or_404(procurement_id)
    if not _procurement_management_access(procurement):
        abort(403)

    bidder_id = request.form.get('bidder_id', type=int)
    bidder = Bidder.query.get(bidder_id) if bidder_id else None
    scores = [request.form.get(name, type=int) for name in ('delivery_score', 'quality_score', 'compliance_score')]
    if not bidder or any(score is None or score < 1 or score > 5 for score in scores):
        flash('Select a bidder and provide scores from 1 to 5.', 'danger')
        return redirect(url_for('procurements.bidder_performance', procurement_id=procurement.id))

    overall_score = round(sum(scores) / 3, 2)
    review = BidderPerformance(
        procurement_id=procurement.id,
        bidder_id=bidder.id,
        delivery_score=scores[0],
        quality_score=scores[1],
        compliance_score=scores[2],
        overall_score=overall_score,
        status=(request.form.get('status') or 'under_review').strip()
            if (request.form.get('status') or 'under_review').strip() in BidderPerformance.STATUSES
            else 'under_review',
        notes=(request.form.get('notes') or '').strip() or None,
        reviewed_by_id=current_user.id,
    )
    db.session.add(review)
    db.session.commit()
    log_action('BIDDER_PERFORMANCE_RECORDED', entity_type='BidderPerformance', entity_id=review.id,
               new_value={'procurement_id': procurement.id, 'bidder_id': bidder.id, 'overall_score': overall_score})
    flash('Bidder performance review recorded.', 'success')
    return redirect(url_for('procurements.bidder_performance', procurement_id=procurement.id))


@procurements_bp.route('/<int:procurement_id>/upload-documents', methods=['POST'])
@login_required
def upload_documents(procurement_id):
    procurement = Procurement.query.get_or_404(procurement_id)

    is_submitting_evaluator = (
        feedback.evaluator_id == current_user.id
        and EvaluatorAssignment.active_for(procurement.id, current_user.id)
    )
    if current_user.has_role('bidder') or (
        not current_user.can_access_procurement(procurement) and not is_submitting_evaluator
    ):
        abort(403)

    uploaded = []
    if request.files.get('form_d_document'):
        path, name = _save_procurement_document(request.files['form_d_document'], procurement.tender_number, 'form_d')
        if path:
            procurement.form_d_file_path = path
            procurement.form_d_filename = name
            uploaded.append('FORM D')

    if request.files.get('form_e_document'):
        path, name = _save_procurement_document(request.files['form_e_document'], procurement.tender_number, 'form_e')
        if path:
            procurement.form_e_file_path = path
            procurement.form_e_filename = name
            uploaded.append('FORM E')

    if request.files.get('itt_document'):
        path, name = _save_procurement_document(request.files['itt_document'], procurement.tender_number, 'itt')
        if path:
            procurement.itt_file_path = path
            procurement.itt_filename = name
            uploaded.append('ITT')

    if request.files.get('rfq_document'):
        path, name = _save_procurement_document(request.files['rfq_document'], procurement.tender_number, 'rfq')
        if path:
            procurement.rfq_file_path = path
            procurement.rfq_filename = name
            uploaded.append('RFQ')

    if request.form.get('tender_fee'):
        try:
            procurement.tender_fee = float(request.form.get('tender_fee'))
        except ValueError:
            pass

    if uploaded:
        db.session.commit()
        log_action('PROCUREMENT_DOCUMENTS_UPLOADED', entity_type='Procurement', entity_id=procurement.id,
                   new_value={'uploaded': uploaded, 'tender_fee': float(procurement.tender_fee or 0)})
        flash(f"Successfully uploaded: {', '.join(uploaded)}.", 'success')
    else:
        flash("No valid documents selected for upload.", 'info')

    return redirect(url_for('procurements.detail', procurement_id=procurement.id))


@procurements_bp.route('/<int:procurement_id>/tender-docs/<string:doc_type>/download')
@login_required
def download_tender_document(procurement_id, doc_type):
    procurement = Procurement.query.get_or_404(procurement_id)
    doc_type = doc_type.lower()

    if doc_type == 'form_d':
        filepath = procurement.form_d_file_path
        filename = procurement.form_d_filename
    elif doc_type == 'form_e':
        filepath = procurement.form_e_file_path
        filename = procurement.form_e_filename
    elif doc_type == 'itt':
        filepath = procurement.itt_file_path
        filename = procurement.itt_filename
    elif doc_type == 'rfq':
        filepath = procurement.rfq_file_path
        filename = procurement.rfq_filename
    else:
        abort(404)

    # STRICT ACCESS CONTROL FIRST
    if doc_type in ('form_d', 'form_e'):
        # Internal requesting department and procurement only. Never bidders.
        if current_user.has_role('bidder'):
            log_action('UNAUTHORIZED_FORM_ACCESS_BLOCKED', entity_type='ProcurementDocument', entity_id=procurement.id,
                       reason=f"Bidder {current_user.bidder_id} attempted direct access to {doc_type.upper()}")
            abort(403)
        if not current_user.can_access_procurement(procurement):
            abort(403)

    elif doc_type == 'itt':
        # Gated by payment approval for bidders
        if current_user.has_role('bidder'):
            if procurement.status not in ('published', 'submission_open', 'clarification_period'):
                abort(404)
            if not current_user.bidder_id:
                abort(403)

            has_access = BidderDocumentAccess.can_bidder_access(procurement.id, current_user.bidder_id, doc_type)
            if not has_access:
                log_action('UNAUTHORIZED_DOCUMENT_ACCESS_BLOCKED', entity_type='ProcurementDocument', entity_id=procurement.id,
                           reason=f"Unapproved Bidder {current_user.bidder_id} attempted direct access to {doc_type.upper()}")
                abort(403)

    elif doc_type == 'rfq' and current_user.has_role('bidder'):
        if procurement.status not in ('published', 'submission_open', 'clarification_period'):
            abort(404)

    if not filepath or not filename or not os.path.exists(filepath):
        abort(404)

    directory = os.path.dirname(filepath)
    basename = os.path.basename(filepath)

    log_action('DOCUMENT_DOWNLOADED', entity_type='ProcurementDocument', entity_id=procurement.id,
               new_value={'doc_type': doc_type, 'filename': filename, 'user_id': current_user.id,
                          'bidder_id': current_user.bidder_id if current_user.has_role('bidder') else None})

    return send_from_directory(directory, basename, as_attachment=True, download_name=filename)


@procurements_bp.route('/<int:procurement_id>/tender-docs/<string:doc_type>/view')
@login_required
def view_tender_document(procurement_id, doc_type):
    procurement = Procurement.query.get_or_404(procurement_id)
    doc_type = doc_type.lower()

    if doc_type == 'form_d':
        filepath = procurement.form_d_file_path
        filename = procurement.form_d_filename
    elif doc_type == 'form_e':
        filepath = procurement.form_e_file_path
        filename = procurement.form_e_filename
    elif doc_type == 'itt':
        filepath = procurement.itt_file_path
        filename = procurement.itt_filename
    elif doc_type == 'rfq':
        filepath = procurement.rfq_file_path
        filename = procurement.rfq_filename
    else:
        abort(404)

    # STRICT ACCESS CONTROL FIRST
    if doc_type in ('form_d', 'form_e'):
        if current_user.has_role('bidder') or not current_user.can_access_procurement(procurement):
            log_action('UNAUTHORIZED_FORM_ACCESS_BLOCKED', entity_type='ProcurementDocument', entity_id=procurement.id,
                       reason=f"Bidder/User attempted direct inline view of {doc_type.upper()}")
            abort(403)

    elif doc_type == 'itt':
        if current_user.has_role('bidder'):
            if procurement.status not in ('published', 'submission_open', 'clarification_period'):
                abort(404)
            if not current_user.bidder_id or not BidderDocumentAccess.can_bidder_access(procurement.id, current_user.bidder_id, doc_type):
                log_action('UNAUTHORIZED_DOCUMENT_ACCESS_BLOCKED', entity_type='ProcurementDocument', entity_id=procurement.id,
                           reason=f"Unapproved Bidder {current_user.bidder_id} attempted direct inline view of {doc_type.upper()}")
                abort(403)

    elif doc_type == 'rfq' and current_user.has_role('bidder'):
        if procurement.status not in ('published', 'submission_open', 'clarification_period'):
            abort(404)

    if not filepath or not filename or not os.path.exists(filepath):
        abort(404)

    directory = os.path.dirname(filepath)
    basename = os.path.basename(filepath)

    log_action('DOCUMENT_VIEWED', entity_type='ProcurementDocument', entity_id=procurement.id,
               new_value={'doc_type': doc_type, 'filename': filename, 'user_id': current_user.id,
                          'bidder_id': current_user.bidder_id if current_user.has_role('bidder') else None})

    return send_from_directory(directory, basename, as_attachment=False, download_name=filename)


@procurements_bp.route('/payments/<int:payment_id>/proof')
@login_required
def download_payment_proof(payment_id):
    payment = BidderPayment.query.get_or_404(payment_id)

    # Bidder can only view their own proof. Procurement/Admin staff can view any.
    if current_user.has_role('bidder'):
        if payment.bidder_id != current_user.bidder_id:
            abort(403)
    else:
        # Check that user is internal staff
        if not (current_user.has_role('system_admin') or current_user.has_role('procurement_unit') or
                current_user.has_role('procurement_oversight') or current_user.has_role('accounting_officer')):
            abort(403)

        log_action('PAYMENT_PROOF_VIEWED', entity_type='BidderPayment', entity_id=payment.id,
                   new_value={'payment_reference': payment.payment_reference, 'bidder_id': payment.bidder_id,
                              'procurement_id': payment.procurement_id})

    if not payment.proof_file_path or not os.path.exists(payment.proof_file_path):
        abort(404)

    directory = os.path.dirname(payment.proof_file_path)
    basename = os.path.basename(payment.proof_file_path)
    return send_from_directory(directory, basename, as_attachment=True, download_name=payment.proof_filename)


@procurements_bp.route('/payments/<int:payment_id>/supporting-document')
@login_required
def download_payment_supporting_document(payment_id):
    payment = BidderPayment.query.get_or_404(payment_id)

    if current_user.has_role('bidder'):
        if payment.bidder_id != current_user.bidder_id:
            abort(403)
    else:
        if not (current_user.has_role('system_admin') or current_user.has_role('procurement_unit') or
                current_user.has_role('procurement_oversight') or current_user.has_role('accounting_officer')):
            abort(403)

    if not payment.supporting_document_path or not os.path.exists(payment.supporting_document_path):
        abort(404)

    directory = os.path.dirname(payment.supporting_document_path)
    basename = os.path.basename(payment.supporting_document_path)
    return send_from_directory(directory, basename, as_attachment=True, download_name=payment.supporting_document_filename)


@procurements_bp.route('/payments/<int:payment_id>/verify', methods=['POST'])
@login_required
def verify_payment(payment_id):
    payment = BidderPayment.query.get_or_404(payment_id)
    procurement = payment.procurement

    # Must have procurement approval or management permissions
    if current_user.has_role('bidder'):
        abort(403)
    if not (current_user.has_role('system_admin') or current_user.has_role('procurement_unit') or
            current_user.has_role('procurement_oversight') or (current_user.role and current_user.role.can_approve_procurement)):
        abort(403)

    action = request.form.get('action')  # approve, reject, request_resubmission, revoke
    reason = (request.form.get('reason') or '').strip()

    terminal_actions = {
        'approve': 'approved',
        'reject': 'rejected',
        'request_resubmission': 'resubmission_required',
    }
    if action in terminal_actions and payment.status == terminal_actions[action]:
        flash(
            f'This payment is already {payment.status.replace("_", " ")}. '
            'No duplicate notification was sent.',
            'info',
        )
        return redirect(request.referrer or url_for('procurements.detail', procurement_id=procurement.id))

    bidder_users = User.query.filter_by(bidder_id=payment.bidder_id).all()

    if action == 'approve':
        payment.status = 'approved'
        payment.reviewed_by_id = current_user.id
        payment.reviewed_at = datetime.utcnow()
        payment.notes = reason or 'Payment verified and approved by Procurement.'

        # Grant access to the paid ITT document.
        for doc_type in ('itt', 'all_bidder_docs'):
            access = BidderDocumentAccess.query.filter_by(
                procurement_id=procurement.id,
                bidder_id=payment.bidder_id,
                document_type=doc_type
            ).first()

            if access:
                access.status = 'active'
                access.payment_id = payment.id
                access.granted_by_id = current_user.id
                access.granted_at = datetime.utcnow()
                access.revoked_by_id = None
                access.revoked_at = None
                access.revocation_reason = None
            else:
                access = BidderDocumentAccess(
                    procurement_id=procurement.id,
                    bidder_id=payment.bidder_id,
                    document_type=doc_type,
                    payment_id=payment.id,
                    status='active',
                    granted_by_id=current_user.id,
                    granted_at=datetime.utcnow()
                )
                db.session.add(access)

        db.session.commit()

        log_action('PAYMENT_APPROVED', entity_type='BidderPayment', entity_id=payment.id,
                   new_value={'bidder_id': payment.bidder_id, 'reference': payment.payment_reference,
                              'amount': float(payment.amount), 'procurement_id': procurement.id})
        log_action('DOCUMENT_ACCESS_GRANTED', entity_type='BidderDocumentAccess', entity_id=procurement.id,
                   new_value={'bidder_id': payment.bidder_id, 'granted_by': current_user.id, 'documents': ['ITT']})

        # Notifications
        for u in bidder_users:
            notify_user(
                u, 'payment_approved',
                f'Payment Approved — Tender Documents Unlocked ({procurement.tender_number})',
                f'Your payment (Ref: {payment.payment_reference}) for {procurement.title} has been verified and approved. You now have access to view and download the ITT document.',
                procurement_id=procurement.id
            )

        flash(f'Payment {payment.payment_reference} from {payment.bidder.company_name} approved! ITT access granted.', 'success')

    elif action == 'reject':
        if not reason:
            flash('A rejection reason is required.', 'danger')
            return redirect(request.referrer or url_for('procurements.detail', procurement_id=procurement.id))

        payment.status = 'rejected'
        payment.notes = reason
        payment.reviewed_by_id = current_user.id
        payment.reviewed_at = datetime.utcnow()

        # Revoke access if any existed
        accesses = BidderDocumentAccess.query.filter_by(
            procurement_id=procurement.id,
            bidder_id=payment.bidder_id,
            status='active'
        ).all()
        for a in accesses:
            a.status = 'revoked'
            a.revoked_by_id = current_user.id
            a.revoked_at = datetime.utcnow()
            a.revocation_reason = f'Payment rejected: {reason}'

        db.session.commit()

        log_action('PAYMENT_REJECTED', entity_type='BidderPayment', entity_id=payment.id,
                   reason=reason,
                   new_value={'bidder_id': payment.bidder_id, 'reference': payment.payment_reference})

        for u in bidder_users:
            notify_user(
                u, 'payment_rejected',
                f'Payment Proof Rejected ({procurement.tender_number})',
                f'Your payment submission (Ref: {payment.payment_reference}) for {procurement.title} was rejected. Reason: {reason}. ITT remains locked.',
                procurement_id=procurement.id
            )

        flash(f'Payment {payment.payment_reference} rejected. Notification sent to bidder.', 'warning')

    elif action == 'request_resubmission':
        if not reason:
            flash('Resubmission instructions/reason are required.', 'danger')
            return redirect(request.referrer or url_for('procurements.detail', procurement_id=procurement.id))

        payment.status = 'resubmission_required'
        payment.notes = reason
        payment.reviewed_by_id = current_user.id
        payment.reviewed_at = datetime.utcnow()

        # Ensure no active access
        accesses = BidderDocumentAccess.query.filter_by(
            procurement_id=procurement.id,
            bidder_id=payment.bidder_id,
            status='active'
        ).all()
        for a in accesses:
            a.status = 'revoked'
            a.revoked_by_id = current_user.id
            a.revoked_at = datetime.utcnow()
            a.revocation_reason = f'Resubmission requested: {reason}'

        db.session.commit()

        log_action('PAYMENT_RESUBMISSION_REQUESTED', entity_type='BidderPayment', entity_id=payment.id,
                   reason=reason,
                   new_value={'bidder_id': payment.bidder_id, 'reference': payment.payment_reference})

        for u in bidder_users:
            notify_user(
                u, 'payment_resubmission_required',
                f'Payment Correction Required ({procurement.tender_number})',
                f'Procurement requires a corrected payment proof (Ref: {payment.payment_reference}) for {procurement.title}. Instructions: {reason}. Please re-upload in your workspace.',
                procurement_id=procurement.id
            )

        flash(f'Resubmission requested for payment {payment.payment_reference}. Notification sent to bidder.', 'info')

    elif action == 'revoke':
        accesses = BidderDocumentAccess.query.filter_by(
            procurement_id=procurement.id,
            bidder_id=payment.bidder_id,
            status='active'
        ).all()
        for a in accesses:
            a.status = 'revoked'
            a.revoked_by_id = current_user.id
            a.revoked_at = datetime.utcnow()
            a.revocation_reason = reason or 'Access revoked by Procurement.'

        db.session.commit()

        log_action('DOCUMENT_ACCESS_REVOKED', entity_type='BidderDocumentAccess', entity_id=procurement.id,
                   reason=reason,
                   new_value={'bidder_id': payment.bidder_id, 'revoked_by': current_user.id})

        for u in bidder_users:
            notify_user(
                u, 'access_revoked',
                f'Document Access Revoked ({procurement.tender_number})',
                f'Your ITT access for {procurement.title} has been revoked by Procurement. Reason: {reason or "Administrative action"}.',
                procurement_id=procurement.id
            )

        flash(f'Document access for {payment.bidder.company_name} revoked.', 'warning')

    return redirect(request.referrer or url_for('procurements.detail', procurement_id=procurement.id))


@procurements_bp.route('/payment-verifications')
@login_required
def payment_verifications():
    if current_user.has_role('bidder'):
        abort(403)

    status_filter = request.args.get('status', 'all').strip().lower()
    query = BidderPayment.query.join(Procurement).order_by(BidderPayment.submitted_at.desc())

    if status_filter != 'all' and status_filter in ('pending', 'approved', 'rejected', 'resubmission_required'):
        query = query.filter(BidderPayment.status == status_filter)

    payments = query.all()
    pending_count = BidderPayment.query.filter_by(status='pending').count()
    approved_count = BidderPayment.query.filter_by(status='approved').count()
    rejected_count = BidderPayment.query.filter_by(status='rejected').count()
    resubmit_count = BidderPayment.query.filter_by(status='resubmission_required').count()

    return render_template(
        'payment_verifications.html',
        payments=payments,
        status_filter=status_filter,
        pending_count=pending_count,
        approved_count=approved_count,
        rejected_count=rejected_count,
        resubmit_count=resubmit_count,
    )


@procurements_bp.route('/<int:procurement_id>/documents/<int:communication_id>/download')
@login_required
def download_document(procurement_id, communication_id):
    procurement = Procurement.query.get_or_404(procurement_id)
    document = Communication.query.filter_by(id=communication_id, procurement_id=procurement.id).first_or_404()

    if current_user.has_role('bidder') or current_user.bidder_id:
        if not _bidder_can_access_procurement(procurement):
            abort(404)
        if document.type == 'clarification':
            if not ClarificationAccessService.can_bidder_view_clarification(document.id, current_user.bidder_id):
                abort(403)
        elif document.type not in ('advertisement', 'addendum'):
            abort(403)
        if not current_user.bidder or not current_user.bidder.has_approved_payment_for_procurement(procurement.id):
            log_action('UNAUTHORIZED_COMMUNICATION_DOWNLOAD_BLOCKED', entity_type='Communication', entity_id=document.id,
                       reason=f"Bidder {current_user.bidder_id} attempted access before payment approval")
            abort(403)

    if not document.file_path or not document.original_filename:
        abort(404)

    directory = document.file_path.rsplit('/', 1)[0] if '/' in document.file_path else '.'
    filename = document.file_path.rsplit('/', 1)[-1]
    return send_from_directory(directory, filename, as_attachment=True, download_name=document.original_filename)


@procurements_bp.route('/<int:procurement_id>/submission/<int:submission_id>/download')
@login_required
def download_submission(procurement_id, submission_id):
    procurement = Procurement.query.get_or_404(procurement_id)
    submission = Submission.query.filter_by(id=submission_id, procurement_id=procurement.id).first_or_404()

    if current_user.has_role('bidder'):
        if submission.bidder_id != current_user.bidder_id:
            log_action('UNAUTHORIZED_SUBMISSION_DOWNLOAD_BLOCKED', entity_type='Submission',
                       entity_id=submission.id,
                       reason=f'Bidder {current_user.bidder_id} tried to download another bidder\'s submission')
            abort(403)
    elif current_user.role and current_user.role.can_evaluate and not current_user.role.can_view_all_records:
        # Evaluator / committee roles: document-type scope is enforced server-side.
        if not EvaluatorAssignmentService.can_view_envelope(
            procurement.id, current_user.id, submission.envelope_type
        ):
            log_action(
                'EVALUATOR_DOCUMENT_ACCESS_BLOCKED',
                entity_type='Submission',
                entity_id=submission.id,
                reason=(
                    f"Evaluator {current_user.id} attempted to download "
                    f"{submission.envelope_type} document without the matching assigned scope"
                ),
            )
            abort(403)

    if not submission.file_path or not submission.original_filename:
        abort(404)

    if not os.path.isfile(submission.file_path):
        abort(404)

    with open(submission.file_path, 'rb') as encrypted_file:
        plaintext = decrypt_bytes(encrypted_file.read())

    bidder_name = secure_filename(submission.bidder.company_name) if submission.bidder else ''
    if not bidder_name:
        bidder_name = f'bidder_{submission.bidder_id}'
    original_stem, original_extension = os.path.splitext(submission.original_filename)
    download_name = secure_filename(
        f'{bidder_name}_{submission.envelope_type}_{original_stem}'
    ) + original_extension

    return send_file(
        io.BytesIO(plaintext),
        as_attachment=True,
        download_name=download_name,
        mimetype='application/octet-stream',
    )


@procurements_bp.route('/<int:procurement_id>/evaluator-feedback/<int:feedback_id>/download')
@login_required
def download_evaluator_feedback(procurement_id, feedback_id):
    procurement = Procurement.query.get_or_404(procurement_id)
    feedback = EvaluatorFeedback.query.filter_by(
        id=feedback_id, procurement_id=procurement.id
    ).first_or_404()

    is_submitting_evaluator = (
        feedback.evaluator_id == current_user.id
        and EvaluatorAssignment.active_for(procurement.id, current_user.id)
    )
    if current_user.has_role('bidder') or (
        not current_user.can_access_procurement(procurement) and not is_submitting_evaluator
    ):
        abort(403)
    if not feedback.file_path or not os.path.isfile(feedback.file_path):
        abort(404)

    with open(feedback.file_path, 'rb') as encrypted_file:
        plaintext = decrypt_bytes(encrypted_file.read())
    log_action(
        'EVALUATOR_FEEDBACK_DOWNLOADED',
        entity_type='EvaluatorFeedback',
        entity_id=feedback.id,
        reason=f'Procurement user {current_user.id} accessed evaluator feedback',
    )
    return send_file(
        io.BytesIO(plaintext),
        as_attachment=True,
        download_name=feedback.original_filename,
        mimetype=mimetypes.guess_type(feedback.original_filename)[0] or 'application/octet-stream',
    )


@procurements_bp.route('/<int:procurement_id>/evaluator-feedback/<int:feedback_id>/view')
@login_required
def view_evaluator_feedback(procurement_id, feedback_id):
    procurement = Procurement.query.get_or_404(procurement_id)
    feedback = EvaluatorFeedback.query.filter_by(
        id=feedback_id, procurement_id=procurement.id
    ).first_or_404()
    is_submitting_evaluator = (
        feedback.evaluator_id == current_user.id
        and EvaluatorAssignment.active_for(procurement.id, current_user.id)
    )
    if current_user.has_role('bidder') or (
        not current_user.can_access_procurement(procurement) and not is_submitting_evaluator
    ):
        abort(403)
    if not feedback.file_path or not os.path.isfile(feedback.file_path):
        abort(404)
    with open(feedback.file_path, 'rb') as encrypted_file:
        plaintext = decrypt_bytes(encrypted_file.read())
    log_action(
        'EVALUATOR_FEEDBACK_VIEWED',
        entity_type='EvaluatorFeedback',
        entity_id=feedback.id,
        reason=f'Procurement user {current_user.id} viewed evaluator feedback',
    )
    return send_file(
        io.BytesIO(plaintext),
        as_attachment=False,
        download_name=feedback.original_filename,
        mimetype=mimetypes.guess_type(feedback.original_filename)[0] or 'application/octet-stream',
    )


@procurements_bp.route('/<int:procurement_id>/transition', methods=['POST'])
@login_required
def transition(procurement_id):
    procurement = Procurement.query.get_or_404(procurement_id)
    submission_count = procurement.submissions.filter_by(status='submitted').count()

    if not (current_user.role and (current_user.role.can_publish or current_user.role.can_admin_system)):
        abort(403)

    to_status = request.form.get('to_status')
    allowed = TRANSITIONS.get(procurement.status, [])
    if to_status not in allowed:
        flash(f'Cannot move from {procurement.status_label()} to that status.', 'danger')
        return redirect(url_for('procurements.detail', procurement_id=procurement.id))

    transition_reason = request.form.get('reason', '').strip()
    if to_status == 'cancelled':
        reason = request.form.get('cancelled_reason', '').strip()
        if not reason:
            flash('A cancellation reason is required (SOAR 7.14).', 'danger')
            return redirect(url_for('procurements.detail', procurement_id=procurement.id))
        procurement.cancelled = True
        procurement.cancelled_reason = reason
        procurement.cancelled_at = datetime.utcnow()
        transition_reason = reason

    if to_status == 'submission_open':
        deadline_raw = request.form.get('submission_deadline')
        if deadline_raw:
            procurement.submission_deadline = datetime.fromisoformat(deadline_raw)
        elif not procurement.submission_deadline:
            flash('Set a submission deadline before opening submissions.', 'danger')
            return redirect(url_for('procurements.detail', procurement_id=procurement.id))

    if to_status == 'closed' and (
        not procurement.submission_deadline or datetime.utcnow() < procurement.submission_deadline
    ):
        flash('Submissions can be closed only after the tender deadline has passed.', 'warning')
        return redirect(url_for('procurements.detail', procurement_id=procurement.id))

    if to_status == 'under_evaluation' and submission_count == 0:
        flash('At least one bidder submission is required before evaluation can begin.', 'danger')
        return redirect(url_for('procurements.detail', procurement_id=procurement.id))

    if to_status == 'submission_open' and procurement.status in ('under_evaluation', 'closed'):
        deadline_raw = request.form.get('submission_deadline', '').strip()
        try:
            reopened_deadline = datetime.fromisoformat(deadline_raw)
        except ValueError:
            reopened_deadline = None
        if not reopened_deadline or reopened_deadline <= datetime.utcnow():
            flash('Choose a future deadline before reopening bidding.', 'danger')
            return redirect(url_for('procurements.detail', procurement_id=procurement.id))
        procurement.submission_deadline = reopened_deadline

    previous_status = procurement.status
    procurement.status = to_status
    db.session.commit()

    history_entry = ProcurementHistory.log_action(
        procurement_id=procurement.id,
        action=to_status,
        performed_by_id=current_user.id,
        previous_status=previous_status,
        new_status=to_status,
        reason=transition_reason or None,
    )
    db.session.add(history_entry)
    db.session.commit()

    log_action('PROCUREMENT_STATUS_CHANGED', entity_type='Procurement', entity_id=procurement.id,
               previous_value={'status': previous_status}, new_value={'status': to_status},
               reason=transition_reason or None)

    if to_status in NOTIFIABLE:
        if to_status == 'submission_open' and previous_status in ('closed', 'under_evaluation'):
            title = f'Tender reopened: {procurement.tender_number}'
            body = (
                f'{procurement.title} has been reopened for bidding. '
                f'You may submit or resubmit your bid before the new deadline: '
                f'{procurement.submission_deadline}.'
            )
        else:
            title, body = NOTIFIABLE[to_status](procurement)
        try:
            notify_bidders_on_procurement(procurement, 'status_change', title, body)
        except Exception as exc:
            print(f"Notification dispatch failed (non-fatal): {exc}")

    flash(f'Procurement moved to {to_status.replace("_", " ").title()}.', 'success')
    return redirect(url_for('procurements.detail', procurement_id=procurement.id))