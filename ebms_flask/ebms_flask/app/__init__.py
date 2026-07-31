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

    # Import models here (not at module top) so they register with SQLAlchemy
    # only once the app + db are both initialized — avoids circular imports.
    from app import models  # noqa: F401

    from app.models.user import User

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

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(procurements_bp)
    app.register_blueprint(evaluations_bp)
    app.register_blueprint(bidders_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(notifications_bp)

    @app.context_processor
    def inject_globals():
        from datetime import datetime
        return {'now': datetime.utcnow()}

    return app
