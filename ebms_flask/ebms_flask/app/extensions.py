# Shared extension instances. Kept in one module (rather than created inside
# __init__.py directly) so model files can `from app.extensions import db`
# without circular imports.
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()

login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please sign in to continue.'
login_manager.login_message_category = 'warning'
