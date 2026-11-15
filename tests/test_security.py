from datetime import timedelta

from app.core.config import Settings
from app.core.security import create_token, decode_token, hash_password, verify_password


def test_password_hash_and_verification() -> None:
    password = "correct horse battery staple"
    password_hash = hash_password(password)

    assert password_hash != password
    assert verify_password(password, password_hash)
    assert not verify_password("incorrect password", password_hash)


def test_token_contains_required_claims_and_round_trips() -> None:
    config = Settings(secret_key="test-secret-key-with-at-least-32-characters")
    token, token_id = create_token(
        subject="42",
        token_type="access",
        lifetime=timedelta(minutes=5),
        settings=config,
    )

    claims = decode_token(token, config)

    assert claims["sub"] == "42"
    assert claims["type"] == "access"
    assert claims["jti"] == token_id
