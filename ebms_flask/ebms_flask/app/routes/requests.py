"""Procurement request workflow routes (Form D / Form E).

Server-rendered, POST/redirect/GET style — exactly like the rest of the app
(no REST framework in use). Role enforcement is server-side on every route:

- ``requester`` role users submit Form D / Form E requests and may view only
  their own submissions (IDOR guard on every detail/download route).
- Procurement staff (roles with ``can_view_all_records``,
  ``can_approve_procurement`` or ``can_create_procurement``) operate the
  combined Incoming Requests queue, mark requests under review, convert a
  request into a real Procurement record, or reject it with a reason.
"""
import os
import random
import secrets
from datetime import datetime

from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, send_from_directory, url_for)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models.procurement import Procurement
from app.models.request import FormDRequest, FormERequest, FormDERequest, REQUEST_STATUSES
from app.models.role import Role
from app.models.user import User
from app.utils.audit import log_action
from app.utils.decorators import role_required
from app.utils.notify import notify_user

requests_bp = Blueprint('requests', __name__, url_prefix='/requests')

CATEGORY_OPTIONS = ['works', 'services', 'consultancy', 'supplies', 'combination']
METHOD_OPTIONS = ['open_domestic', 'open_international', 'restricted', 'rfq', 'direct', 'rfp']
HUMANIZED_STATUS = {s: s.replace('_', ' ').title() for s in REQUEST_STATUSES}
REQUEST_DOCUMENT_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx'}
REQUEST_DOCUMENT_MAX_BYTES = 25 * 1024 * 1024


def _is_procurement_staff(user=None):
    """Internal staff who may operate the request queue and take review actions."""
    user = user or current_user
    if not getattr(user, 'is_authenticated', False) or not getattr(user, 'role', None):
        return False
    return bool(
        user.role.can_view_all_records
        or user.role.can_approve_procurement
        or user.role.can_create_procurement
    )


def _require_procurement_staff():
    if not _is_procurement_staff(current_user):
        abort(403)


def _can_view_request(user, request_obj):
    """Owner requester or any procurement staff member. Never other requesters."""
    if _is_procurement_staff(user):
        return True
    return bool(getattr(user, 'is_authenticated', False) and request_obj.requester_id == user.id)


def _require_request_access(request_obj):
    if not _can_view_request(current_user, request_obj):
        abort(403)


def _parse_date_field(raw):
    """Accept 'YYYY-MM-DD' (or empty); return a date or None."""
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        return None


def _parse_value(raw):
    try:
        return float(raw or '')
    except (TypeError, ValueError):
        return None


def _save_signed_form(file_storage, form_type):
    """Persist the signed/scanned copy of a submitted Form D or Form E."""
    if not file_storage or not file_storage.filename:
        return None, None
    token = secrets.token_hex(4)
    safe_name = secure_filename(file_storage.filename) or 'signed_form.pdf'
    filename = secure_filename(f"request_{form_type}_{token}_{safe_name}")
    doc_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'procurement_documents')
    os.makedirs(doc_dir, exist_ok=True)
    filepath = os.path.join(doc_dir, filename)
    file_storage.save(filepath)
    return filepath, file_storage.filename


def _validate_request_document(file_storage, label):
    if not file_storage or not file_storage.filename:
        return f'Please attach the signed/certified copy of {label}.'
    original_name = secure_filename(file_storage.filename)
    extension = original_name.rsplit('.', 1)[-1].lower() if '.' in original_name else ''
    if extension not in REQUEST_DOCUMENT_EXTENSIONS:
        allowed = ', '.join(sorted(REQUEST_DOCUMENT_EXTENSIONS))
        return f'{label} must be a PDF or supported Office document ({allowed}).'
    stream = file_storage.stream
    current_position = stream.tell()
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(current_position)
    if size > REQUEST_DOCUMENT_MAX_BYTES:
        return f'{label} must be 25 MB or smaller.'
    return None


def _generate_tender_number():
    """Same format as procurements.py's generator (TB-YYYY-NNN)."""
    year = datetime.utcnow().year
    while True:
        candidate = f"TB-{year}-{random.randint(100, 999)}"
        if not Procurement.query.filter_by(tender_number=candidate).first():
            return candidate


