import os
from cryptography.fernet import Fernet
from config.settings import settings

def _fernet():
    key = settings.api_secret_encryption_key.strip()
    if not key:
        raise RuntimeError("API_SECRET_ENCRYPTION_KEY is not configured")
    return Fernet(key.encode("ascii"))

def encrypt_partner_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode("utf-8")).decode("ascii")
