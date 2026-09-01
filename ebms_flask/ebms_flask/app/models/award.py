from datetime import datetime
from app.extensions import db
from sqlalchemy import text


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
    award_value = db.Column(db.Numeric(15, 2))
    decision_reason = db.Column(db.Text)
    decision_notes = db.Column(db.Text)
    published_at = db.Column(db.DateTime)
    published_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    # POU / AO workflow tracking: pre-decision packet, AO final decision, and publish step.
    pre_decision_at = db.Column(db.DateTime)
    pre_decision_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    pou_score_summary = db.Column(db.Text)
    pou_score_reasons = db.Column(db.Text)
    pou_decision_document_path = db.Column(db.String(500))
    pou_decision_document_name = db.Column(db.String(255))
    evaluation_results_file_path = db.Column(db.String(500))
    evaluation_results_filename = db.Column(db.String(255))
    ao_decision_at = db.Column(db.DateTime)
    ao_decision_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    ao_decision_reason = db.Column(db.Text)
    ao_final_choice_summary = db.Column(db.Text)
    ao_decision_document_path = db.Column(db.String(500))
    ao_decision_document_name = db.Column(db.String(255))

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    winning_bidder = db.relationship('Bidder', foreign_keys=[winning_bidder_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    published_by = db.relationship('User', foreign_keys=[published_by_id])

    def cooling_off_active(self):
        return datetime.utcnow() < self.cooling_off_expiry

    @classmethod
    def ensure_schema_columns(cls):
        for column_name, column_sql in {
            'award_value': 'ALTER TABLE awards ADD award_value NUMERIC(15, 2)',
            'decision_reason': 'ALTER TABLE awards ADD decision_reason TEXT',
            'decision_notes': 'ALTER TABLE awards ADD decision_notes TEXT',
            'published_at': 'ALTER TABLE awards ADD published_at DATETIME',
            'published_by_id': 'ALTER TABLE awards ADD published_by_id INTEGER',
            'pre_decision_at': 'ALTER TABLE awards ADD pre_decision_at DATETIME',
            'pre_decision_by_id': 'ALTER TABLE awards ADD pre_decision_by_id INTEGER',
            'pou_score_summary': 'ALTER TABLE awards ADD pou_score_summary TEXT',
            'pou_score_reasons': 'ALTER TABLE awards ADD pou_score_reasons TEXT',
            'pou_decision_document_path': 'ALTER TABLE awards ADD pou_decision_document_path VARCHAR(500)',
            'pou_decision_document_name': 'ALTER TABLE awards ADD pou_decision_document_name VARCHAR(255)',
            'evaluation_results_file_path': 'ALTER TABLE awards ADD evaluation_results_file_path VARCHAR(500)',
            'evaluation_results_filename': 'ALTER TABLE awards ADD evaluation_results_filename VARCHAR(255)',
            'ao_decision_at': 'ALTER TABLE awards ADD ao_decision_at DATETIME',
            'ao_decision_by_id': 'ALTER TABLE awards ADD ao_decision_by_id INTEGER',
            'ao_decision_reason': 'ALTER TABLE awards ADD ao_decision_reason TEXT',
            'ao_final_choice_summary': 'ALTER TABLE awards ADD ao_final_choice_summary TEXT',
            'ao_decision_document_path': 'ALTER TABLE awards ADD ao_decision_document_path VARCHAR(500)',
            'ao_decision_document_name': 'ALTER TABLE awards ADD ao_decision_document_name VARCHAR(255)',
        }.items():
            try:
                probe = f'SELECT TOP 1 {column_name} FROM awards' if db.engine.name != 'sqlite' else f'SELECT {column_name} FROM awards LIMIT 1'
                db.session.execute(text(probe))
            except Exception:
                try:
                    db.session.execute(text(column_sql))
                except Exception:
                    db.session.rollback()
        db.session.commit()

    def __repr__(self):
        return f'<Award procurement={self.procurement_id}>'
