from datetime import datetime
from app.extensions import db


class Award(db.Model):
    """FR-AWD-001/005: award decision and cooling-off tracking."""
    __tablename__ = 'awards'

    id = db.Column(db.Integer, primary_key=True)
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), unique=True, nullable=False)
    winning_bidder_id = db.Column(db.Integer, db.ForeignKey('bidders.id'), nullable=False)

    decision_date = db.Column(db.DateTime, default=datetime.utcnow)
    cooling_off_expiry = db.Column(db.DateTime, nullable=False)
    contract_concluded = db.Column(db.Boolean, default=False)
    contract_concluded_at = db.Column(db.DateTime)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    winning_bidder = db.relationship('Bidder', foreign_keys=[winning_bidder_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    def cooling_off_active(self):
        return datetime.utcnow() < self.cooling_off_expiry

    def __repr__(self):
        return f'<Award procurement={self.procurement_id}>'
