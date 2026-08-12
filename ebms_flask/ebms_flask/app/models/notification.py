from datetime import datetime
from app.extensions import db


class Notification(db.Model):
    """In-app + emailed notifications (publication, clarifications, awards,
    complaint updates, deadline reminders)."""
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # Track who sent the message
    type = db.Column(db.String(30), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'))
    reply_to = db.Column(db.Integer, db.ForeignKey('notifications.id'), nullable=True)  # Link to original message
    is_read = db.Column(db.Boolean, default=False)
    emailed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Relationship to sender - overlaps with existing user relationship
    sender = db.relationship('User', foreign_keys=[sender_id], viewonly=True)

    def __repr__(self):
        return f'<Notification {self.title}>'