def _notify_procurement_staff(title, body):
    """Alert everyone who operates the queue that a new request arrived."""
    staff = (
        User.query.join(Role, User.role_id == Role.id)
        .filter(
            (Role.can_view_all_records == True)
            | (Role.can_approve_procurement == True)
            | (Role.can_create_procurement == True)
        )
        .filter(User.id != current_user.id)
        .all()
    )
    for user in staff:
        notify_user(user, 'request_submitted', title, body, email=False)


def _notify_requester(request_obj, notif_type, title, body):
    try:
        notify_user(request_obj.requester, notif_type, title, body)
    except Exception as exc:  # notification failures must never fail the action
        print(f"Requester notification failed (non-fatal): {exc}")


def _detail_link(request_obj):
    if request_obj.form_type == 'form_d':
        return url_for('requests.detail_form_d', request_id=request_obj.id)
    if request_obj.form_type == 'de':
        return url_for('requests.detail_de', request_id=request_obj.id)
    return url_for('requests.detail_form_e', request_id=request_obj.id)# ---------------------------------------------------------------------------
# Requester hub, submission pages, my requests and detail views
# ---------------------------------------------------------------------------
@requests_bp.route('/hub')
@login_required
@role_required('requester')
def hub():
    # The hub no longer offers two separate Form D / Form E entry points —
    # requesters upload both documents in one combined window.
    return redirect(url_for('requests.new_form'))


@requests_bp.route('/new', methods=['GET'])
@login_required
@role_required('requester')
def new_form():
    return render_template('requests/new_form.html', form=None)


@requests_bp.route('/new', methods=['POST'])
@login_required
@role_required('requester')
def submit_form_de():
    """Combined Form D / Form E submission.

    The requester only attaches the two signed documents and a justification.
    Every procurement detail (title, category, method, value, budget, tender
    documents) is created later by the Procurement Unit on the Procurement
    record.
    """
    justification = (request.form.get('justification') or '').strip()
    department = (current_user.department or '').strip()

    errors = []
    form_d_file = request.files.get('form_d_document')
    form_e_file = request.files.get('form_e_document')
    form_d_error = _validate_request_document(form_d_file, 'Form D')
    form_e_error = _validate_request_document(form_e_file, 'Form E')
    if form_d_error:
        errors.append(form_d_error)
    if form_e_error:
        errors.append(form_e_error)

    if errors:
        for error in errors:
            flash(error, 'danger')
        return render_template('requests/new_form.html', form=request.form)

    d_path, d_name = _save_signed_form(form_d_file, 'form_d')
    e_path, e_name = _save_signed_form(form_e_file, 'form_e')

    request_obj = FormDERequest(
        requester_id=current_user.id,
        submitted_by_id=current_user.id,
        status='submitted',
        department=department,
        justification=justification,
        form_d_file_path=d_path,
        form_d_filename=d_name,
        form_e_file_path=e_path,
        form_e_filename=e_name,
    )
    db.session.add(request_obj)
    db.session.commit()

    log_action('REQUEST_DE_SUBMITTED', entity_type='FormDERequest', entity_id=request_obj.id,
               new_value={'requester': current_user.full_name(), 'department': department,
                          'status': 'submitted', 'has_form_d': bool(d_path), 'has_form_e': bool(e_path)})
    log_action('REQUEST_DE_FORM_D_UPLOADED', entity_type='FormDERequest', entity_id=request_obj.id,
               new_value={'filename': d_name})
    log_action('REQUEST_DE_FORM_E_UPLOADED', entity_type='FormDERequest', entity_id=request_obj.id,
               new_value={'filename': e_name})
    _notify_procurement_staff(
        f'New procurement request from {current_user.full_name()}',
        f'{current_user.full_name()} ({department or "Department not set"}) submitted a '
        f'combined Form D & Form E request with justification. Review it in the Incoming Requests queue.',
    )
    flash('Request submitted to Procurement with Form D & Form E attached.', 'success')
    return redirect(url_for('requests.my_requests'))


@requests_bp.route('/form-d/new', methods=['GET'])
@login_required
@role_required('requester')
def new_form_d():
    return redirect(url_for('requests.new_form'))


