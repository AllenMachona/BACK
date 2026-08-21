import os
from flask import Flask
from app.extensions import db, login_manager, migrate
from config import Config


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

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
        # CSP (Content-Security-Policy)
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' fonts.googleapis.com; font-src 'self' fonts.gstatic.com cdn.jsdelivr.net; img-src 'self' data: https:; connect-src 'self'"
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
        SiteSetting.ensure_defaults()
        from app.models.user import User
        User.ensure_auth_columns()
        from app.models.procurement import Procurement
        Procurement.ensure_schema_columns()
        from app.models.communication import Communication
        Communication.ensure_schema_columns()
        from app.models.message import Message
        Message.ensure_schema_columns()
        from app.models.role import Role
        if Role.query.count() == 0:
            try:
                import seed
                seed.seed_data()
            except Exception as e:
                app.logger.warning(f"Auto-seed notification: {e}")

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

    @app.context_processor
    def inject_globals():
        from datetime import datetime
        return {
            'now': datetime.utcnow(),
            'site_settings': SiteSetting.as_dict(),
        }

    return app
