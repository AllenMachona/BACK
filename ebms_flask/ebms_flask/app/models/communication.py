from datetime import datetime
from app.extensions import db


class Communication(db.Model):
    """SOAR 7.6: questions, clarifications, addenda and notices — the single
    official channel through which anything communicated to bidders must pass."""
    __tablename__ = 'communications'

    id = db.Column(db.Integer, primary_key=True)
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # question, clarification, addendum, notice
    content = db.Column(db.Text, nullable=False)

    from_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    from_bidder_id = db.Column(db.Integer, db.ForeignKey('bidders.id'))  # set when a bidder asks a question
    is_public = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    from_user = db.relationship('User', foreign_keys=[from_user_id])
    from_bidder = db.relationship('Bidder', foreign_keys=[from_bidder_id])

    def __repr__(self):
        return f'<Communication {self.type}>'
