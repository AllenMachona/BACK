"""Procurement state history and restoration tracking.

Records all significant procurement state changes (open, close, cancel, restore).
Enables authorized staff to restore previous states where business rules permit.
Original actions are NEVER erased from the audit trail.
"""
from datetime import datetime
from app.extensions import db


class ProcurementHistory(db.Model):
    """Immutable record of procurement state transitions.
    
    Every significant state change is recorded:
    - Draft → Published → Submission Open → Opening → Evaluation → Award → Concluded
    - Cancelled (with reason)
    - Reopened/Extended
    - Restored (reverting a previous action)
    
    Used to:
    - Allow restoration of accidentally closed procurements
    - Audit who changed what and when
    - Preserve business continuity
    """
    __tablename__ = 'procurement_histories'

    id = db.Column(db.Integer, primary_key=True)
    
    # Which procurement
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), nullable=False, index=True)
    
    # State change
    action = db.Column(db.String(50), nullable=False)  # published, submission_open, submission_closed, opening, cancelled, restored, etc.
    
    # Previous state
    previous_status = db.Column(db.String(30))
    
    # New state
    new_status = db.Column(db.String(30))
    
    # For cancellations and restorations
    reason = db.Column(db.Text)
    
    # For restorations: which history entry is being restored from
    restored_from_history_id = db.Column(db.Integer, db.ForeignKey('procurement_histories.id'))
    
    # Who made the change
    performed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    performed_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    # Approval information (if required)
    requires_approval = db.Column(db.Boolean, default=False)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)
    
    # Affected submission deadline/opening date (if changed)
    affected_submission_deadline = db.Column(db.DateTime)
    affected_opening_date = db.Column(db.DateTime)
    
    # Relationships
    procurement = db.relationship('Procurement', backref=db.backref('state_history', lazy='dynamic'))
    performed_by = db.relationship('User', foreign_keys=[performed_by_id], backref='performed_procurement_actions')
    approved_by = db.relationship('User', foreign_keys=[approved_by_id], backref='approved_procurement_actions')
    restored_from = db.relationship('ProcurementHistory', remote_side=[id], backref='restorations')

    def __repr__(self):
        return f'<ProcurementHistory proc={self.procurement_id} {self.action}>'

    @classmethod
    def log_action(cls, procurement_id, action, performed_by_id, reason=None, 
                  previous_status=None, new_status=None, restored_from_history_id=None):
        """Log a procurement state change."""
        entry = cls(
            procurement_id=procurement_id,
            action=action,
            previous_status=previous_status,
            new_status=new_status,
            reason=reason,
            restored_from_history_id=restored_from_history_id,
            performed_by_id=performed_by_id,
        )
        db.session.add(entry)
        return entry


class SubmissionHistory(db.Model):
    """Track submission state changes (replace, restore, withdraw, etc).
    
    When a bidder replaces a submission, the old one is never deleted.
    Instead, a new version is created and status changes are audited.
    Allows restoration where business rules permit.
    """
    __tablename__ = 'submission_histories'

    id = db.Column(db.Integer, primary_key=True)
    
    # Which submission
    submission_id = db.Column(db.Integer, db.ForeignKey('submissions.id'), nullable=False, index=True)
    
    # What changed
    action = db.Column(db.String(50), nullable=False)  # submitted, replaced, withdrawn, restored
    
    # Previous/new state
    previous_status = db.Column(db.String(20))
    new_status = db.Column(db.String(20))
    
    # Reason (required for withdrawal/restoration)
    reason = db.Column(db.Text)
    
    # Who made the change
    performed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    performed_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    # For replacements: reference to previous submission version
    replaced_submission_id = db.Column(db.Integer, db.ForeignKey('submissions.id'))
    
    # Relationships
    submission = db.relationship('Submission', foreign_keys=[submission_id], backref=db.backref('change_history', lazy='dynamic'))
    performed_by = db.relationship('User', foreign_keys=[performed_by_id], backref='performed_submission_actions')
    replaced_submission = db.relationship('Submission', foreign_keys=[replaced_submission_id])

    def __repr__(self):
        return f'<SubmissionHistory sub={self.submission_id} {self.action}>'