@requests_bp.route('/form-e/new', methods=['GET'])
@login_required
@role_required('requester')
def new_form_e():
    return redirect(url_for('requests.new_form'))


@requests_bp.route('/my')
@login_required
@role_required('requester')
def my_requests():
    d_items = FormDRequest.query.filter_by(requester_id=current_user.id).order_by(
        FormDRequest.created_at.desc()).all()
    e_items = FormERequest.query.filter_by(requester_id=current_user.id).order_by(
        FormERequest.created_at.desc()).all()
    de_items = FormDERequest.query.filter_by(requester_id=current_user.id).order_by(
        FormDERequest.created_at.desc()).all()
    items = [dict(form_type='form_d', request=x) for x in d_items]
    items += [dict(form_type='form_e', request=x) for x in e_items]
    items += [dict(form_type='de', request=x) for x in de_items]
    items.sort(key=lambda item: item['request'].created_at or datetime.min, reverse=True)
    return render_template('requests/my_requests.html',
                           items=items, status_labels=HUMANIZED_STATUS)


@requests_bp.route('/form-d/<int:request_id>')
@login_required
def detail_form_d(request_id):
    request_obj = FormDRequest.query.get_or_404(request_id)
    _require_request_access(request_obj)
    return render_template('requests/detail_form_d.html',
                           req=request_obj,
                           can_manage=_is_procurement_staff(current_user),
                           status_labels=HUMANIZED_STATUS)


@requests_bp.route('/form-e/<int:request_id>')
@login_required
def detail_form_e(request_id):
    request_obj = FormERequest.query.get_or_404(request_id)
    _require_request_access(request_obj)
    return render_template('requests/detail_form_e.html',
                           req=request_obj,
                           can_manage=_is_procurement_staff(current_user),
                           status_labels=HUMANIZED_STATUS)# ---------------------------------------------------------------------------
# Submission handlers
# ---------------------------------------------------------------------------
@requests_bp.route('/form-d', methods=['POST'])
@login_required
@role_required('requester')
def submit_form_d():
    title = (request.form.get('requisition_title') or '').strip()
    category = (request.form.get('category') or '').strip()
    method = (request.form.get('procurement_method') or '').strip()
    entity = (request.form.get('procurement_entity') or '').strip()
    justification = (request.form.get('justification') or '').strip()
    delivery_period = (request.form.get('delivery_period') or '').strip()
    authorized_by = (request.form.get('authorized_by') or '').strip()
    estimated_value = _parse_value(request.form.get('estimated_value'))
    authorization_date = _parse_date_field(request.form.get('authorization_date'))

    errors = []
    if not title:
        errors.append('A requisition title is required.')
    if category not in CATEGORY_OPTIONS:
        errors.append('Select a valid procurement category.')
    if method not in METHOD_OPTIONS:
        errors.append('Select a valid procurement method.')
    if estimated_value is None or estimated_value < 0:
        errors.append('A valid estimated value is required.')
    if not entity:
        errors.append('The requesting department / procurement entity is required.')
    if not request.files.get('signed_form_document') or not request.files['signed_form_document'].filename:
        errors.append('Please attach the signed/certified copy of Form D.')

    if errors:
        for error in errors:
            flash(error, 'danger')
        return render_template('requests/form_d_new.html',
                               categories=CATEGORY_OPTIONS, methods=METHOD_OPTIONS,
                               form=request.form)

    signed_path, signed_name = _save_signed_form(request.files['signed_form_document'], 'form_d')
    request_obj = FormDRequest(
        requester_id=current_user.id,
        submitted_by_id=current_user.id,
        status='submitted',
        requisition_title=title,
        category=category,
        procurement_method=method,
        estimated_value=estimated_value,
        procurement_entity=entity,
        justification=justification,
        delivery_period=delivery_period,
        authorized_by=authorized_by,
        authorization_date=authorization_date,
        submitted_form_path=signed_path,
        submitted_form_filename=signed_name,
    )
    db.session.add(request_obj)
    db.session.commit()

    log_action('REQUEST_D_SUBMITTED', entity_type='FormDRequest', entity_id=request_obj.id,
               new_value={'title': title, 'estimated_value': estimated_value, 'status': 'submitted'})
    _notify_procurement_staff(
        f'New Form D request: {title}',
        f'{current_user.full_name()} submitted a Procurement Requisition (Form D) for '
        f'"{title}" worth BWP {estimated_value:,.2f}. Review it in the Incoming Requests queue.',
    )
    flash(f'Form D request "{title}" submitted to Procurement for review.', 'success')
    return redirect(url_for('requests.my_requests'))


