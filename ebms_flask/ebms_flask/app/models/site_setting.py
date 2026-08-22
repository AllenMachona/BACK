import os
from datetime import datetime
from sqlalchemy.exc import OperationalError, ProgrammingError
from app.extensions import db


class SiteSetting(db.Model):
    __tablename__ = 'site_settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False, index=True)
    value = db.Column(db.String(500), nullable=False, default='')
    label = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def ensure_defaults(cls):
        try:
            probe = 'SELECT 1 FROM site_settings LIMIT 1' if db.engine.name == 'sqlite' else 'SELECT TOP 1 1 FROM site_settings'
            db.session.execute(db.text(probe))
        except (OperationalError, ProgrammingError):
            db.create_all()

        defaults = {
            'app_name': ('Application Name', os.environ.get('APP_NAME') or 'EBMS Botswana'),
            'app_tagline': ('Tagline', os.environ.get('APP_TAGLINE') or 'Secure Procurement and Bid Management'),
            'support_email': ('Support Email', os.environ.get('SUPPORT_EMAIL') or 'support@your-domain.example'),
            'support_phone': ('Support Phone', os.environ.get('SUPPORT_PHONE') or '+267 000 0000'),
            'contact_address': ('Address', os.environ.get('CONTACT_ADDRESS') or 'Your office address'),
            'default_country': ('Country', os.environ.get('DEFAULT_COUNTRY') or 'Botswana'),
            'maintenance_mode': ('Maintenance Mode', 'false'),
            'allow_registration': ('Allow Registration', 'true'),
            'deadline_reminder_days': ('Reminder Days', '3'),
            'direct_procurement_threshold': ('Direct Procurement Threshold', '500000'),
            'open_procurement_threshold': ('Open Procurement Threshold', '500000'),
            'lot_splitting_warning_threshold': ('Lot Splitting Warning Threshold', '500000'),
        }

        for key, (label, value) in defaults.items():
            if not cls.query.filter_by(key=key).first():
                db.session.add(cls(key=key, value=value, label=label, description='System default setting'))
        db.session.commit()

    @classmethod
    def as_dict(cls):
        try:
            return {setting.key: setting.value for setting in cls.query.all()}
        except (OperationalError, ProgrammingError):
            return {}

    @classmethod
    def get(cls, key, default=''):
        try:
            item = cls.query.filter_by(key=key).first()
            return item.value if item else default
        except (OperationalError, ProgrammingError):
            return default

    def __repr__(self):
        return f'<SiteSetting {self.key}>'
