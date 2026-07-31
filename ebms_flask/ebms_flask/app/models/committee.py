from datetime import datetime
from app.extensions import db


class CommitteeMember(db.Model):
    __tablename__ = 'committee_members'

    id = db.Column(db.Integer, primary_key=True)
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Appointment (SOAR 7.9)
    appointment_instrument_ref = db.Column(db.String(100), nullable=False)
    appointment_date = db.Column(db.Date, nullable=False)

    role = db.Column(db.String(30), nullable=False)  # chair, vice_chair, member, secretary, co_opted_adviser
    is_voting_member = db.Column(db.Boolean, default=True)
    skills = db.Column(db.Text)

    # Declarations (SOAR 7.9)
    conflict_of_interest_declared = db.Column(db.Boolean, default=False)
    conflict_of_interest_details = db.Column(db.Text)
    confidentiality_signed = db.Column(db.Boolean, default=False)
    confidentiality_signed_at = db.Column(db.DateTime)

    # Access control
    access_granted = db.Column(db.Boolean, default=False)
    access_granted_at = db.Column(db.DateTime)
    access_revoked_at = db.Column(db.DateTime)

    # Time-bound access
    access_valid_from = db.Column(db.DateTime)
    access_valid_until = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<CommitteeMember {self.role}>'


class EvaluationCriteria(db.Model):
    __tablename__ = 'evaluation_criteria'

    id = db.Column(db.Integer, primary_key=True)
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), nullable=False)
    lot_id = db.Column(db.Integer, db.ForeignKey('lots.id'))

    criteria_type = db.Column(db.String(20), nullable=False)  # compliance, technical, financial
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

    # Scoring
    weight = db.Column(db.Numeric(5, 2), default=0)
    max_score = db.Column(db.Numeric(5, 2), default=0)
    min_qualifying_mark = db.Column(db.Numeric(5, 2))

    # Method
    scoring_method = db.Column(db.String(20))  # pass_fail, points, formula
    is_mandatory = db.Column(db.Boolean, default=False)

    # Lock status (SOAR FR-EVAL-002)
    locked = db.Column(db.Boolean, default=False)
    locked_at = db.Column(db.DateTime)
    locked_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    sequence = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    scores = db.relationship('ScoreSheet', backref='criteria', lazy='dynamic')

    def __repr__(self):
        return f'<EvaluationCriteria {self.name}>'
