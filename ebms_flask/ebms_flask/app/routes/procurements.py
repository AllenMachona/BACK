import os
import random
import secrets
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, send_from_directory, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models.procurement import Procurement
from app.models.communication import Communication
from app.models.complaint import Complaint
from app.models.submission import Submission
from app.models.user import User
from app.models.role import Role
from app.models.bidder import Bidder
from app.models.payment import BidderPayment, BidderDocumentAccess
from app.utils.decorators import permission_required, role_required
from app.utils.audit import log_action
from app.utils.notify import notify_user, notify_bidders_on_procurement

procurements_bp = Blueprint('procurements', __name__, url_prefix='/procurements')


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
    ppra_codes = Procurement.ppra_code_options()
    ppra_sub_codes = Procurement.ppra_sub_code_options()

    if request.method == 'POST':
        try:
            estimated_value = float(request.form['estimated_value'])
        except (KeyError, ValueError):
            flash('A valid estimated value is required.', 'danger')
            return render_template('procurement_create.html', ppra_codes=ppra_codes, ppra_sub_codes=ppra_sub_codes)

        tender_fee = 0.0
        if request.form.get('tender_fee'):
            try:
                tender_fee = float(request.form.get('tender_fee'))
            except ValueError:
                tender_fee = 0.0

        procurement_entity = request.form.get('procurement_entity') or request.form.get('user_department')
        if not procurement_entity:
            flash('A procurement entity is required.', 'danger')
            return render_template('procurement_create.html', ppra_codes=ppra_codes, ppra_sub_codes=ppra_sub_codes)

        advertisement = request.files.get('advertisement_document')
        if not advertisement or not advertisement.filename:
            flash('An advertisement document is required before creating the procurement.', 'danger')
            return render_template('procurement_create.html', ppra_codes=ppra_codes, ppra_sub_codes=ppra_sub_codes)

        ppra_base = request.form.get('ppra_code', '').strip()
        ppra_sub_code = request.form.get('ppra_sub_code', '').strip()
        ppra_code = ppra_base
        if ppra_sub_code and ppra_sub_code not in ('00', 'none'):
            ppra_code = f'{ppra_base}-{ppra_sub_code}'

        direct_threshold = float(request.form.get('direct_procurement_threshold', 500000) or 500000)
        governance = Procurement(
            tender_number='TBD',
            title=request.form['title'],
            description=request.form.get('description'),
            category=request.form['category'],
            procurement_entity=procurement_entity,
            ppra_code=ppra_code,
            ppra_sub_code=ppra_sub_code if ppra_sub_code and ppra_sub_code not in ('00', 'none') else None,
            method=request.form['method'],
            evaluation_method=request.form.get('evaluation_method'),
            envelope_type=request.form.get('envelope_type', 'single'),
            estimated_value=estimated_value,
            tender_fee=tender_fee,
            user_department=procurement_entity,
            status='draft',
        ).check_governance_rules(direct_threshold=direct_threshold, open_threshold=direct_threshold)

        if governance['errors']:
            flash('Direct procurement exceeds the approved threshold and is not permitted.', 'danger')
            return render_template('procurement_create.html', ppra_codes=ppra_codes, ppra_sub_codes=ppra_sub_codes)

        if governance['warnings']:
            flash('Governance check noted a review risk: lot splitting or high-value procedure review required.', 'warning')

        deadline_raw = request.form.get('submission_deadline')
        clarification_deadline_raw = request.form.get('clarification_deadline')
        deadline = datetime.fromisoformat(deadline_raw) if deadline_raw else None
        clarification_deadline = datetime.fromisoformat(clarification_deadline_raw) if clarification_deadline_raw else None

        tender_number = generate_tender_number()

        # Handle document uploads
        form_d_path, form_d_name = _save_procurement_document(request.files.get('form_d_document'), tender_number, 'form_d')
        form_e_path, form_e_name = _save_procurement_document(request.files.get('form_e_document'), tender_number, 'form_e')
        rfce_path, rfce_name = _save_procurement_document(request.files.get('rfce_document'), tender_number, 'rfce')
        itt_path, itt_name = _save_procurement_document(request.files.get('itt_document'), tender_number, 'itt')

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
            envelope_type=request.form.get('envelope_type', 'single'),
            estimated_value=estimated_value,
            tender_fee=tender_fee,
            user_department=procurement_entity,
            submission_deadline=deadline,
            clarification_deadline=clarification_deadline,
            form_d_file_path=form_d_path,
            form_d_filename=form_d_name,
            form_e_file_path=form_e_path,
            form_e_filename=form_e_name,
            rfce_file_path=rfce_path,
            rfce_filename=rfce_name,
            itt_file_path=itt_path,
            itt_filename=itt_name,
            created_by_id=current_user.id,
            status='draft',
        )
        db.session.add(procurement)
        db.session.commit()

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
                              'has_rfce': bool(rfce_path), 'has_itt': bool(itt_path)})
        flash(f'Procurement {procurement.tender_number} created as Draft with submitted documents.', 'success')
        return redirect(url_for('procurements.detail', procurement_id=procurement.id))

    return render_template('procurement_create.html', ppra_codes=ppra_codes, ppra_sub_codes=ppra_sub_codes)


