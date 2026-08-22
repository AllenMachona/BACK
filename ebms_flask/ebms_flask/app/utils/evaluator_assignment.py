"""Evaluator assignment service (document-type scope, post-closure).

Centralises the business rules behind assigning evaluators to a closed
procurement:

- An assignment (create/update/revoke) may only happen once the procurement
  is Closed — i.e. status is ``closed`` or any later lifecycle stage.
- Only Procurement-role users may manage assignments.
- The assigned user must be an eligible evaluator (role with can_evaluate).
- One procurement can have many evaluators; each row is unique per
  (procurement, evaluator), so editing a row *is* reassignment.
- Scope controls which submission envelope types the evaluator can see:
  technical -> 'technical' envelopes; single -> 'single'/'financial'
  (financial/commercial) envelopes; both -> everything.
- Every create/update/revoke is audit-logged and the evaluator is notified.
"""
from datetime import datetime
from flask_login import current_user
from app.extensions import db
from app.models.evaluator_assignment import EvaluatorAssignment
from app.models.role import Role
from app.models.user import User
from app.utils.audit_enhanced import log_action
from app.utils.notify import notify_user

# Evaluator assignment is only allowed during the exact Closed stage. Once
# opening/evaluation begins, the assignment window is closed.
ASSIGNABLE_STATUS = 'closed'

# Roles allowed to create/update/revoke evaluator assignments. Matches the
# existing `Role.code.in_(['procurement_unit', 'system_admin',
# 'procurement_oversight'])` pattern used elsewhere (e.g. bid submission
# notifications).
ASSIGNMENT_MANAGER_ROLES = frozenset({
    'procurement_unit',
    'procurement_oversight',
    'system_admin',
})


class EvaluatorAssignmentError(Exception):
    """Raised on a business-rule violation (fatal for the request)."""


# Evaluation stage (Evaluation.evaluation_stage) -> required document-scope
# coverage. 'compliance' has no envelope counterpart so any active assignment
# is enough, while scoring 'financial' demands single/financial coverage.
STAGE_REQUIRED_ENVELOPES = {
    'compliance': None,      # any active assignment
    'technical': ('technical',),
    'financial': ('single', 'financial'),
}


