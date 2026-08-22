from datetime import datetime

from app.extensions import db


class BidderPerformance(db.Model):
    """A procurement-specific performance review for an awarded bidder."""
    __tablename__ = 'bidder_performance'

    id = db.Column(db.Integer, primary_key=True)
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), nullable=False, index=True)
    bidder_id = db.Column(db.Integer, db.ForeignKey('bidders.id'), nullable=False, index=True)
    delivery_score = db.Column(db.Integer, nullable=False)
    quality_score = db.Column(db.Integer, nullable=False)
    compliance_score = db.Column(db.Integer, nullable=False)
    overall_score = db.Column(db.Numeric(5, 2), nullable=False)
    status = db.Column(db.String(30), nullable=False, default='under_review')
    notes = db.Column(db.Text)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reviewed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    procurement = db.relationship('Procurement', backref=db.backref('bidder_performance_reviews', lazy='dynamic', cascade='all, delete-orphan'))
    bidder = db.relationship('Bidder', backref=db.backref('performance_reviews', lazy='dynamic'))
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_id])

    STATUSES = ('under_review', 'satisfactory', 'needs_improvement', 'completed')