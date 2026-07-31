import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-change-before-deployment'

    # Defaults to a local SQLite file so the project runs with zero external
    # setup. Point DATABASE_URL at Postgres for anything beyond a demo.
    # Uses `or` rather than get(key, default) so an empty DATABASE_URL= line
    # in .env (present but blank) still falls through to the SQLite default,
    # rather than handing Flask-SQLAlchemy an empty string as the URI.
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or f"sqlite:///{os.path.join(basedir, 'instance', 'ebms.db')}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or os.path.join(basedir, 'uploads')
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024 * 1024  # 2GB, matches SOAR NFR-003 default

    # AES key for sealed-bid encryption at rest (Fernet, base64 urlsafe 32-byte
    # key). Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    SUBMISSION_ENCRYPTION_KEY = os.environ.get('SUBMISSION_ENCRYPTION_KEY')

    OPENING_QUORUM = int(os.environ.get('OPENING_QUORUM') or 2)
    COOLING_OFF_DAYS = int(os.environ.get('COOLING_OFF_DAYS') or 10)

    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    # Email (optional). If MAIL_SERVER is blank, notifications are printed to
    # the console instead of sent, so the app runs without SMTP configured.
    MAIL_SERVER = os.environ.get('MAIL_SERVER', '')
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or 'no-reply@ebms.gov.bw'
