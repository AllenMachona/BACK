from datetime import datetime

from app.extensions import db


class EvaluatorFeedback(db.Model):
    """A document-backed result submitted by an assigned evaluator."""
    __tablename__ = 'evaluator_feedback'

    id = db.Column(db.Integer, primary_key=True)
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), nullable=False, index=True)
    evaluator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    feedback_text = db.Column(db.Text)
    file_path = db.Column(db.String(500), nullable=False)
    original_filename = db.Column(db.String(300), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    procurement = db.relationship(
        'Procurement',
        backref=db.backref('evaluator_feedback', lazy='dynamic'),
    )
    evaluator = db.relationship('User', foreign_keys=[evaluator_id])

    def __repr__(self):
        return f'<EvaluatorFeedback procurement={self.procurement_id} evaluator={self.evaluator_id}>'