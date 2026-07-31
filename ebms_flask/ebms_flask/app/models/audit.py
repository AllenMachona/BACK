from datetime import datetime
from app.extensions import db


class AuditLog(db.Model):
    """Append-only. No route in this application ever updates or deletes an
    AuditLog row (SOAR 8.3)."""
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(50))
    entity_id = db.Column(db.Integer)
    previous_value = db.Column(db.Text)  # JSON-serialized
    new_value = db.Column(db.Text)       # JSON-serialized
    ip_address = db.Column(db.String(45))
    reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f'<AuditLog {self.action}>'
