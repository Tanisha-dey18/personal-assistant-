"""Password hashing, JWTs and field-level encryption for sensitive data."""
import base64
import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_token(subject: str, purpose: str = "access", minutes: int | None = None, extra: dict | None = None) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "purpose": purpose, "exp": exp, **(extra or {})}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str, purpose: str = "access") -> dict | None:
    try:
        data = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if data.get("purpose") != purpose:
        return None
    return data


def _fernet() -> Fernet:
    key = settings.ENCRYPTION_KEY
    if not key:
        # Derive a stable key from SECRET_KEY so dev setups work out of the box.
        key = base64.urlsafe_b64encode(hashlib.sha256(("astra-enc:" + settings.SECRET_KEY).encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return "[unable to decrypt — encryption key changed]"
