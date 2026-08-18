"""Clarification visibility and access control system.

Supports PUBLIC clarifications (visible to all eligible bidders)
and TARGETED clarifications (visible only to selected bidders).

Access enforcement is backend-enforced, not just frontend-hidden.
"""
from datetime import datetime
from app.extensions import db


class ClarificationVisibility(db.Model):
    """Controls which bidders can access which clarification documents.
    
    For PUBLIC clarifications: No entry needed (all can see).
    For TARGETED clarifications: One entry per recipient bidder.
    
    Ensures backend API always validates access before serving documents.
    """
    __tablename__ = 'clarification_visibilities'

    id = db.Column(db.Integer, primary_key=True)
    
    # Which clarification
    communication_id = db.Column(db.Integer, db.ForeignKey('communications.id'), nullable=False, index=True)
    
    # Who can see it
    bidder_id = db.Column(db.Integer, db.ForeignKey('bidders.id'), nullable=False, index=True)
    
    # Audit
    granted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    granted_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Revocation (soft delete)
    revoked_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    revoked_at = db.Column(db.DateTime)
    revocation_reason = db.Column(db.Text)
    
    # Relationships
    communication = db.relationship('Communication', backref=db.backref('targeted_visibilities', lazy='dynamic', cascade='all, delete-orphan'))
    bidder = db.relationship('Bidder', backref='clarification_access')
    granted_by = db.relationship('User', foreign_keys=[granted_by_id])
    revoked_by = db.relationship('User', foreign_keys=[revoked_by_id])

    def is_active(self):
        return self.revoked_at is None

    def __repr__(self):
        return f'<ClarificationVisibility comm={self.communication_id} bidder={self.bidder_id}>'


class ClarificationAccess(db.Model):
    """Audit trail for clarification document access.
    
    Records every time a bidder views/downloads a clarification document.
    Used to identify which bidders have seen which information.
    """
    __tablename__ = 'clarification_accesses'

    id = db.Column(db.Integer, primary_key=True)
    
    # What was accessed
    communication_id = db.Column(db.Integer, db.ForeignKey('communications.id'), nullable=False, index=True)
    
    # Who accessed it
    bidder_id = db.Column(db.Integer, db.ForeignKey('bidders.id'), nullable=False, index=True)
    accessed_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # Portal user
    
    # Access type
    access_type = db.Column(db.String(30), nullable=False)  # view, download
    
    # IP for audit
    ip_address = db.Column(db.String(45))
    
    # When
    accessed_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    communication = db.relationship('Communication', backref='access_logs')
    bidder = db.relationship('Bidder')
    accessed_by = db.relationship('User', foreign_keys=[accessed_by_user_id])

    def __repr__(self):
        return f'<ClarificationAccess comm={self.communication_id} bidder={self.bidder_id} {self.access_type}>'
