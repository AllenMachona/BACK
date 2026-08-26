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
