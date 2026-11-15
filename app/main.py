import math
import time
from contextlib import asynccontextmanager
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1 import auth, health, home, users
from app.core.config import Settings, settings
from app.core.logging import configure_logging
from app.services.rate_limit import consume_request

logger = structlog.get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id")
        if not request_id or len(request_id) > 128:
            request_id = str(uuid4())
        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            logger.info(
                "request_completed",
                status_code=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            structlog.contextvars.clear_contextvars()


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        excluded_paths = {
            "/health/live",
            "/health/ready",
            "/docs",
            "/redoc",
            "/openapi.json",
        }
        if request.url.path in excluded_paths:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        is_auth_route = request.url.path.startswith("/api/v1/auth/")
        config: Settings = request.app.state.settings
        limit = (
            config.auth_rate_limit_requests
            if is_auth_route
            else config.rate_limit_requests
        )
        key = f"rate:{client_ip}:{request.method}:{request.url.path}"
        try:
            count, ttl = await consume_request(
                request.app.state.redis, key, config.rate_limit_window_seconds
            )
        except RedisError:
            logger.exception("rate_limit_backend_unavailable", client_ip=client_ip)
            return JSONResponse(
                status_code=503,
                content={"detail": "Rate limit service unavailable"},
            )

        if count > limit:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers={"Retry-After": str(max(1, math.ceil(ttl)))},
            )
        return await call_next(request)


def create_app(app_settings: Settings | None = None) -> FastAPI:
    configure_logging()
    active_settings = app_settings or settings

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = active_settings
        app.state.engine = create_async_engine(
            active_settings.database_url, pool_pre_ping=True
        )
        app.state.session_factory = async_sessionmaker(
            app.state.engine, expire_on_commit=False
        )
        app.state.redis = Redis.from_url(
            active_settings.redis_url, encoding="utf-8", decode_responses=True
        )
        try:
            yield
        finally:
            await app.state.redis.aclose()
            await app.state.engine.dispose()

    app = FastAPI(title=active_settings.app_name, lifespan=lifespan)
    app.state.settings = active_settings
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=active_settings.cors_origins,
        allow_credentials=active_settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(request: Request, exc: SQLAlchemyError):
        logger.exception("database_operation_failed", path=request.url.path)
        return JSONResponse(
            status_code=503, content={"detail": "Database service unavailable"}
        )

    @app.exception_handler(RedisError)
    async def redis_error_handler(request: Request, exc: RedisError):
        logger.exception("redis_operation_failed", path=request.url.path)
        return JSONResponse(
            status_code=503, content={"detail": "Redis service unavailable"}
        )

    @app.get("/", tags=["root"])
    async def root() -> dict[str, str]:
        return {"service": active_settings.app_name, "docs": "/docs"}

    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(users.router, prefix="/api/v1")
    app.include_router(home.router, prefix="/api/v1")
    app.include_router(health.router)
    return app


app = create_app()
