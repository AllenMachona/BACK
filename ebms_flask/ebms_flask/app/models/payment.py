from datetime import datetime
from app.extensions import db


class BidderPayment(db.Model):
    """Tracks bidder payment information and proof-of-payment documents for a procurement tender."""
    __tablename__ = 'bidder_payments'

    id = db.Column(db.Integer, primary_key=True)
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), nullable=False, index=True)
    bidder_id = db.Column(db.Integer, db.ForeignKey('bidders.id'), nullable=False, index=True)
    submitted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    payment_reference = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    proof_file_path = db.Column(db.String(500), nullable=False)
    proof_filename = db.Column(db.String(300), nullable=False)
    supporting_document_path = db.Column(db.String(500))
    supporting_document_filename = db.Column(db.String(300))

    # Status: pending, approved, rejected, resubmission_required
    status = db.Column(db.String(30), default='pending', nullable=False, index=True)
    notes = db.Column(db.Text)  # Rejection reason or resubmission instructions from Procurement

    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    reviewed_at = db.Column(db.DateTime)

    # Relationships
    procurement = db.relationship('Procurement', backref=db.backref('payments', lazy='dynamic', cascade='all, delete-orphan'))
    bidder = db.relationship('Bidder', backref=db.backref('payments', lazy='dynamic', cascade='all, delete-orphan'))
    submitted_by = db.relationship('User', foreign_keys=[submitted_by_id], backref='submitted_payments')
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_id], backref='reviewed_payments')
    document_accesses = db.relationship('BidderDocumentAccess', backref='payment', lazy='dynamic', cascade='all, delete-orphan')

    def status_label(self):
        return self.status.replace('_', ' ').title()

    def is_approved(self):
        return self.status == 'approved'

    def is_pending(self):
        return self.status == 'pending'

    def is_rejected(self):
        return self.status == 'rejected'

    def is_resubmission_required(self):
        return self.status == 'resubmission_required'

    def __repr__(self):
        return f'<BidderPayment {self.payment_reference} ({self.status})>'


class BidderDocumentAccess(db.Model):
    """Tracks document-level access permissions granted to specific bidders for restricted ITT documents."""
    __tablename__ = 'bidder_document_accesses'

    id = db.Column(db.Integer, primary_key=True)
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), nullable=False, index=True)
    bidder_id = db.Column(db.Integer, db.ForeignKey('bidders.id'), nullable=False, index=True)
    document_type = db.Column(db.String(30), nullable=False, default='all_bidder_docs')  # itt, all_bidder_docs
    payment_id = db.Column(db.Integer, db.ForeignKey('bidder_payments.id'))

    # Access status: active, revoked
    status = db.Column(db.String(20), default='active', nullable=False, index=True)

    granted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    granted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    revoked_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    revoked_at = db.Column(db.DateTime)
    revocation_reason = db.Column(db.Text)

    # Relationships
    procurement = db.relationship('Procurement', backref=db.backref('document_accesses', lazy='dynamic', cascade='all, delete-orphan'))
    bidder = db.relationship('Bidder', backref=db.backref('document_accesses', lazy='dynamic', cascade='all, delete-orphan'))
    granted_by = db.relationship('User', foreign_keys=[granted_by_id], backref='granted_document_accesses')
    revoked_by = db.relationship('User', foreign_keys=[revoked_by_id], backref='revoked_document_accesses')

    @classmethod
    def can_bidder_access(cls, procurement_id, bidder_id, document_type=None):
        """Returns True if the bidder currently has active access to the given document type for the procurement."""
        if not procurement_id or not bidder_id:
            return False

        query = cls.query.filter_by(
            procurement_id=procurement_id,
            bidder_id=bidder_id,
            status='active'
        )

        if document_type:
            query = query.filter(
                (cls.document_type == document_type) | (cls.document_type == 'all_bidder_docs')
            )

        return query.first() is not None

    def __repr__(self):
        return f'<BidderDocumentAccess {self.procurement_id}:{self.bidder_id}:{self.document_type} ({self.status})>'
