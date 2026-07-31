from datetime import datetime
from app.extensions import db


class Complaint(db.Model):
    """SOAR 7.13: complaints, review and appeals."""
    __tablename__ = 'complaints'

    id = db.Column(db.Integer, primary_key=True)
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), nullable=False)
    bidder_id = db.Column(db.Integer, db.ForeignKey('bidders.id'), nullable=False)

    grounds = db.Column(db.Text, nullable=False)
    relief_sought = db.Column(db.Text)
    status = db.Column(db.String(20), default='received')  # received, under_review, upheld, dismissed, escalated
    decision = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime)
    resolved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    resolved_by = db.relationship('User', foreign_keys=[resolved_by_id])

    def __repr__(self):
        return f'<Complaint {self.id} status={self.status}>'