@requests_bp.route('/form-e', methods=['POST'])
@login_required
@role_required('requester')
def submit_form_e():
    title = (request.form.get('specification_title') or '').strip()
    category = (request.form.get('category') or '').strip()
    specification = (request.form.get('technical_specification') or '').strip()
    budget_line = (request.form.get('budget_line') or '').strip()
    entity = (request.form.get('procurement_entity') or '').strip()
    clearance_authority = (request.form.get('clearance_authority') or '').strip()
    budget_allocated = _parse_value(request.form.get('budget_allocated'))
    budget_status = (request.form.get('budget_status') or 'available').strip()
    clearance_date = _parse_date_field(request.form.get('clearance_date'))

    errors = []
    if not title:
        errors.append('A specification title is required.')
    if category not in CATEGORY_OPTIONS:
        errors.append('Select a valid procurement category.')
    if not specification:
        errors.append('The technical specification is required.')
    if budget_allocated is None or budget_allocated < 0:
        errors.append('A valid budget allocation is required.')
    if not entity:
        errors.append('The requesting department / procurement entity is required.')
    if not request.files.get('signed_form_e_document') or not request.files['signed_form_e_document'].filename:
        errors.append('Please attach the signed/certified copy of Form E.')

    if errors:
        for error in errors:
            flash(error, 'danger')
        return render_template('requests/form_e_new.html',
                               categories=CATEGORY_OPTIONS, form=request.form)

    signed_path, signed_name = _save_signed_form(request.files['signed_form_e_document'], 'form_e')
    request_obj = FormERequest(
        requester_id=current_user.id,
        submitted_by_id=current_user.id,
        status='submitted',
        specification_title=title,
        category=category,
        technical_specification=specification,
        budget_line=budget_line,
        budget_allocated=budget_allocated,
        budget_status=budget_status,
        procurement_entity=entity,
        clearance_authority=clearance_authority,
        clearance_date=clearance_date,
        submitted_form_path=signed_path,
        submitted_form_filename=signed_name,
    )
    db.session.add(request_obj)
    db.session.commit()

    log_action('REQUEST_E_SUBMITTED', entity_type='FormERequest', entity_id=request_obj.id,
               new_value={'title': title, 'budget_allocated': budget_allocated, 'status': 'submitted'})
    _notify_procurement_staff(
        f'New Form E request: {title}',
        f'{current_user.full_name()} submitted a Specification & Budget Clearance (Form E) for '
        f'"{title}" with budget allocation BWP {budget_allocated:.2f}. Please review it.',
    )
    flash(f'Form E request "{title}" submitted to Procurement for review.', 'success')
    return redirect(url_for('requests.my_requests'))


