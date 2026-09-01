import os
from datetime import datetime, timedelta
from flask import Flask, request, render_template, redirect, url_for
from flask_login import current_user
from app.extensions import db, login_manager, migrate
from config import Config


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    if not app.config.get('MAIL_CONFIGURED'):
        app.logger.warning(
            'SMTP email is disabled: set MAIL_SERVER and MAIL_DEFAULT_SENDER in the project .env file.'
        )

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(app.config['UPLOAD_FOLDER']), 'instance'), exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    # SECURITY: Add security headers
    @app.after_request
    def set_security_headers(response):
        # Prevent clickjacking
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        # Prevent MIME sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # Enable XSS protection
        response.headers['X-XSS-Protection'] = '1; mode=block'
        # Referrer policy
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        # Feature policy
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        # HSTS (Strict-Transport-Security) - only in production
        if not app.debug:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        # CSP (Content-Security-Policy).
        # Icons (Bootstrap Icons) are self-hosted under /static/vendor so "self" covers
        # their CSS + woff/woff2 fonts — the previous jsDelivr CDN link was blocked here
        # because style-src did not allow cdn.jsdelivr.net, which made every icon render
        # as an empty box. Google Fonts are still allowed for the public/auth pages.
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' fonts.googleapis.com; font-src 'self' fonts.gstatic.com; img-src 'self' data: https:; connect-src 'self'"
        return response

    
    # SECURITY: Enforce HTTPS in production
    if not app.debug and app.config.get('REQUIRE_HTTPS', True):
        @app.before_request
        def force_https():
            from flask import request, redirect
            if request.headers.get('X-Forwarded-Proto', 'http') == 'http':
                return redirect(request.url.replace('http://', 'https://', 1), code=301)

    # Import models here (not at module top) so they register with SQLAlchemy
    # only once the app + db are both initialized — avoids circular imports.
    from app import models  # noqa: F401
    from app.models.site_setting import SiteSetting

    with app.app_context():
        db.create_all()
        from app.models.evaluator_assignment import EvaluatorAssignment
        EvaluatorAssignment.__table__.create(db.engine, checkfirst=True)
        from app.models.evaluator_feedback import EvaluatorFeedback
        EvaluatorFeedback.__table__.create(db.engine, checkfirst=True)
        from app.models.budget_entry import BudgetEntry
        BudgetEntry.__table__.create(db.engine, checkfirst=True)
        from app.models.bidder_performance import BidderPerformance
        BidderPerformance.__table__.create(db.engine, checkfirst=True)
        SiteSetting.ensure_defaults()
        app.config['MAX_CONTENT_LENGTH'] = int(float(SiteSetting.get('max_upload_size_mb', '2048'))) * 1024 * 1024
        app.permanent_session_lifetime = timedelta(hours=int(float(SiteSetting.get('session_lifetime_hours', '8'))))
        app.config['MAIL_SERVER'] = SiteSetting.get('smtp_host', app.config.get('MAIL_SERVER', ''))
        app.config['MAIL_PORT'] = int(float(SiteSetting.get('smtp_port', str(app.config.get('MAIL_PORT', 587)))))
        app.config['MAIL_DEFAULT_SENDER'] = SiteSetting.get('sender_email', '') or app.config.get('MAIL_DEFAULT_SENDER', '')
        encryption = SiteSetting.get('email_encryption', 'tls')
        app.config['MAIL_USE_TLS'] = encryption == 'tls'
        app.config['MAIL_USE_SSL'] = encryption == 'ssl'
        app.config['MAIL_CONFIGURED'] = bool(app.config['MAIL_SERVER'] and app.config.get('MAIL_DEFAULT_SENDER'))
        from app.models.user import User
        User.ensure_auth_columns()
        from app.models.procurement import Procurement
        Procurement.ensure_schema_columns()
        from app.models.procurement_plan import ProcurementPlanItem
        ProcurementPlanItem.ensure_schema_columns()
        from app.models.award import Award
        Award.ensure_schema_columns()
        from app.models.communication import Communication
        Communication.ensure_schema_columns()
        from app.models.message import Message
        Message.ensure_schema_columns()
        from app.models.request import ensure_schema_columns
        ensure_schema_columns()
        from app.models.role import Role
        from app.models.user import User
        Role.ensure_default_roles()

        def ensure_default_login_users():
            from app.models.bidder import Bidder

            default_password = 'ChangeMe123!'
            role_map = {role.code: role for role in Role.query.all()}
            default_users = [
                ('admin', 'admin@pe.gov.bw', 'System', 'Administrator', 'system_admin', 'ICT'),
                ('d.tlou', 'd.tlou@pe.gov.bw', 'David', 'Tlou', 'procurement_unit', 'Procurement'),
                ('j.molefe', 'j.molefe@pe.gov.bw', 'John', 'Molefe', 'accounting_officer', 'Head Office'),
                ('n.kgosi', 'n.kgosi@pe.gov.bw', 'Naledi', 'Kgosi', 'evaluator', 'Engineering'),
                ('t.mmutle', 't.mmutle@health.gov.bw', 'Thabo', 'Mmutle', 'requester', 'Ministry of Health'),
                ('a.seretse', 'a.seretse@moe.gov.bw', 'Ame', 'Seretse', 'requester', 'Ministry of Education'),
                ('bidder1', 'bids@mokwenaconstruction.co.bw', 'Karabo', 'Mokwena', 'bidder', 'Construction'),
            ]

            for username, email, first_name, last_name, role_code, department in default_users:
                if role_code not in role_map:
                    continue
                user = User.query.filter_by(username=username).first()
                if not user:
                    user = User(
                        username=username,
                        email=email,
                        first_name=first_name,
                        last_name=last_name,
                        role_id=role_map[role_code].id,
                        department=department,
                        is_active=True,
                    )
                    db.session.add(user)
                user.email = email
                user.first_name = first_name
                user.last_name = last_name
                user.role_id = role_map[role_code].id
                user.department = department
                user.is_active = True
                user.failed_login_attempts = 0
                user.locked_until = None
                user.set_password(default_password)
                if role_code == 'bidder':
                    if not user.bidder_id:
                        bidder = Bidder.query.filter_by(contact_email=user.email).first()
                        if not bidder:
                            bidder = Bidder(
                                company_name=department,
                                contact_email=user.email,
                                active=True,
                                verified=True,
                            )
                            db.session.add(bidder)
                            db.session.flush()
                        user.bidder_id = bidder.id
                    user.email_confirmed_at = datetime.utcnow()
                    user.email_confirmation_token = None
                    user.email_confirmation_expires_at = None
            db.session.commit()

        ensure_default_login_users()

        has_system_admin = bool(
            User.query.join(Role, User.role_id == Role.id)
            .filter(Role.code == 'system_admin')
            .first()
        )
        if User.query.count() == 0 or not has_system_admin:
            try:
                import seed
                seed.seed_data()
            except Exception as e:
                app.logger.warning(f"Auto-seed notification: {e}")

    @app.before_request
    def enforce_maintenance_mode():
        if SiteSetting.get('maintenance_mode', 'false').lower() != 'true':
            return None
        if current_user.is_authenticated and current_user.has_role('system_admin'):
            return None
        if request.endpoint in {'auth.login', 'auth.logout', 'static'}:
            return None
        return render_template(
            'maintenance.html',
            message=SiteSetting.get('maintenance_message', 'The system is temporarily undergoing maintenance.'),
        ), 503

    @app.before_request
    def restrict_admin_procurement_access():
        """Keep system administrators out of operational procurement workflows, except the global search."""
        if not current_user.is_authenticated or not current_user.has_role('system_admin'):
            return None
        endpoint = request.endpoint or ''
        allowed_endpoints = {'procurements.search'}
        blocked_prefixes = ('procurements.', 'requests.', 'bidders.', 'evaluations.')
        blocked_endpoints = {
            'dashboard.dashboard', 'dashboard.public_tenders',
            'dashboard.public_tender_detail', 'dashboard.public_procurement_plans',
            'dashboard.manage_procurement_plans', 'dashboard.edit_procurement_plan',
        }
        if endpoint in allowed_endpoints:
            return None
        if endpoint.startswith(blocked_prefixes) or endpoint in blocked_endpoints:
            return redirect(url_for('reports.index'))
        return None

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.procurements import procurements_bp
    from app.routes.evaluations import evaluations_bp
    from app.routes.bidders import bidders_bp
    from app.routes.admin import admin_bp
    from app.routes.reports import reports_bp
    from app.routes.notifications import notifications_bp
    from app.routes.messages import messages_bp
    from app.routes.clarifications import clarifications_bp
    from app.routes.requests import requests_bp
    from app.routes.evaluator_assignments import evaluator_assignments_bp
    from app.models.site_setting import SiteSetting

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(procurements_bp)
    app.register_blueprint(evaluations_bp)
    app.register_blueprint(bidders_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(clarifications_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(evaluator_assignments_bp)

    @app.context_processor
    def inject_globals():
        from datetime import datetime
        from app.models.request import FormDRequest, FormERequest, FormDERequest
        pending_statuses = ('submitted', 'under_review')
        incoming_requests_count = sum(
            model.query.filter(model.status.in_(pending_statuses)).count()
            for model in (FormDRequest, FormERequest, FormDERequest)
        )
        return {
            'now': datetime.utcnow(),
            'site_settings': SiteSetting.as_dict(),
            'incoming_requests_count': incoming_requests_count,
        }

    return app
