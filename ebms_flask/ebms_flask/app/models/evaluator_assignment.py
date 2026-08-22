"""Evaluator assignment with document-type scope (post-closure).

After a procurement closes, Procurement-role users assign evaluator(s) to a
specific procurement and grant them access to a specific document scope:

    technical -> submission envelope_type == 'technical'
    single    -> submission envelope_type in ('single', 'financial')  # financial/commercial side
    both      -> all three

There is at most one active row per (procurement_id, evaluator_id); editing
the scope on that row IS the reassignment action. Every write is audit-logged
and the evaluator is notified (see app/utils/evaluator_assignment.py).
"""
from datetime import datetime
from app.extensions import db


class EvaluatorAssignment(db.Model):
    __tablename__ = 'evaluator_assignments'
    __table_args__ = (
        db.UniqueConstraint('procurement_id', 'evaluator_id', name='uq_evaluator_assignment_proc_eval'),
    )

    id = db.Column(db.Integer, primary_key=True)
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), nullable=False, index=True)
    evaluator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Document scope: 'technical', 'single' or 'both' (see SCOPE_ENVELOPES).
    document_scope = db.Column(db.String(20), nullable=False, index=True)

    # Audit on the assignment itself (mirrors BidderDocumentAccess).
    assigned_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # active | revoked
    status = db.Column(db.String(20), default='active', nullable=False, index=True)

    # Relationships — foreign_keys is explicit because User has several FKs
    # pointing at this model chain (evaluator, assigned_by), same pattern as
    # User.evaluations / User.audit_logs.
    procurement = db.relationship(
        'Procurement',
        backref=db.backref('evaluator_assignments', lazy='dynamic'),
    )
    evaluator = db.relationship(
        'User',
        foreign_keys=[evaluator_id],
        backref=db.backref('evaluator_assignments', lazy='dynamic'),
    )
    assigned_by = db.relationship(
        'User',
        foreign_keys=[assigned_by_id],
        backref=db.backref('evaluator_assignments_made', lazy='dynamic'),
    )

    # document_scope -> Submission.envelope_type values granted by that scope.
    SCOPE_ENVELOPES = {
        'technical': ('technical',),
        'single': ('single', 'financial'),
        'both': ('technical', 'single', 'financial'),
    }
    VALID_SCOPES = tuple(SCOPE_ENVELOPES.keys())

    @classmethod
    def scope_covers(cls, scope, envelope_type):
        """Return True if a scope grants access to the given envelope type."""
        if scope not in cls.SCOPE_ENVELOPES:
            return False
        return envelope_type in cls.SCOPE_ENVELOPES[scope]

    @classmethod
    def active_for(cls, procurement_id, evaluator_id):
        """Return the current (non-revoked) assignment row, if any."""
        if not procurement_id or not evaluator_id:
            return None
        return cls.query.filter_by(
            procurement_id=procurement_id,
            evaluator_id=evaluator_id,
            status='active',
        ).first()

    @classmethod
    def can_evaluator_access(cls, procurement_id, evaluator_id, envelope_type):
        """Server-side check: does the evaluator have an active assignment that
        grants access to the given submission envelope type?"""
        if not envelope_type:
            return False
        assignment = cls.active_for(procurement_id, evaluator_id)
        if not assignment:
            return False
        return cls.scope_covers(assignment.document_scope, envelope_type)

    def scope_label(self):
        return {
            'technical': 'Technical only',
            'single': 'Single only (financial/commercial)',
            'both': 'Both',
        }.get(self.document_scope, self.document_scope)

    def __repr__(self):
        return f'<EvaluatorAssignment proc={self.procurement_id} evaluator={self.evaluator_id} scope={self.document_scope} ({self.status})>'