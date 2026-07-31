from datetime import datetime
from app.extensions import db


class Role(db.Model):
    __tablename__ = 'roles'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Role-based access control flags (SOAR Appendix A)
    can_create_procurement = db.Column(db.Boolean, default=False)
    can_approve_procurement = db.Column(db.Boolean, default=False)
    can_publish = db.Column(db.Boolean, default=False)
    can_evaluate = db.Column(db.Boolean, default=False)
    can_open_bids = db.Column(db.Boolean, default=False)
    can_award = db.Column(db.Boolean, default=False)
    can_view_all_records = db.Column(db.Boolean, default=False)
    can_admin_system = db.Column(db.Boolean, default=False)
    can_bid = db.Column(db.Boolean, default=False)

    users = db.relationship('User', backref='role', lazy='dynamic', foreign_keys='User.role_id')

    def __repr__(self):
        return f'<Role {self.code}>'
