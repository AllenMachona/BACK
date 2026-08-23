from datetime import datetime

from app.extensions import db


class BidderComplianceDocument(db.Model):
    """Compliance document submitted during bidder registration."""
    __tablename__ = 'bidder_compliance_documents'

    id = db.Column(db.Integer, primary_key=True)
    bidder_id = db.Column(db.Integer, db.ForeignKey('bidders.id'), nullable=False, unique=True, index=True)
    file_path = db.Column(db.String(500), nullable=False)
    original_filename = db.Column(db.String(300), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    review_notes = db.Column(db.Text)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at = db.Column(db.DateTime)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    bidder = db.relationship('Bidder', backref=db.backref('compliance_document', uselist=False))
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_id])

    def is_pending(self):
        return self.status == 'pending'