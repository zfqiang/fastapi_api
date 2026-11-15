from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from pwdlib import PasswordHash

from app.core.config import Settings

password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_hasher.verify(password, password_hash)


def create_token(
    *,
    subject: str,
    token_type: str,
    lifetime: timedelta,
    settings: Settings,
) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    token_id = str(uuid4())
    payload = {
        "sub": subject,
        "type": token_type,
        "jti": token_id,
        "iat": now,
        "exp": now + lifetime,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, token_id


def decode_token(token: str, settings: Settings) -> dict[str, object]:
    return jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "iat", "sub", "jti", "type"]},
    )