@procurements_bp.route('/search')
@login_required
def search():
    query = (request.args.get('q') or '').strip()
    procurements = []
    users = []
    if query:
        pattern = f'%{query}%'
        procurements = Procurement.query.filter(
            or_(
                Procurement.title.ilike(pattern),
                Procurement.tender_number.ilike(pattern),
                Procurement.description.ilike(pattern),
                Procurement.procurement_entity.ilike(pattern),
                Procurement.user_department.ilike(pattern),
                Procurement.ppra_code.ilike(pattern),
            )
        ).order_by(Procurement.created_at.desc()).all()
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

    if current_user.has_role('bidder'):
        if procurement.status in ('draft', 'internal_review', 'approved_for_publication'):
            abort(404)
    elif not current_user.can_access_procurement(procurement):
        abort(403)

    committee = procurement.committee_members.all()
    communications = procurement.communications.order_by(Communication.created_at.desc()).limit(10).all()
    complaints = procurement.complaints.order_by(Complaint.created_at.desc()).all()
    submissions = procurement.submissions.order_by(Submission.submitted_at.desc()).all()
    submission_count = procurement.submissions.filter_by(status='submitted').count()
    next_status = TRANSITIONS.get(procurement.status, [None])[0] if TRANSITIONS.get(procurement.status) else None

    # Payments for Procurement verification
    payments = BidderPayment.query.filter_by(procurement_id=procurement.id).order_by(BidderPayment.submitted_at.desc()).all()
    pending_payments_count = sum(1 for p in payments if p.status == 'pending')

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
    )


