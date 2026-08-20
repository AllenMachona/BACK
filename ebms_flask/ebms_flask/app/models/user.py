import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
import uuid
from datetime import datetime, timedelta
from flask_login import UserMixin
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256))

    # Profile
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    department = db.Column(db.String(100))
    designation = db.Column(db.String(100))
    employee_id = db.Column(db.String(50))

    # Role and delegation (SOAR Section 5)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False)
    delegation_limit = db.Column(db.Numeric(15, 2), default=0)
    delegation_start = db.Column(db.DateTime)
    delegation_end = db.Column(db.DateTime)
    delegation_conditions = db.Column(db.Text)

    # Bidder linkage — set only for role_code == 'bidder' accounts
    bidder_id = db.Column(db.Integer, db.ForeignKey('bidders.id'))

    # Security (SOAR Section 8.1)
    is_active = db.Column(db.Boolean, default=True)
    mfa_enabled = db.Column(db.Boolean, default=False)
    mfa_secret = db.Column(db.String(256))
    last_login = db.Column(db.DateTime)
    last_login_ip = db.Column(db.String(45))
    failed_login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime)
    password_changed_at = db.Column(db.DateTime, default=datetime.utcnow)
    password_expiry_days = db.Column(db.Integer, default=90)
    reset_token = db.Column(db.String(255))
    reset_token_expires_at = db.Column(db.DateTime)

    # Personalization / user settings
    preferences = db.Column(db.Text, default='{}')

    # Federation (SOAR SEC-002)
    federation_id = db.Column(db.String(256))
    federation_provider = db.Column(db.String(50))

    # Conflict of interest declaration
    conflict_of_interest_declared = db.Column(db.Boolean, default=False)
    conflict_of_interest_details = db.Column(db.Text)
    confidentiality_signed = db.Column(db.Boolean, default=False)
    confidentiality_signed_at = db.Column(db.DateTime)

    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships — every FK below has more than one column pointing at
    # 'users' or 'procurements' etc. somewhere in the schema, so each one is
    # given an explicit foreign_keys= to avoid AmbiguousForeignKeysError.
    procurements_created = db.relationship(
        'Procurement', foreign_keys='Procurement.created_by_id', backref='creator', lazy='dynamic'
    )
    evaluations = db.relationship(
        'Evaluation', foreign_keys='Evaluation.evaluator_id', backref='evaluator', lazy='dynamic'
    )
    evaluations_approved = db.relationship(
        'Evaluation', foreign_keys='Evaluation.approved_by', backref='approver', lazy='dynamic'
    )
    committee_memberships = db.relationship(
        'CommitteeMember', foreign_keys='CommitteeMember.user_id', backref='user', lazy='dynamic'
    )
    audit_logs = db.relationship(
        'AuditLog', foreign_keys='AuditLog.user_id', backref='user', lazy='dynamic'
    )
    notifications = db.relationship(
        'Notification', foreign_keys='Notification.user_id', backref='user', lazy='dynamic'
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        self.password_changed_at = datetime.utcnow()

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_preferences(self):
        try:
            data = json.loads(self.preferences or '{}')
            if isinstance(data, dict):
                return data
        except (TypeError, ValueError):
            pass
        return {}

    def set_preference(self, key, value):
        prefs = self.get_preferences()
        prefs[key] = value
        self.preferences = json.dumps(prefs, ensure_ascii=False)

    def get_preference(self, key, default=None):
        return self.get_preferences().get(key, default)

    def theme_style(self):
        prefs = self.get_preferences()
        theme = prefs.get('theme', 'light')
        font_family = prefs.get('font_family', 'Segoe UI')
        accent = prefs.get('accent_color', '#2563eb')

        if theme == 'dark':
            bg = '#0b1220'
            surface = '#111827'
            card = '#172033'
            text = '#e5eefc'
            muted = '#9fb3d1'
            border = 'rgba(148, 163, 184, 0.22)'
        else:
            bg = '#f3f6fb'
            surface = '#ffffff'
            card = '#ffffff'
            text = '#0f172a'
            muted = '#475569'
            border = 'rgba(148, 163, 184, 0.18)'

        return (
            f"font-family: '{font_family}', sans-serif; "
            f"--app-bg: {bg}; --app-surface: {surface}; --app-card: {card}; "
            f"--app-text: {text}; --app-muted: {muted}; --app-border: {border}; "
            f"--app-accent: {accent}; --app-accent-soft: {accent}22;"
        )

    @classmethod
    def ensure_preferences_column(cls):
        try:
            db.session.execute(text('SELECT preferences FROM users LIMIT 1'))
        except Exception:
            db.session.execute(text('ALTER TABLE users ADD COLUMN preferences TEXT DEFAULT "{}"'))
            db.session.commit()

    @classmethod
    def ensure_auth_columns(cls):
        for column_name, column_sql in {
            'preferences': 'ALTER TABLE users ADD COLUMN preferences TEXT DEFAULT "{}"',
            'reset_token': 'ALTER TABLE users ADD COLUMN reset_token VARCHAR(255)',
            'reset_token_expires_at': 'ALTER TABLE users ADD COLUMN reset_token_expires_at DATETIME',
        }.items():
            try:
                db.session.execute(text(f'SELECT {column_name} FROM users LIMIT 1'))
            except Exception:
                db.session.execute(text(column_sql))
        db.session.commit()

    def generate_reset_token(self):
        self.reset_token = secrets.token_urlsafe(32)
        self.reset_token_expires_at = datetime.utcnow() + timedelta(hours=1)
        return self.reset_token

    def clear_reset_token(self):
        self.reset_token = None
        self.reset_token_expires_at = None

    def is_password_expired(self):
        if not self.password_changed_at:
            return True
        expiry = self.password_changed_at + timedelta(days=self.password_expiry_days)
        return datetime.utcnow() > expiry

    def has_role(self, role_code):
        return bool(self.role and self.role.code == role_code)

    def has_permission(self, flag_name):
        """Return True if the user's role grants the given permission flag."""
        return bool(self.role and getattr(self.role, flag_name, False))

    def can_access_procurement(self, procurement):
        if not procurement:
            return False

        if self.has_role('system_admin'):
            return True
        if self.has_role('procurement_oversight') or self.has_role('procurement_unit'):
            return True
        if self.has_role('accounting_officer'):
            try:
                estimated_value = float(procurement.estimated_value or 0)
            except (TypeError, ValueError):
                estimated_value = 0
            limit = float(self.delegation_limit or 0)
            return estimated_value <= limit
        if self.has_role('user_department'):
            procurement_entity = getattr(procurement, 'procurement_entity', None) or getattr(procurement, 'user_department', None)
            return procurement_entity == self.department
        return False

    def _totp_code(self):
        if not self.mfa_secret:
            return None
        key = base64.b32decode(self.mfa_secret + '=' * ((8 - len(self.mfa_secret) % 8) % 8), casefold=True)
        counter = int(time.time() // 30)
        msg = struct.pack('>Q', counter)
        digest = hmac.new(key, msg, hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        binary = ((digest[offset] & 0x7F) << 24) | ((digest[offset + 1] & 0xFF) << 16) | ((digest[offset + 2] & 0xFF) << 8) | (digest[offset + 3] & 0xFF)
        code = binary % 1_000_000
        return str(code).zfill(6)

    def generate_mfa_secret(self):
        secret = base64.b32encode(secrets.token_bytes(20)).decode('utf-8').rstrip('=')
        self.mfa_secret = secret
        self.mfa_enabled = True
        return secret

    def verify_mfa_code(self, code):
        if not self.mfa_secret or not code:
            return False
        expected = self._totp_code()
        if not expected:
            return False
        return str(code).strip() == expected

    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def __repr__(self):
        return f'<User {self.username}>'
