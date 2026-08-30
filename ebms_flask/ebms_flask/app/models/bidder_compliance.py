from datetime import datetime

from app.extensions import db


class BidderComplianceDocument(db.Model):
    """Compliance document submitted during bidder registration."""
    __tablename__ = 'bidder_compliance_documents'

    REQUIRED_DOCUMENT_TYPES = {
        'cipa_equivalent': 'CIPA / Equivalent',
        'tax_certificate': 'Tax Certificate',
    }

    id = db.Column(db.Integer, primary_key=True)
    bidder_id = db.Column(db.Integer, db.ForeignKey('bidders.id'), nullable=False, index=True)
    document_type = db.Column(db.String(50), nullable=False, default='cipa_equivalent', index=True)
    file_path = db.Column(db.String(500), nullable=False)
    original_filename = db.Column(db.String(300), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    review_notes = db.Column(db.Text)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at = db.Column(db.DateTime)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    bidder = db.relationship('Bidder', backref=db.backref('compliance_documents', cascade='all, delete-orphan'))
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_id])

    __table_args__ = (
        db.UniqueConstraint('bidder_id', 'document_type', name='uq_bidder_compliance_document_type'),
    )

    @property
    def document_label(self):
        return self.REQUIRED_DOCUMENT_TYPES.get(self.document_type, self.document_type.replace('_', ' ').title())

    def is_pending(self):
        return self.status == 'pending'