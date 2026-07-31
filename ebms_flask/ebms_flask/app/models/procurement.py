from datetime import datetime
from app.extensions import db


class Procurement(db.Model):
    __tablename__ = 'procurements'

    id = db.Column(db.Integer, primary_key=True)
    tender_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(30), nullable=False)  # works, services, consultancy, supplies, combination
    ppra_code = db.Column(db.String(50))
    method = db.Column(db.String(30), nullable=False)  # open_domestic, open_international, restricted, rfq, direct, rfp...
    evaluation_method = db.Column(db.String(30))        # pass_fail, scored, weighted, least_cost, quality_cost
    envelope_type = db.Column(db.String(10), default='single')  # single, dual
    estimated_value = db.Column(db.Numeric(15, 2), nullable=False)
    user_department = db.Column(db.String(150))

    submission_deadline = db.Column(db.DateTime)
    opening_scheduled_at = db.Column(db.DateTime)

    # Status follows SOAR Appendix C's bid status lifecycle.
    status = db.Column(db.String(30), default='draft', index=True)

    cancelled = db.Column(db.Boolean, default=False)
    cancelled_reason = db.Column(db.Text)
    cancelled_at = db.Column(db.DateTime)
    replacement_of_id = db.Column(db.Integer, db.ForeignKey('procurements.id'))

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    lots = db.relationship('Lot', backref='procurement', lazy='dynamic', cascade='all, delete-orphan')
    submissions = db.relationship('Submission', backref='procurement', lazy='dynamic')
    criteria = db.relationship('EvaluationCriteria', backref='procurement', lazy='dynamic')
    evaluations = db.relationship('Evaluation', backref='procurement', lazy='dynamic')
    committee_members = db.relationship('CommitteeMember', backref='procurement', lazy='dynamic')
    communications = db.relationship('Communication', backref='procurement', lazy='dynamic')
    complaints = db.relationship('Complaint', backref='procurement', lazy='dynamic')
    award = db.relationship('Award', backref='procurement', uselist=False)
    replacement = db.relationship('Procurement', remote_side=[id], backref='replaced_by')

    def status_label(self):
        return self.status.replace('_', ' ').title()

    def bid_count(self):
        return self.submissions.filter_by(status='submitted').count()

    def committee_chair(self):
        return self.committee_members.filter_by(role='chair').first()

    def __repr__(self):
        return f'<Procurement {self.tender_number}>'


class Lot(db.Model):
    """Optional sub-division of a procurement (SOAR FR-INIT-007: lot splitting)."""
    __tablename__ = 'lots'

    id = db.Column(db.Integer, primary_key=True)
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), nullable=False)
    lot_number = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text)
    estimated_value = db.Column(db.Numeric(15, 2))

    def __repr__(self):
        return f'<Lot {self.lot_number}>'
