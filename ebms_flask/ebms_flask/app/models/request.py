"""Request-to-procurement workflow models (Form D / Form E).

Form D is the *Procurement Requisition* — the user department's request and
authorization to procure. Form E is the *Specification & Budget Clearance* —
the technical specification and evidence that budget is available.

There are two families of request records:

- The legacy ``FormDRequest`` / ``FormERequest`` tables ask requesters to fill
  in procurement details themselves (title, category, method, value, budget).
- ``FormDERequest`` is the combined requisition used by the current workflow:
  the requester attaches the signed/certified Form D and Form E documents and
  adds a justification only — every procurement detail (title, category,
  method, value, tender documents, ...) is created by Procurement on the
  Procurement record, never inside the request.

The three models share a lifecycle + audit envelope (status, requester,
linked procurement, rejection metadata). ``FormDRequest`` and
``FormERequest`` carry genuinely different detail content, so they live in
separate tables. ``FormDERequest`` intentionally carries only the two uploaded
documents plus justification/department metadata.

Lifecycle: submitted -> under_review -> converted | rejected.
The linked ``procurement_id`` gives full traceability from request to the
Procurement record it produced (1:1).
"""
from datetime import datetime

from app.extensions import db
from flask import has_app_context
from sqlalchemy import text


def _status_list_from_settings():
    """Read request lifecycle states without assuming an app context exists."""
    default = 'draft,submitted,under_review,converted,rejected'
    try:
        from app.models.site_setting import SiteSetting
        if has_app_context():
            raw = SiteSetting.get('request_statuses', default)
            if raw:
                return str(raw)
    except Exception:
        pass
    return default


# Keep the status vocabulary centralized in the database while keeping a safe
# default for older databases / bootstrap environments.
REQUEST_STATUSES = [
    status.strip()
    for status in _status_list_from_settings().split(',')
    if status.strip()
]

FORM_TYPE_LABELS = {
    'form_d': 'Form D',
    'form_e': 'Form E',
}


def _ensure_columns(table_name, columns):
    """Upgrade request tables created by an earlier version of the workflow."""
    for column_name, column_sql in columns.items():
        try:
            probe = f'SELECT {column_name} FROM {table_name} LIMIT 1' if db.engine.name == 'sqlite' else f'SELECT TOP 1 {column_name} FROM {table_name}'
            db.session.execute(text(probe))
        except Exception:
            try:
                if db.engine.name != 'sqlite':
                    column_sql = column_sql.replace(' ADD COLUMN ', ' ADD ')
                db.session.execute(text(column_sql))
            except Exception:
                pass


def ensure_schema_columns():
    common_columns = {
        'submitted_by_id': 'INTEGER',
        'under_review_by_id': 'INTEGER',
        'under_review_at': 'DATETIME',
        'converted_by_id': 'INTEGER',
        'converted_at': 'DATETIME',
        'rejected_by_id': 'INTEGER',
        'rejected_at': 'DATETIME',
        'rejection_reason': 'TEXT',
        'updated_at': 'DATETIME',
    }
    for table_name in ('form_d_requests', 'form_e_requests'):
        columns = {name: f'ALTER TABLE {table_name} ADD COLUMN {name} {sql_type}'
                   for name, sql_type in common_columns.items()}
        _ensure_columns(table_name, columns)
    db.session.commit()


class FormDRequest(db.Model):
    """Procurement Requisition request (Form D)."""

    __tablename__ = 'form_d_requests'

    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    status = db.Column(db.String(30), default='submitted', index=True)

    # Form D — Requisition content (mapped onto Procurement on conversion)
    requisition_title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(30), nullable=False)  # works, services, consultancy, supplies, combination
    procurement_method = db.Column(db.String(30), nullable=False)  # open_domestic, rfq, direct, ...
    estimated_value = db.Column(db.Numeric(15, 2), nullable=False)
    procurement_entity = db.Column(db.String(200))
    justification = db.Column(db.Text)
    delivery_period = db.Column(db.String(100))
    authorized_by = db.Column(db.String(150))
    authorization_date = db.Column(db.Date)

    # Uploaded copy of the signed/scanned requisition document
    submitted_form_path = db.Column(db.String(500))
    submitted_form_filename = db.Column(db.String(300))

    # Traceability: the Procurement record this request eventually produced.
    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), index=True)

    # Review / conversion / rejection audit
    submitted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    under_review_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    under_review_at = db.Column(db.DateTime)
    converted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    converted_at = db.Column(db.DateTime)
    rejected_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    rejected_at = db.Column(db.DateTime)
    rejection_reason = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Explicit foreign_keys on every user link because this table has several
    # separate columns pointing at users (requester conversion/rejection links).
    requester = db.relationship('User', foreign_keys=[requester_id],
                                backref=db.backref('form_d_requests', lazy='dynamic'))
    submitted_by = db.relationship('User', foreign_keys=[submitted_by_id])
    under_review_by = db.relationship('User', foreign_keys=[under_review_by_id])
    converted_by = db.relationship('User', foreign_keys=[converted_by_id])
    rejected_by = db.relationship('User', foreign_keys=[rejected_by_id])
    procurement = db.relationship('Procurement', backref=db.backref('form_d_requests', lazy='dynamic'))

    form_type = 'form_d'
    form_type_label = 'Form D'

    def has_signed_document(self):
        return bool(self.submitted_form_path and self.submitted_form_filename)

    def status_label(self):
        return self.status.replace('_', ' ').title()

    @property
    def title(self):
        return self.requisition_title

    def __repr__(self):
        return f'<FormDRequest {self.id} status={self.status}>'