class EvaluatorAssignmentService:
    @staticmethod
    def is_post_closure(procurement):
        """Return True only while the procurement status is exactly Closed."""
        return bool(procurement and procurement.status == ASSIGNABLE_STATUS)

    @staticmethod
    def is_manager(user):
        """A user is allowed to manage assignments if they hold a Procurement
        role (or system admin, matching existing access patterns)."""
        return bool(user and user.role and user.role.code in ASSIGNMENT_MANAGER_ROLES)

    @staticmethod
    def eligible_evaluator_ids():
        """IDs of every active user whose role grants can_evaluate."""
        rows = (
            User.query.join(Role, User.role_id == Role.id)
            .filter(Role.can_evaluate == True, User.is_active == True)
            .all()
        )
        return [u.id for u in rows]

    @staticmethod
    def eligible_evaluators():
        """Every active user whose role grants can_evaluate (for the picker UI)."""
        return (
            User.query.join(Role, User.role_id == Role.id)
            .filter(Role.can_evaluate == True, User.is_active == True)
            .order_by(User.first_name, User.last_name)
            .all()
        )

    @staticmethod
    def is_eligible_evaluator(user):
        return bool(user and user.role and user.role.can_evaluate and user.is_active)

    @staticmethod
    def _payload(assignment):
        return {
            'id': assignment.id,
            'procurement_id': assignment.procurement_id,
            'evaluator_id': assignment.evaluator_id,
            'evaluator_name': assignment.evaluator.full_name() if assignment.evaluator else None,
            'evaluator_role': assignment.evaluator.role.name if (assignment.evaluator and assignment.evaluator.role) else None,
            'document_scope': assignment.document_scope,
            'document_scope_label': assignment.scope_label(),
            'assigned_by': assignment.assigned_by.full_name() if assignment.assigned_by else None,
            'assigned_by_id': assignment.assigned_by_id,
            'assigned_at': assignment.assigned_at.isoformat() if assignment.assigned_at else None,
            'status': assignment.status,
        }

    @staticmethod
    def _current_actor():
        if current_user.is_authenticated:
            return current_user._get_current_object()
        raise EvaluatorAssignmentError('An authenticated user is required.')

    @staticmethod
    def assign(procurement, evaluator, scope, assigned_by=None, reason=None):
        """Create or update (upsert) an evaluator assignment.

        The same call handles assignment and reassignment: when a row for
        (procurement, evaluator) already exists its scope is replaced, which
        is also the audited reassignment action.

        Returns:
            (assignment, created_flag)
        """
        if assigned_by is None:
            assigned_by = EvaluatorAssignmentService._current_actor()

        if not EvaluatorAssignmentService.is_post_closure(procurement):
            raise EvaluatorAssignmentError(
                'Evaluators can only be assigned once the procurement is Closed.'
            )

        if scope not in EvaluatorAssignment.VALID_SCOPES:
            raise EvaluatorAssignmentError(
                f"Invalid document scope '{scope}'. Choose one of: {', '.join(EvaluatorAssignment.VALID_SCOPES)}."
            )

        if not EvaluatorAssignmentService.is_eligible_evaluator(evaluator):
            raise EvaluatorAssignmentError('The selected user is not an eligible evaluator.')

        existing = EvaluatorAssignment.active_for(procurement.id, evaluator.id)
        if existing is None:
            # Reuse revoked rows because the database intentionally enforces
            # one assignment record per evaluator and procurement.
            existing = EvaluatorAssignment.query.filter_by(
                procurement_id=procurement.id,
                evaluator_id=evaluator.id,
            ).first()
        created = existing is None

        if created:
            assignment = EvaluatorAssignment(
                procurement_id=procurement.id,
                evaluator_id=evaluator.id,
                document_scope=scope,
                assigned_by_id=assigned_by.id,
                assigned_at=datetime.utcnow(),
            )
            db.session.add(assignment)
            db.session.flush()
            log_action(
                'EVALUATOR_ASSIGNMENT_CREATED',
                entity_type='EvaluatorAssignment',
                entity_id=assignment.id,
                new_value={
                    'procurement_id': procurement.id,
                    'evaluator_id': evaluator.id,
                    'scope': scope,
                },
                reason=reason,
            )
        else:
            previous_scope = existing.document_scope
            previous_status = existing.status
            existing.document_scope = scope
            existing.assigned_by_id = assigned_by.id
            existing.assigned_at = datetime.utcnow()
            existing.status = 'active'
            db.session.flush()
            log_action(
                'EVALUATOR_ASSIGNMENT_UPDATED',
                entity_type='EvaluatorAssignment',
                entity_id=existing.id,
                previous_value={'scope': previous_scope, 'status': previous_status},
                new_value={'scope': scope, 'status': 'active'},
                reason=reason,
            )
            assignment = existing

        db.session.commit()

        # In-app notification to the evaluator (email falls back to console).
        try:
            notify_user(
                evaluator,
                'evaluator_assignment',
                f'Assigned to {procurement.tender_number}',
                f'You were assigned to evaluate "{procurement.title}" '
                f'({procurement.tender_number}) with scope: '
                f"{assignment.scope_label()}.",
                procurement_id=procurement.id,
            )
        except Exception as exc:  # never fail the request on notification issues
            print(f"EVALUATOR ASSIGNMENT NOTIFICATION FAILURE: {exc}")

        return assignment, created

    @staticmethod
    def revoke(procurement, assignment, assigned_by=None, reason=None):
        """Revoke an evaluator's assignment (soft delete: status -> revoked)."""
        if assigned_by is None:
            assigned_by = EvaluatorAssignmentService._current_actor()

        if not EvaluatorAssignmentService.is_post_closure(procurement):
            raise EvaluatorAssignmentError(
                'Evaluator assignments can only be edited once the procurement is Closed.'
            )

        if assignment.status != 'active':
            raise EvaluatorAssignmentError('This assignment is already revoked.')

        assignment.status = 'revoked'
        db.session.flush()
        log_action(
            'EVALUATOR_ASSIGNMENT_REVOKED',
            entity_type='EvaluatorAssignment',
            entity_id=assignment.id,
            previous_value={'scope': assignment.document_scope, 'status': 'active'},
            new_value={'scope': assignment.document_scope, 'status': 'revoked'},
            reason=reason,
        )
        db.session.commit()
        return assignment

    @staticmethod
    def list_for_procurement(procurement_id, include_revoked=False):
        """Active assignments for a procurement (optionally including revoked)."""
        query = EvaluatorAssignment.query.filter_by(procurement_id=procurement_id)
        if not include_revoked:
            query = query.filter_by(status='active')
        return query.order_by(EvaluatorAssignment.assigned_at.desc()).all()

    @staticmethod
    def for_user(evaluator_id, include_revoked=False):
        """Every assignment held by a user across all procurements."""
        query = EvaluatorAssignment.query.filter_by(evaluator_id=evaluator_id)
        if not include_revoked:
            query = query.filter_by(status='active')
        return query.all()

    @staticmethod
    def assigned_procurement_ids(evaluator_id):
        """Procurement IDs the evaluator is currently assigned to."""
        return {
            a.procurement_id
            for a in EvaluatorAssignment.query.filter_by(
                evaluator_id=evaluator_id, status='active'
            ).all()
        }

    @staticmethod
    def envelopes_for(procurement_id, evaluator_id):
        """Union of Submission.envelope_type values the evaluator may see."""
        assignment = EvaluatorAssignment.active_for(procurement_id, evaluator_id)
        if not assignment:
            return set()
        return set(EvaluatorAssignment.SCOPE_ENVELOPES[assignment.document_scope])

    @staticmethod
    def can_view_envelope(procurement_id, evaluator_id, envelope_type):
        """Server-side scope check for a single submission envelope."""
        return EvaluatorAssignment.can_evaluator_access(
            procurement_id, evaluator_id, envelope_type
        )

    @staticmethod
    def can_submit_stage(procurement_id, evaluator_id, stage):
        """Whether an evaluator may submit a score for a stage given their scope.

        compliance -> any active assignment; technical -> technical envelopes;
        financial -> 'single'/'financial' envelopes.
        """
        assignment = EvaluatorAssignment.active_for(procurement_id, evaluator_id)
        if not assignment:
            return False
        required = STAGE_REQUIRED_ENVELOPES.get(stage)
        if required is None:
            return True
        return EvaluatorAssignment.scope_covers(assignment.document_scope, required[0])