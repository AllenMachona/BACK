import os
from datetime import datetime
from flask import g
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
            'app_name': ('Application Name', os.environ.get('APP_NAME') or 'EBMS Botswana', 'Name shown in the portal header.'),
            'app_tagline': ('Tagline', os.environ.get('APP_TAGLINE') or 'Secure Procurement and Bid Management', 'Short description shown on public pages.'),
            'system_description': ('System Description', 'Secure Procurement and Bid Management', 'Description used in public portal metadata.'),
            'support_email': ('Support Email', os.environ.get('SUPPORT_EMAIL') or 'support@your-domain.example', 'Address users should contact for support.'),
            'support_phone': ('Support Phone', os.environ.get('SUPPORT_PHONE') or '+267 000 0000', 'Support telephone number shown to users.'),
            'contact_address': ('Address', os.environ.get('CONTACT_ADDRESS') or 'Your office address', 'Organisation address shown on public pages.'),
            'website_url': ('Website URL', '', 'Public organisation website.'),
            'default_country': ('Country', os.environ.get('DEFAULT_COUNTRY') or 'Botswana', 'Default country for public-facing content.'),
            'default_timezone': ('Default Timezone', 'Africa/Gaborone', 'Timezone used for displayed dates.'),
            'currency': ('Currency', 'BWP', 'Currency label used for procurement values.'),
            'date_format': ('Date Format', '%d %b %Y', 'Display format for dates.'),
            'time_format': ('Time Format', '%H:%M', 'Display format for times.'),
            'portal_primary_color': ('Portal Primary Colour', '#0f766e', 'Primary accent colour used across the public portal.'),
            'portal_secondary_color': ('Portal Secondary Colour', '#1f2937', 'Secondary accent colour used in headings and cards.'),
            'public_home_title': ('Public Home Title', 'EBMS Procurement Portal', 'Header title shown on the public landing page.'),
            'public_home_intro': ('Public Home Intro', 'Transparent procurement for public-sector delivery.', 'Intro copy for the public landing page.'),
            'maintenance_mode': ('Maintenance Mode', 'false', 'Blocks public and non-administrator access while maintenance is in progress.'),
            'maintenance_message': ('Maintenance Message', 'The system is temporarily undergoing maintenance. Please try again later.', 'Message shown during maintenance mode.'),
            'allow_registration': ('Allow Registration', 'true', 'Controls whether new bidder registrations are accepted.'),
            'enable_supplier_registration': ('Enable Supplier Registration', 'true', 'Feature flag for public supplier registration.'),
            'supplier_approval_required': ('Supplier Approval Required', 'true', 'Require administrator approval before bidder access is activated.'),
            'supplier_verification_required': ('Supplier Verification Required', 'true', 'Require email and compliance verification for suppliers.'),
            'required_supplier_documents': ('Required Supplier Documents', 'compliance_document', 'Comma-separated documents required at supplier registration.'),
            'supplier_categories': ('Supplier Categories', 'goods,works,consultancy,non_consultancy', 'Comma-separated supplier categories.'),
            'deadline_reminder_days': ('Reminder Days', '3', 'Days before a deadline when reminder notifications are sent.'),
            'direct_procurement_threshold': ('Direct Procurement Threshold', '500000', 'Maximum value allowed for direct procurement.'),
            'open_procurement_threshold': ('Open Procurement Threshold', '500000', 'Value threshold used for open procurement governance.'),
            'lot_splitting_warning_threshold': ('Lot Splitting Warning Threshold', '500000', 'Value at which lot-splitting risks require review.'),
            'enabled_procurement_methods': ('Enabled Procurement Methods', 'open_domestic,open_international,restricted,rfq,direct,rfp', 'Comma-separated methods available when creating procurements.'),
            'required_procurement_documents': ('Required Procurement Documents', 'advertisement', 'Comma-separated document types required before publication.'),
            'default_procurement_status': ('Default Procurement Status', 'draft', 'Initial status for newly created procurements.'),
            'approval_levels': ('Approval Levels', '1', 'Number of approval levels required for configured workflows.'),
            'tender_number_prefix': ('Tender Number Prefix', 'TB', 'Prefix used for generated tender numbers.'),
            'bid_submission_deadline_min_hours': ('Minimum Bid Deadline (Hours)', '24', 'Minimum time allowed between publication and bid deadline.'),
            'workflow_rejection_behaviour': ('Workflow Rejection Behaviour', 'return_for_correction', 'Behaviour after a workflow rejection.'),
            'workflow_escalation_days': ('Workflow Escalation Days', '3', 'Days before an outstanding approval is escalated.'),
            'request_statuses': ('Request Statuses', 'draft,submitted,under_review,converted,rejected', 'Allowed internal lifecycle states for procurement requests.'),
            'request_categories': ('Request Categories', 'works,services,consultancy,supplies,combination', 'Comma-separated categories used in request forms.'),
            'request_methods': ('Request Methods', 'open_domestic,open_international,restricted,rfq,direct,rfp', 'Comma-separated procurement methods used in request forms.'),
            'request_document_extensions': ('Request Document Extensions', 'pdf,doc,docx,xls,xlsx', 'Comma-separated signed document extensions accepted for requests.'),
            'request_document_max_mb': ('Request Document Max MB', '25', 'Maximum size of each uploaded signed request document.'),
            'allowed_document_extensions': ('Allowed Document Extensions', 'pdf,doc,docx,xls,xlsx,png,jpg,jpeg', 'Comma-separated upload extensions accepted by the platform.'),
            'max_upload_size_mb': ('Maximum Upload Size (MB)', '2048', 'Maximum size of any uploaded file.'),
            'session_lifetime_hours': ('Session Lifetime (Hours)', '8', 'How long users may remain signed in.'),
            'login_max_attempts': ('Login Attempts Before Lock', '5', 'Failed attempts before an account is temporarily locked.'),
            'login_lockout_minutes': ('Login Lockout (Minutes)', '15', 'Duration of a temporary login lockout.'),
            'password_expiry_days': ('Password Expiry (Days)', '90', 'Maximum age of user passwords.'),
            'minimum_password_length': ('Minimum Password Length', '10', 'Minimum characters required for passwords.'),
            'require_password_uppercase': ('Require Uppercase', 'true', 'Require an uppercase character in passwords.'),
            'require_password_number': ('Require Number', 'true', 'Require a number in passwords.'),
            'require_password_special': ('Require Special Character', 'true', 'Require a special character in passwords.'),
            'document_retention_days': ('Document Retention (Days)', '3650', 'Retention policy reference for document maintenance.'),
            'file_naming_rule': ('File Naming Rule', 'safe_unique', 'Safe naming policy for uploaded files.'),
            'smtp_host': ('SMTP Host', os.environ.get('MAIL_SERVER') or 'smtp.gmail.com', 'SMTP host override; password remains in deployment secrets.'),
            'smtp_port': ('SMTP Port', os.environ.get('MAIL_PORT') or '587', 'SMTP port override.'),
            'email_sender_name': ('Email Sender Name', 'EBMS Botswana', 'Display name used in system emails.'),
            'sender_email': ('Sender Email', os.environ.get('MAIL_DEFAULT_SENDER') or '', 'Verified sender email address; SMTP password remains a deployment secret.'),
            'email_encryption': ('Email Encryption', 'tls', 'SMTP encryption mode: none, tls, or ssl.'),
            'enable_email': ('Enable Email Notifications', 'true', 'Enable outgoing email notifications.'),
            'enable_system_notifications': ('Enable System Notifications', 'true', 'Enable in-application notifications.'),
            'enable_notifications': ('Enable Notifications', 'true', 'Feature flag for in-app and email notification workflows.'),
            'notification_frequency': ('Notification Frequency', 'immediate', 'Notification frequency: immediate or digest.'),
            'notification_retention_days': ('Notification Retention (Days)', '365', 'Age after which old read notifications may be removed.'),
            'email_template_account_approved': ('Approved Account Email', 'Your EBMS Botswana bidder account has been activated.', 'Body text for account approval emails.'),
            'email_template_account_rejected': ('Rejected Account Email', 'Your EBMS Botswana bidder account was rejected.', 'Body text for account rejection emails.'),
            'enable_bid_submission': ('Enable Bid Submission', 'true', 'Feature flag for bidder submissions.'),
            'enable_audit_log': ('Enable Audit Log', 'true', 'Audit logging is mandatory and cannot be disabled by the GUI.'),
            'audit_log_retention_days': ('Audit Log Retention (Days)', '3650', 'How long audit records are retained before review or cleanup.'),
            'default_bidder_status': ('Default Bidder Status', 'pending', 'Default approval state assigned to new bidder records.'),
            'require_bidder_document_review': ('Require Bidder Document Review', 'true', 'Require compliance review for newly registered bidders before activation.'),
            'default_public_entity_status': ('Default Public Entity Status', 'active', 'Default status for public entities on the portal.'),
            'show_financial_year_in_portal': ('Show Financial Year in Portal', 'true', 'Display financial year labels on public procurement and plan pages.'),
        }

        for key, (label, value, description) in defaults.items():
            setting = cls.query.filter_by(key=key).first()
            if not setting:
                db.session.add(cls(key=key, value=value, label=label, description=description))
            elif not setting.description or setting.description == 'System default setting':
                setting.description = description
        db.session.commit()

    @classmethod
    def as_dict(cls):
        try:
            cached = getattr(g, '_site_settings', None)
            if cached is not None:
                return cached
        except RuntimeError:
            cached = None
        try:
            cached = {setting.key: setting.value for setting in cls.query.all()}
            try:
                g._site_settings = cached
            except RuntimeError:
                pass
            return cached
        except (OperationalError, ProgrammingError, RuntimeError):
            return {}

    @classmethod
    def get(cls, key, default=''):
        try:
            cached = getattr(g, '_site_settings', None)
            if cached is not None:
                return cached.get(key, default)
        except RuntimeError:
            cached = None
        try:
            item = cls.query.filter_by(key=key).first()
            return item.value if item else default
        except (OperationalError, ProgrammingError, RuntimeError):
            return default

    def __repr__(self):
        return f'<SiteSetting {self.key}>'
