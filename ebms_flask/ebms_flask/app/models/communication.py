from datetime import datetime
from app.extensions import db


class Communication(db.Model):
    """SOAR 7.6: questions, clarifications, addenda and notices — the single
    official channel through which anything communicated to bidders must pass."""
    __tablename__ = 'communications'

    id = db.Column(db.Integer, primary_key=True)
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # question, clarification, addendum, notice, advertisement
    content = db.Column(db.Text, nullable=False)
    file_path = db.Column(db.String(500))
    original_filename = db.Column(db.String(255))

    from_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    from_bidder_id = db.Column(db.Integer, db.ForeignKey('bidders.id'))  # set when a bidder asks a question
    is_public = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    from_user = db.relationship('User', foreign_keys=[from_user_id])
    from_bidder = db.relationship('Bidder', foreign_keys=[from_bidder_id])

    @classmethod
    def ensure_schema_columns(cls):
        from sqlalchemy import text
        for column_name, column_sql in {
            'file_path': 'ALTER TABLE communications ADD COLUMN file_path VARCHAR(500)',
            'original_filename': 'ALTER TABLE communications ADD COLUMN original_filename VARCHAR(255)',
        }.items():
            try:
                db.session.execute(text(f'SELECT {column_name} FROM communications LIMIT 1'))
            except Exception:
                db.session.execute(text(column_sql))
        db.session.commit()

    def __repr__(self):
        return f'<Communication {self.type}>'
