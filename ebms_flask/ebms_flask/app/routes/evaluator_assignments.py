"""Evaluator assignment API (document-type scope, post-closure).

Endpoints:
    GET  /api/evaluator-assignments                        list assignments
    GET  /api/evaluator-assignments?procurement_id=<id>    list for a procurement
    GET  /api/evaluator-assignments/mine                   own assignments (evaluator)
    POST /api/evaluator-assignments                        create/update (upsert)
    POST /api/evaluator-assignments/<id>/revoke            revoke an assignment

Restrictions (enforced here and in the service):
- Create/update/revoke require a Procurement role (procurement_unit,
  procurement_oversight) or system_admin.
- Every write requires the procurement to be Closed (status 'closed' or any
  later lifecycle stage) — see evaluator_assignment.POST_CLOSURE_STATUSES.
- Evaluators may read only their own assignments.

Both JSON and form-encoded payloads are accepted so the server-rendered
detail-page modal can submit either way.
"""
from flask import Blueprint, jsonify, request, abort
from flask_login import login_required, current_user
from app.models.evaluator_assignment import EvaluatorAssignment
from app.models.procurement import Procurement
from app.models.user import User
from app.utils.evaluator_assignment import (
    EvaluatorAssignmentService,
    EvaluatorAssignmentError,
)

evaluator_assignments_bp = Blueprint(
    'evaluator_assignments', __name__, url_prefix='/api/evaluator-assignments'
)


def _assignment_json(assignment):
    if assignment is None:
        return None
    return EvaluatorAssignmentService._payload(assignment)


def _manager_required():
    """Abort unless the caller holds a Procurement role / system admin."""
    if not EvaluatorAssignmentService.is_manager(current_user):
        abort(403)


def _request_payload():
    """Accept JSON or form-encoded bodies (JSON wins)."""
    json_data = request.get_json(silent=True)
    if isinstance(json_data, dict):
        return json_data
    return request.form


@evaluator_assignments_bp.get('/mine')
@login_required
def mine():
    """Current user's own assignments (evaluator-facing)."""
    assignments = EvaluatorAssignmentService.for_user(current_user.id)
    return _ok({
        'ok': True,
        'assignments': [_assignment_json(a) for a in assignments],
    })


@evaluator_assignments_bp.get('')
@login_required
def list_assignments():
    """List assignments.

    Managers may list every assignment (optionally filtered by procurement_id);
    evaluators may only list their own.
    """
    procurement_id = request.args.get('procurement_id', type=int)
    include_revoked = request.args.get('include_revoked', 'false').lower() in ('1', 'true', 'yes')

    if EvaluatorAssignmentService.is_manager(current_user):
        if procurement_id:
            Procurement.query.get_or_404(procurement_id)
            assignments = EvaluatorAssignmentService.list_for_procurement(
                procurement_id, include_revoked=include_revoked
            )
        else:
            query = EvaluatorAssignment.query
            if not include_revoked:
                query = query.filter_by(status='active')
            assignments = query.order_by(EvaluatorAssignment.assigned_at.desc()).all()
    elif current_user.role and current_user.role.can_evaluate:
        assignments = EvaluatorAssignmentService.for_user(
            current_user.id, include_revoked=include_revoked
        )
        if procurement_id:
            assignments = [a for a in assignments if a.procurement_id == procurement_id]
    else:
        abort(403)

    return _ok({
        'ok': True,
        'assignments': [_assignment_json(a) for a in assignments],
    })


def _ok(data):
    return jsonify(data), 200


def _fail(message, code=400):
    return jsonify({'ok': False, 'message': message}), code


@evaluator_assignments_bp.post('')
@login_required
def upsert_assignment():
    """Create (201) or update/reassign (200) an evaluator assignment.

    A single evaluator keeps one row per procurement; overwriting the scope
    on that row is the reassignment action.
    """
    _manager_required()

    payload = _request_payload()
    try:
        procurement_id = int(payload.get('procurement_id'))
        evaluator_id = int(payload.get('evaluator_id'))
    except (TypeError, ValueError):
        return _fail('procurement_id and evaluator_id must be numbers.', 400)

    scope = (payload.get('scope') or '').strip()
    reason = payload.get('reason') or None

    procurement = Procurement.query.get(procurement_id)
    if not procurement:
        return _fail('Procurement not found.', 404)

    evaluator = User.query.get(evaluator_id)
    if not evaluator:
        return _fail('Evaluator user not found.', 404)

    try:
        assignment, created = EvaluatorAssignmentService.assign(
            procurement=procurement,
            evaluator=evaluator,
            scope=scope,
            reason=reason,
        )
    except EvaluatorAssignmentError as exc:
        return _fail(str(exc), 400)

    message = 'Evaluator assigned.' if created else 'Evaluator assignment updated.'
    return (
        jsonify({'ok': True, 'message': message, 'assignment': _assignment_json(assignment)}),
        201 if created else 200,
    )


@evaluator_assignments_bp.post('/<int:assignment_id>/revoke')
@login_required
def revoke_assignment(assignment_id):
    """Revoke an active evaluator assignment (soft delete, audit-logged)."""
    _manager_required()

    assignment = EvaluatorAssignment.query.get(assignment_id)
    if not assignment:
        return _fail('Assignment not found.', 404)

    procurement = Procurement.query.get(assignment.procurement_id)
    payload = _request_payload()
    reason = payload.get('reason') or None

    try:
        EvaluatorAssignmentService.revoke(
            procurement=procurement,
            assignment=assignment,
            reason=reason,
        )
    except EvaluatorAssignmentError as exc:
        return _fail(str(exc), 400)

    return jsonify({
        'ok': True,
        'message': 'Evaluator assignment revoked.',
        'assignment': _assignment_json(assignment),
    })