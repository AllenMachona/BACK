import os
import secrets
from datetime import timedelta

from cryptography.fernet import Fernet
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))


def _is_production():
    return os.environ.get('APP_ENV', os.environ.get('FLASK_ENV', 'development')).lower() == 'production'


def _required_env(name, dev_default=None):
    value = os.environ.get(name)
    if value and value.strip():
        return value
    if _is_production():
        raise RuntimeError(f"Missing required environment variable: {name}. Set it in the environment or .env before starting the app.")
    if dev_default is not None:
        return dev_default
    return ''


def _development_submission_key():
    """Keep the local encryption key stable across development restarts."""
    key_path = os.path.join(basedir, 'instance', 'submission_encryption.key')
    os.makedirs(os.path.dirname(key_path), exist_ok=True)

    try:
        with open(key_path, 'r', encoding='ascii') as key_file:
            key = key_file.read().strip()
        Fernet(key)
        return key
    except (FileNotFoundError, ValueError):
        key = Fernet.generate_key().decode('ascii')
        with open(key_path, 'w', encoding='ascii') as key_file:
            key_file.write(key)
        return key


if _is_production():
    SECRET_KEY = _required_env('SECRET_KEY')
    SUBMISSION_ENCRYPTION_KEY = _required_env('SUBMISSION_ENCRYPTION_KEY')
else:
    SECRET_KEY = _required_env('SECRET_KEY', secrets.token_hex(32))
    SUBMISSION_ENCRYPTION_KEY = _required_env('SUBMISSION_ENCRYPTION_KEY', _development_submission_key())


class Config:
    SECRET_KEY = SECRET_KEY
    APP_ENV = os.environ.get('APP_ENV', os.environ.get('FLASK_ENV', 'development')).lower()

    # SQL Server is the active local development database after migration.
    # The original SQLite URI remains available for rollback/testing.
    # Uses `or` rather than get(key, default) so an empty DATABASE_URL= line
    # in .env (present but blank) still falls through to the SQLite default,
    # rather than handing Flask-SQLAlchemy an empty string as the URI.
    SQLITE_DATABASE_URI = f"sqlite:///{os.path.join(basedir, 'instance', 'ebms.db')}"
    SQLSERVER_DATABASE_URI = os.environ.get(
        'SQLSERVER_DATABASE_URL',
        'mssql+pyodbc:///?odbc_connect='
        'DRIVER%3D%7BODBC%2BDriver%2B17%2Bfor%2BSQL%2BServer%7D%3B'
        'SERVER%3Dlocalhost%255CSQLEXPRESS%3BDATABASE%3DProcurementDB%3B'
        'Trusted_Connection%3Dyes%3BTrustServerCertificate%3Dyes',
    )
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or SQLSERVER_DATABASE_URI
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or os.path.join(basedir, 'uploads')
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024 * 1024  # 2GB, matches SOAR NFR-003 default

    # AES key for sealed-bid encryption at rest (Fernet, base64 urlsafe 32-byte
    # key). Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    SUBMISSION_ENCRYPTION_KEY = SUBMISSION_ENCRYPTION_KEY

    OPENING_QUORUM = int(os.environ.get('OPENING_QUORUM') or 2)
    COOLING_OFF_DAYS = int(os.environ.get('COOLING_OFF_DAYS') or 10)
    REQUIRE_HTTPS = os.environ.get('REQUIRE_HTTPS', 'false').lower() in {'1', 'true', 'yes', 'on'}

    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    # SMTP email settings. MAIL_USERNAME and MAIL_PASSWORD may be empty for a
    # trusted unauthenticated relay, but server and sender are always required
    # for real delivery.
    MAIL_SERVER = os.environ.get('MAIL_SERVER', '').strip()
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() in {'1', 'true', 'yes', 'on'}
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'false').lower() in {'1', 'true', 'yes', 'on'}
    MAIL_TIMEOUT = int(os.environ.get('MAIL_TIMEOUT') or 20)
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '').strip()
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', '').strip()
    MAIL_CONFIGURED = bool(MAIL_SERVER and MAIL_DEFAULT_SENDER)

    if APP_ENV == 'production' and not MAIL_CONFIGURED:
        raise RuntimeError('MAIL_SERVER and MAIL_DEFAULT_SENDER must be configured in production.')