@requests_bp.route('/')
@login_required
def queue():
    """Combined Incoming Requests queue for procurement staff, filterable by
    status, form type, requester and free-text search."""
    _require_procurement_staff()

    status_filter = (request.args.get('status') or 'all').strip().lower()
    if status_filter not in REQUEST_STATUSES:
        status_filter = 'all'
    form_type_filter = (request.args.get('form_type') or 'all').strip().lower()
    if form_type_filter not in ('form_d', 'form_e', 'de'):
        form_type_filter = 'all'
    requester_id = request.args.get('requester_id', type=int)
    query_text = (request.args.get('q') or '').strip()

    def build_d():
        q = FormDRequest.query
        if status_filter != 'all':
            q = q.filter(FormDRequest.status == status_filter)
        if requester_id:
            q = q.filter(FormDRequest.requester_id == requester_id)
        if query_text:
            q = q.filter(FormDRequest.requisition_title.ilike(f'%{query_text}%'))
        return q.order_by(FormDRequest.created_at.desc()).all()

    def build_e():
        q = FormERequest.query
        if status_filter != 'all':
            q = q.filter(FormERequest.status == status_filter)
        if requester_id:
            q = q.filter(FormERequest.requester_id == requester_id)
        if query_text:
            q = q.filter(FormERequest.specification_title.ilike(f'%{query_text}%'))
        return q.order_by(FormERequest.created_at.desc()).all()

    def build_de():
        q = FormDERequest.query
        if status_filter != 'all':
            q = q.filter(FormDERequest.status == status_filter)
        if requester_id:
            q = q.filter(FormDERequest.requester_id == requester_id)
        if query_text:
            q = q.filter(FormDERequest.justification.ilike(f'%{query_text}%'))
        return q.order_by(FormDERequest.created_at.desc()).all()

    items = []
    if form_type_filter in ('all', 'form_d'):
        items += [dict(form_type='form_d', request=x) for x in build_d()]
    if form_type_filter in ('all', 'form_e'):
        items += [dict(form_type='form_e', request=x) for x in build_e()]
    if form_type_filter in ('all', 'de'):
        items += [dict(form_type='de', request=x) for x in build_de()]
    items.sort(key=lambda item: item['request'].created_at or datetime.min, reverse=True)

    # Counts used for the metric badges (always summarise the whole queue).
    d_counts = dict(db.session.query(FormDRequest.status, db.func.count()).group_by(FormDRequest.status).all())
    e_counts = dict(db.session.query(FormERequest.status, db.func.count()).group_by(FormERequest.status).all())
    de_counts = dict(db.session.query(FormDERequest.status, db.func.count()).group_by(FormDERequest.status).all())
    counts = {status: int(d_counts.get(status, 0)) + int(e_counts.get(status, 0)) + int(de_counts.get(status, 0))
              for status in REQUEST_STATUSES}
    counts['all'] = sum(counts.values())

    requesters = (
        User.query.join(Role, User.role_id == Role.id)
        .filter(Role.code == 'requester')
        .order_by(User.first_name, User.last_name)
        .all()
    )
    return render_template(
        'requests/queue.html',
        items=items,
        counts=counts,
        status_filter=status_filter,
        form_type_filter=form_type_filter,
        requester_id=requester_id,
        query_text=query_text,
        requesters=requesters,
        status_labels=HUMANIZED_STATUS,
    )# ---------------------------------------------------------------------------
# Procurement review actions
# ---------------------------------------------------------------------------
def _mark_under_review(request_obj, detail_endpoint):
    _require_procurement_staff()
    if request_obj.status in ('converted', 'rejected'):
        flash(f'This request is already {request_obj.status}.', 'warning')
        return redirect(_detail_link(request_obj))
    request_obj.status = 'under_review'
    request_obj.under_review_by_id = current_user.id
    request_obj.under_review_at = datetime.utcnow()
    db.session.commit()
    log_action(f'REQUEST_{request_obj.form_type.upper()}_UNDER_REVIEW',
               entity_type=type(request_obj).__name__, entity_id=request_obj.id,
               new_value={'status': 'under_review'})
    flash('Request marked as under review.', 'info')
    return redirect(detail_endpoint)


@requests_bp.route('/form-d/<int:request_id>/review', methods=['POST'])
@login_required
def review_form_d(request_id):
    request_obj = FormDRequest.query.get_or_404(request_id)
    return _mark_under_review(request_obj, url_for('requests.detail_form_d', request_id=request_obj.id))


@requests_bp.route('/form-e/<int:request_id>/review', methods=['POST'])
@login_required
def review_form_e(request_id):
    request_obj = FormERequest.query.get_or_404(request_id)
    return _mark_under_review(request_obj, url_for('requests.detail_form_e', request_id=request_obj.id))


