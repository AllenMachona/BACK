"""Encryption at rest for sealed bid submissions (SOAR 7.7, 8.2).

Uses Fernet (AES-128-CBC + HMAC, from the `cryptography` package) rather than
hand-rolled AES so we get authenticated encryption without re-implementing
padding/IV handling ourselves. The key never reaches the browser and is only
read from the environment on the server.
"""
import hashlib
from cryptography.fernet import Fernet
from flask import current_app


def _fernet():
    key = current_app.config.get('SUBMISSION_ENCRYPTION_KEY')
    if not key:
        raise RuntimeError(
            'SUBMISSION_ENCRYPTION_KEY is not configured. Generate one with: '
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_bytes(plaintext: bytes) -> bytes:
    return _fernet().encrypt(plaintext)


def decrypt_bytes(ciphertext: bytes) -> bytes:
    return _fernet().decrypt(ciphertext)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
