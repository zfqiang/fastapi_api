import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import RedisClient

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def readiness(request: Request, redis: RedisClient) -> JSONResponse:
    async def check_database() -> bool:
        try:
            async with request.app.state.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            return True
        except SQLAlchemyError:
            return False

    async def check_redis() -> bool:
        try:
            return bool(await redis.ping())
        except RedisError:
            return False

    database_ok, redis_ok = await asyncio.gather(check_database(), check_redis())
    status_code = 200 if database_ok and redis_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ok" if status_code == 200 else "not_ready",
            "checks": {"database": database_ok, "redis": redis_ok},
        },
    )