@procurements_bp.route('/<int:procurement_id>/upload-documents', methods=['POST'])
@login_required
def upload_documents(procurement_id):
    procurement = Procurement.query.get_or_404(procurement_id)

    if current_user.has_role('bidder') or not current_user.can_access_procurement(procurement):
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

    if request.files.get('rfce_document'):
        path, name = _save_procurement_document(request.files['rfce_document'], procurement.tender_number, 'rfce')
        if path:
            procurement.rfce_file_path = path
            procurement.rfce_filename = name
            uploaded.append('RFCE')

    if request.files.get('itt_document'):
        path, name = _save_procurement_document(request.files['itt_document'], procurement.tender_number, 'itt')
        if path:
            procurement.itt_file_path = path
            procurement.itt_filename = name
            uploaded.append('ITT')

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
    elif doc_type == 'rfce':
        filepath = procurement.rfce_file_path
        filename = procurement.rfce_filename
    elif doc_type == 'itt':
        filepath = procurement.itt_file_path
        filename = procurement.itt_filename
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

    elif doc_type in ('rfce', 'itt'):
        # Gated by payment approval for bidders
        if current_user.has_role('bidder'):
            if not current_user.bidder_id:
                abort(403)

            has_access = BidderDocumentAccess.can_bidder_access(procurement.id, current_user.bidder_id, doc_type)
            if not has_access:
                log_action('UNAUTHORIZED_DOCUMENT_ACCESS_BLOCKED', entity_type='ProcurementDocument', entity_id=procurement.id,
                           reason=f"Unapproved Bidder {current_user.bidder_id} attempted direct access to {doc_type.upper()}")
                abort(403)

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
    elif doc_type == 'rfce':
        filepath = procurement.rfce_file_path
        filename = procurement.rfce_filename
    elif doc_type == 'itt':
        filepath = procurement.itt_file_path
        filename = procurement.itt_filename
    else:
        abort(404)

    # STRICT ACCESS CONTROL FIRST
    if doc_type in ('form_d', 'form_e'):
        if current_user.has_role('bidder') or not current_user.can_access_procurement(procurement):
            log_action('UNAUTHORIZED_FORM_ACCESS_BLOCKED', entity_type='ProcurementDocument', entity_id=procurement.id,
                       reason=f"Bidder/User attempted direct inline view of {doc_type.upper()}")
            abort(403)

    elif doc_type in ('rfce', 'itt'):
        if current_user.has_role('bidder'):
            if not current_user.bidder_id or not BidderDocumentAccess.can_bidder_access(procurement.id, current_user.bidder_id, doc_type):
                log_action('UNAUTHORIZED_DOCUMENT_ACCESS_BLOCKED', entity_type='ProcurementDocument', entity_id=procurement.id,
                           reason=f"Unapproved Bidder {current_user.bidder_id} attempted direct inline view of {doc_type.upper()}")
                abort(403)

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

    bidder_users = User.query.filter_by(bidder_id=payment.bidder_id).all()

    if action == 'approve':
        payment.status = 'approved'
        payment.reviewed_by_id = current_user.id
        payment.reviewed_at = datetime.utcnow()
        payment.notes = reason or 'Payment verified and approved by Procurement.'

        # Grant access to RFCE and ITT
        for doc_type in ('rfce', 'itt', 'all_bidder_docs'):
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
                   new_value={'bidder_id': payment.bidder_id, 'granted_by': current_user.id, 'documents': ['RFCE', 'ITT']})

        # Notifications
        for u in bidder_users:
            notify_user(
                u, 'payment_approved',
                f'Payment Approved — Tender Documents Unlocked ({procurement.tender_number})',
                f'Your payment (Ref: {payment.payment_reference}) for {procurement.title} has been verified and approved. You now have full access to view and download the RFCE and ITT documents.',
                procurement_id=procurement.id
            )

        flash(f'Payment {payment.payment_reference} from {payment.bidder.company_name} approved! RFCE and ITT access granted.', 'success')

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
                f'Your payment submission (Ref: {payment.payment_reference}) for {procurement.title} was rejected. Reason: {reason}. RFCE and ITT remain locked.',
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
                f'Your access to RFCE and ITT for {procurement.title} has been revoked by Procurement. Reason: {reason or "Administrative action"}.',
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

    if current_user.has_role('bidder'):
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

    if current_user.has_role('bidder') and submission.bidder_id != current_user.bidder_id:
        abort(403)

    if not submission.file_path or not submission.original_filename:
        abort(404)

    directory = submission.file_path.rsplit('/', 1)[0] if '/' in submission.file_path else '.'
    filename = submission.file_path.rsplit('/', 1)[-1]
    return send_from_directory(directory, filename, as_attachment=True, download_name=submission.original_filename)


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

    if to_status == 'clarification_period':
        deadline_raw = request.form.get('clarification_deadline')
        if deadline_raw:
            procurement.clarification_deadline = datetime.fromisoformat(deadline_raw)
        elif not procurement.clarification_deadline:
            flash('Set a clarification deadline before moving to clarification period.', 'danger')
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