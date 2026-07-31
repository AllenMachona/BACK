from datetime import datetime
from app.extensions import db


class Evaluation(db.Model):
    __tablename__ = 'evaluations'

    id = db.Column(db.Integer, primary_key=True)
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), nullable=False)
    lot_id = db.Column(db.Integer, db.ForeignKey('lots.id'))
    bidder_id = db.Column(db.Integer, db.ForeignKey('bidders.id'), nullable=False)
    evaluator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Stage
    evaluation_stage = db.Column(db.String(30), nullable=False)  # compliance, technical, financial

    # Independent scoring (SOAR FR-EVAL-004)
    score = db.Column(db.Numeric(5, 2))
    comments = db.Column(db.Text)
    evidence_references = db.Column(db.Text)

    # Consensus
    is_consensus = db.Column(db.Boolean, default=False)
    consensus_reached = db.Column(db.Boolean, default=False)
    consensus_score = db.Column(db.Numeric(5, 2))
    consensus_comments = db.Column(db.Text)

    # Gate result
    passed = db.Column(db.Boolean)
    eliminated = db.Column(db.Boolean, default=False)
    elimination_reason = db.Column(db.Text)

    # Approval
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    score_sheets = db.relationship('ScoreSheet', backref='evaluation', lazy='dynamic')

    def __repr__(self):
        return f'<Evaluation {self.evaluation_stage}>'


class ScoreSheet(db.Model):
    __tablename__ = 'score_sheets'

    id = db.Column(db.Integer, primary_key=True)
    evaluation_id = db.Column(db.Integer, db.ForeignKey('evaluations.id'), nullable=False)
    criteria_id = db.Column(db.Integer, db.ForeignKey('evaluation_criteria.id'), nullable=False)

    score = db.Column(db.Numeric(5, 2))
    max_score = db.Column(db.Numeric(5, 2))
    weight = db.Column(db.Numeric(5, 2))
    weighted_score = db.Column(db.Numeric(5, 2))

    comments = db.Column(db.Text)
    evidence_reference = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
