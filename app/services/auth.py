from datetime import timedelta

from redis.asyncio import Redis

from app.core.config import Settings
from app.core.security import create_token


def refresh_key(token_id: str) -> str:
    return f"auth:refresh:{token_id}"


async def issue_token_pair(
    redis: Redis, user_id: int, settings: Settings
) -> dict[str, int | str]:
    access_seconds = settings.access_token_minutes * 60
    refresh_seconds = settings.refresh_token_days * 24 * 60 * 60
    access_token, _ = create_token(
        subject=str(user_id),
        token_type="access",
        lifetime=timedelta(seconds=access_seconds),
        settings=settings,
    )
    refresh_token, refresh_id = create_token(
        subject=str(user_id),
        token_type="refresh",
        lifetime=timedelta(seconds=refresh_seconds),
        settings=settings,
    )
    await redis.set(
        refresh_key(refresh_id), str(user_id), ex=refresh_seconds
    )
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": access_seconds,
        "refresh_expires_in": refresh_seconds,
    }


async def consume_refresh_token(
    redis: Redis, token_id: str, user_id: int
) -> bool:
    script = """
    if redis.call('GET', KEYS[1]) == ARGV[1] then
        return redis.call('DEL', KEYS[1])
    end
    return 0
    """
    return bool(await redis.eval(script, 1, refresh_key(token_id), str(user_id)))