@requests_bp.route('/form-d/<int:request_id>/convert', methods=['POST'])
@login_required
def convert_form_d(request_id):
    """Create a draft Procurement record from a Form D request, then link the
    request to it and flip its status to 'converted'."""
    request_obj = FormDRequest.query.get_or_404(request_id)
    _require_procurement_staff()
    if request_obj.status in ('converted', 'rejected'):
        flash(f'This request is already {request_obj.status}.', 'warning')
        return redirect(url_for('requests.detail_form_d', request_id=request_obj.id))

    tender_number = _generate_tender_number()
    procurement = Procurement(
        tender_number=tender_number,
        title=request_obj.requisition_title,
        description=request_obj.justification,
        category=request_obj.category,
        method=request_obj.procurement_method,
        estimated_value=request_obj.estimated_value,
        procurement_entity=request_obj.procurement_entity,
        user_department=request_obj.procurement_entity,
        form_d_file_path=request_obj.submitted_form_path,
        form_d_filename=request_obj.submitted_form_filename,
        created_by_id=current_user.id,
        status='draft',
    )
    db.session.add(procurement)
    db.session.commit()

    request_obj.procurement_id = procurement.id
    request_obj.status = 'converted'
    request_obj.converted_by_id = current_user.id
    request_obj.converted_at = datetime.utcnow()
    db.session.commit()

    log_action('REQUEST_D_CONVERTED', entity_type='FormDRequest', entity_id=request_obj.id,
               new_value={'tender_number': tender_number, 'procurement_id': procurement.id,
                          'status': 'converted'})
    _notify_requester(
        request_obj, 'request_converted',
        f'Your Form D request was converted ({tender_number})',
        f'Your Procurement Requisition "{request_obj.requisition_title}" has been converted into '
        f'procurement record {tender_number}. Track it under Procurements.',
    )
    flash(f'Procurement {tender_number} created from the Form D request (status: Draft).', 'success')
    return redirect(url_for('procurements.detail', procurement_id=procurement.id))


@requests_bp.route('/form-e/<int:request_id>/convert', methods=['POST'])
@login_required
def convert_form_e(request_id):
    request_obj = FormERequest.query.get_or_404(request_id)
    _require_procurement_staff()
    if request_obj.status in ('converted', 'rejected'):
        flash(f'This request is already {request_obj.status}.', 'warning')
        return redirect(url_for('requests.detail_form_e', request_id=request_obj.id))

    tender_number = _generate_tender_number()
    procurement = Procurement(
        tender_number=tender_number,
        title=request_obj.specification_title,
        description=request_obj.technical_specification,
        category=request_obj.category,
        method='open_domestic',
        estimated_value=request_obj.budget_allocated,
        procurement_entity=request_obj.procurement_entity,
        user_department=request_obj.procurement_entity,
        form_e_file_path=request_obj.submitted_form_path,
        form_e_filename=request_obj.submitted_form_filename,
        created_by_id=current_user.id,
        status='draft',
    )
    db.session.add(procurement)
    db.session.commit()

    request_obj.procurement_id = procurement.id
    request_obj.status = 'converted'
    request_obj.converted_by_id = current_user.id
    request_obj.converted_at = datetime.utcnow()
    db.session.commit()

    log_action('REQUEST_E_CONVERTED', entity_type='FormERequest', entity_id=request_obj.id,
               new_value={'tender_number': tender_number, 'procurement_id': procurement.id,
                          'status': 'converted'})
    _notify_requester(
        request_obj, 'request_converted',
        f'Your Form E request was converted ({tender_number})',
        f'Your Specification & Budget Clearance "{request_obj.specification_title}" has been converted '
        f'into procurement record {tender_number}. Track it under Procurements.',
    )
    flash(f'Procurement {tender_number} created from the Form E request (status: Draft).', 'success')
    return redirect(url_for('procurements.detail', procurement_id=procurement.id))


def _reject_request(request_obj):
    _require_procurement_staff()
    if request_obj.status in ('converted', 'rejected'):
        flash(f'This request is already {request_obj.status}.', 'warning')
        return None
    reason = (request.form.get('reason') or '').strip()
    if not reason:
        flash('A rejection reason is required.', 'danger')
        return None
    request_obj.status = 'rejected'
    request_obj.rejection_reason = reason
    request_obj.rejected_by_id = current_user.id
    request_obj.rejected_at = datetime.utcnow()
    db.session.commit()
    log_action(f'REQUEST_{request_obj.form_type.upper()}_REJECTED',
               entity_type=type(request_obj).__name__, entity_id=request_obj.id,
               reason=reason, new_value={'status': 'rejected'})
    _notify_requester(
        request_obj, 'request_rejected',
        f'Your {request_obj.form_type_label} request was rejected',
        f'{request_obj.title} was rejected. Reason: {reason}',
    )
    flash('Request rejected and the requester notified.', 'warning')
    return redirect(url_for('requests.queue'))


