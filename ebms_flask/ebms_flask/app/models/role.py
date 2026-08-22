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

    @classmethod
    def ensure_default_roles(cls):
        """Idempotently insert roles that every environment needs, without
        re-running the full seed (which would also create demo users and
        procurements). Mirrors SiteSetting.ensure_defaults()."""
        defaults = [
            dict(code='requester', name='Requester',
                 description='User department staff who submit Form D / Form E procurement requests.'),
            dict(code='system_admin', name='System Administrator',
                 can_admin_system=True, can_view_all_records=True),
            dict(code='accounting_officer', name='Accounting Officer',
                 can_approve_procurement=True, can_award=True, can_view_all_records=True),
            dict(code='procurement_oversight', name='Procurement Oversight',
                 can_approve_procurement=True, can_view_all_records=True),
            dict(code='procurement_unit', name='Procurement Unit',
                 can_create_procurement=True, can_publish=True, can_view_all_records=True),
            dict(code='user_department', name='User Department', can_create_procurement=True),
            dict(code='committee_chair', name='Committee Chair', can_evaluate=True),
            dict(code='committee_secretary', name='Committee Secretary', can_evaluate=True),
            dict(code='evaluator', name='Evaluator', can_evaluate=True),
            dict(code='opening_panel', name='Opening Panel', can_open_bids=True),
            dict(code='bidder', name='Bidder', can_bid=True),
        ]
        try:
            for spec in defaults:
                existing = cls.query.filter_by(code=spec['code']).first()
                if existing:
                    continue
                db.session.add(cls(**spec))
            db.session.commit()
        except Exception as exc:
            # Never crash the app during startup because a role insert failed
            # (e.g. roles table not migrated yet on an old database).
            db.session.rollback()
            print(f"ROLE DEFAULT SEED WARNING: {exc}")