class FormERequest(db.Model):
    """Specification & Budget Clearance request (Form E)."""

    __tablename__ = 'form_e_requests'

    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    status = db.Column(db.String(30), default='submitted', index=True)

    # Form E — Specification & Budget Clearance content
    specification_title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(30), nullable=False)
    technical_specification = db.Column(db.Text, nullable=False)
    budget_line = db.Column(db.String(100))
    budget_allocated = db.Column(db.Numeric(15, 2), nullable=False)
    budget_status = db.Column(db.String(30), default='available')  # available, insufficient
    procurement_entity = db.Column(db.String(200))
    clearance_authority = db.Column(db.String(150))
    clearance_date = db.Column(db.Date)

    # Uploaded copy of the signed/scanned form E document
    submitted_form_path = db.Column(db.String(500))
    submitted_form_filename = db.Column(db.String(300))

    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), index=True)

    submitted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    under_review_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    under_review_at = db.Column(db.DateTime)
    converted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    converted_at = db.Column(db.DateTime)
    rejected_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    rejected_at = db.Column(db.DateTime)
    rejection_reason = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    requester = db.relationship('User', foreign_keys=[requester_id],
                                backref=db.backref('form_e_requests', lazy='dynamic'))
    submitted_by = db.relationship('User', foreign_keys=[submitted_by_id])
    under_review_by = db.relationship('User', foreign_keys=[under_review_by_id])
    converted_by = db.relationship('User', foreign_keys=[converted_by_id])
    rejected_by = db.relationship('User', foreign_keys=[rejected_by_id])
    procurement = db.relationship('Procurement', backref=db.backref('form_e_requests', lazy='dynamic'))

    form_type = 'form_e'
    form_type_label = 'Form E'

    def has_signed_document(self):
        return bool(self.submitted_form_path and self.submitted_form_filename)

    def status_label(self):
        return self.status.replace('_', ' ').title()

    @property
    def title(self):
        return self.specification_title

    def __repr__(self):
        return f'<FormERequest {self.id} status={self.status}>'


class FormDERequest(db.Model):
    """Combined Form D & Form E procurement request (current requester workflow).

    The requester attaches the signed/certified Form D (Procurement
    Requisition) and Form E (Specification & Budget Clearance) documents in a
    single submission, together with a departmental justification. Procurement
    details (title, category, method, estimated value, budget, tender
    documents) are deliberately *not* captured here — the Procurement Unit
    enters all of those on the linked ``procurement`` record.
    """

    __tablename__ = 'form_de_requests'

    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    status = db.Column(db.String(30), default='submitted', index=True)

    # Requesting department (read from the requester's profile) + justification
    department = db.Column(db.String(200))
    justification = db.Column(db.Text)

    # Uploaded signed/certified copies — stored internally, never exposed to bidders.
    form_d_file_path = db.Column(db.String(500))
    form_d_filename = db.Column(db.String(300))
    form_e_file_path = db.Column(db.String(500))
    form_e_filename = db.Column(db.String(300))

    procurement_id = db.Column(db.Integer, db.ForeignKey('procurements.id'), index=True)

    submitted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    under_review_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    under_review_at = db.Column(db.DateTime)
    converted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    converted_at = db.Column(db.DateTime)
    rejected_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    rejected_at = db.Column(db.DateTime)
    rejection_reason = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    requester = db.relationship('User', foreign_keys=[requester_id],
                                backref=db.backref('form_de_requests', lazy='dynamic'))
    submitted_by = db.relationship('User', foreign_keys=[submitted_by_id])
    under_review_by = db.relationship('User', foreign_keys=[under_review_by_id])
    converted_by = db.relationship('User', foreign_keys=[converted_by_id])
    rejected_by = db.relationship('User', foreign_keys=[rejected_by_id])
    procurement = db.relationship('Procurement', backref=db.backref('form_de_requests', lazy='dynamic'))

    form_type = 'de'
    form_type_label = 'Form D & E'

    def has_form_d(self):
        return bool(self.form_d_file_path and self.form_d_filename)

    def has_form_e(self):
        return bool(self.form_e_file_path and self.form_e_filename)

    def has_signed_document(self):
        return self.has_form_d() and self.has_form_e()

    def status_label(self):
        return self.status.replace('_', ' ').title()

    @property
    def title(self):
        return 'Procurement Request'

    def __repr__(self):
        return f'<FormDERequest {self.id} status={self.status}>'