@requests_bp.route('/form-d/<int:request_id>/reject', methods=['POST'])
@login_required
def reject_form_d(request_id):
    request_obj = FormDRequest.query.get_or_404(request_id)
    response = _reject_request(request_obj)
    if response is None:
        return redirect(url_for('requests.detail_form_d', request_id=request_obj.id))
    return response


@requests_bp.route('/form-e/<int:request_id>/reject', methods=['POST'])
@login_required
def reject_form_e(request_id):
    request_obj = FormERequest.query.get_or_404(request_id)
    response = _reject_request(request_obj)
    if response is None:
        return redirect(url_for('requests.detail_form_e', request_id=request_obj.id))
    return response


def _download_signed_document(request_obj):
    _require_request_access(request_obj)
    if not request_obj.has_signed_document() or not os.path.isfile(request_obj.submitted_form_path):
        abort(404)
    log_action(f'REQUEST_{request_obj.form_type.upper()}_DOCUMENT_VIEWED',
               entity_type=type(request_obj).__name__, entity_id=request_obj.id,
               new_value={'filename': request_obj.submitted_form_filename})
    directory = os.path.dirname(request_obj.submitted_form_path)
    basename = os.path.basename(request_obj.submitted_form_path)
    return send_from_directory(directory, basename, as_attachment=True,
                               download_name=request_obj.submitted_form_filename)


@requests_bp.route('/form-d/<int:request_id>/document')
@login_required
def download_form_d_document(request_id):
    return _download_signed_document(FormDRequest.query.get_or_404(request_id))


@requests_bp.route('/form-e/<int:request_id>/document')
@login_required
def download_form_e_document(request_id):
    return _download_signed_document(FormERequest.query.get_or_404(request_id))


# ---------------------------------------------------------------------------
# Combined Form D & E request routes
# ---------------------------------------------------------------------------
@requests_bp.route('/de/<int:request_id>')
@login_required
def detail_de(request_id):
    request_obj = FormDERequest.query.get_or_404(request_id)
    _require_request_access(request_obj)
    return render_template('requests/detail_de.html',
                           req=request_obj,
                           can_manage=_is_procurement_staff(current_user),
                           status_labels=HUMANIZED_STATUS)


@requests_bp.route('/de/<int:request_id>/document/<doc_type>')
@login_required
def download_form_de_document(request_id, doc_type):
    """Download one of the two attached forms ('form_d' or 'form_e')."""
    request_obj = FormDERequest.query.get_or_404(request_id)
    _require_request_access(request_obj)

    if doc_type == 'form_d':
        file_path = request_obj.form_d_file_path
        filename = request_obj.form_d_filename
    elif doc_type == 'form_e':
        file_path = request_obj.form_e_file_path
        filename = request_obj.form_e_filename
    else:
        abort(404)

    if not file_path or not filename or not os.path.isfile(file_path):
        abort(404)

    log_action(f'REQUEST_DE_DOCUMENT_VIEWED', entity_type='FormDERequest', entity_id=request_obj.id,
               new_value={'doc_type': doc_type, 'filename': filename})
    directory = os.path.dirname(file_path)
    basename = os.path.basename(file_path)
    return send_from_directory(directory, basename, as_attachment=True, download_name=filename)


@requests_bp.route('/de/<int:request_id>/review', methods=['POST'])
@login_required
def review_de(request_id):
    request_obj = FormDERequest.query.get_or_404(request_id)
    return _mark_under_review(request_obj, url_for('requests.detail_de', request_id=request_obj.id))


@requests_bp.route('/de/<int:request_id>/reject', methods=['POST'])
@login_required
def reject_de(request_id):
    request_obj = FormDERequest.query.get_or_404(request_id)
    response = _reject_request(request_obj)
    if response is None:
        return redirect(url_for('requests.detail_de', request_id=request_obj.id))
    return response