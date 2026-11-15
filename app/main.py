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
        # 从请求头中获取请求ID，如果不存在或超过128字符长度，则生成一个新的UUID
        request_id = request.headers.get("x-request-id")
        if not request_id or len(request_id) > 128:
            request_id = str(uuid4())
        # 将请求ID存储到请求状态中
        request.state.request_id = request_id
        # 清除结构化日志的上下文变量，并绑定新的请求相关信息
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        # 记录请求开始时间
        started = time.perf_counter()
        status_code = 500
        try:
            # 调用下一个中间件或路由处理函数
            response = await call_next(request)
            # 获取响应状态码
            status_code = response.status_code
            # 在响应头中添加请求ID
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            # 记录请求完成日志，包括状态码和持续时间（毫秒）
            logger.info(
                "request_completed",
                status_code=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            # 清除结构化日志的上下文变量
            structlog.contextvars.clear_contextvars()


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 定义不需要进行速率限制的路径集合
        excluded_paths = {
            "/health/live",  # 健康检查存活端点
            "/health/ready",  # 健康检查就绪端点
            "/docs",  # Swagger UI 文档
            "/redoc",  # ReDoc 文档
            "/openapi.json",  # OpenAPI 规范文件
        }
        # 如果请求路径在排除列表中，直接放行
        if request.url.path in excluded_paths:
            return await call_next(request)

        # 获取客户端IP地址，如果无法获取则标记为"unknown"
        client_ip = request.client.host if request.client else "unknown"
        # 判断是否为认证相关路由
        is_auth_route = request.url.path.startswith("/api/v1/auth/")
        # 从应用状态中获取配置对象
        config: Settings = request.app.state.settings
        # 根据路由类型设置不同的速率限制值
        limit = (
            config.auth_rate_limit_requests  # 认证路由的速率限制
            if is_auth_route
            else config.rate_limit_requests  # 其他路由的速率限制
        )
        # 构建Redis键，包含IP、方法和路径信息
        key = f"rate:{client_ip}:{request.method}:{request.url.path}"
        try:
            # 尝试从Redis中消费请求计数
            count, ttl = await consume_request(
                request.app.state.redis, key, config.rate_limit_window_seconds
            )
        except RedisError:
            # 如果Redis出现错误，记录异常并返回服务不可用响应
            logger.exception("rate_limit_backend_unavailable", client_ip=client_ip)
            return JSONResponse(
                status_code=503,
                content={"detail": "Rate limit service unavailable"},
            )

        # 如果请求数超过限制，返回429响应
        if count > limit:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers={"Retry-After": str(max(1, math.ceil(ttl)))},  # 建议重试时间
            )
        # 如果未超过限制，继续处理请求
        return await call_next(request)


def create_app(app_settings: Settings | None = None) -> FastAPI:
    # 配置日志系统
    configure_logging()
    # 使用传入的设置或默认设置
    active_settings = app_settings or settings

    # 定义FastAPI应用的生命周期管理器
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 将设置存储到应用状态中
        app.state.settings = active_settings
        # 创建异步数据库引擎，启用连接池预检查
        app.state.engine = create_async_engine(
            active_settings.database_url, pool_pre_ping=True
        )
        # 创建异步会话工厂，禁用提交后过期
        app.state.session_factory = async_sessionmaker(
            app.state.engine, expire_on_commit=False
        )
        # 创建Redis客户端连接
        # app.state.redis = Redis.from_url(
        #     active_settings.redis_url, encoding="utf-8", decode_responses=True
        # )
        app.state.redis = Redis(
            host=active_settings.redis_host,
            port=active_settings.redis_port,
            db=active_settings.redis_db,
            password=active_settings.redis_password,
            decode_responses=True,  # 将响应解码为字符串
            max_connections=20,  # 设置最大连接数
        )
        try:
            # 应用启动时执行yield
            yield
        finally:
            # 应用关闭时执行清理工作：关闭Redis连接和数据库引擎
            await app.state.redis.aclose()
            await app.state.engine.dispose()

    # 创建FastAPI应用实例，设置应用名称和生命周期管理器
    app = FastAPI(
        title=active_settings.app_name, lifespan=lifespan  # 应用名称  # 生命周期管理器
    )
    # 再次确保设置在应用状态中可用
    app.state.settings = active_settings
    # 添加请求上下文中间件
    app.add_middleware(RequestContextMiddleware)
    # 添加请求限流中间件
    app.add_middleware(RateLimitMiddleware)
    # 添加CORS中间件，配置跨域访问
    app.add_middleware(
        CORSMiddleware,
        allow_origins=active_settings.cors_origins,
        allow_credentials=active_settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 数据库异常处理器
    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(request: Request, exc: SQLAlchemyError):
        # 记录数据库操作异常日志
        logger.exception("database_operation_failed", path=request.url.path)
        # 返回服务不可用的响应
        return JSONResponse(
            status_code=503, content={"detail": "Database service unavailable"}
        )

    # Redis异常处理器
    @app.exception_handler(RedisError)
    async def redis_error_handler(request: Request, exc: RedisError):
        # 记录Redis操作异常日志
        logger.exception("redis_operation_failed", path=request.url.path)
        # 返回服务不可用的响应
        return JSONResponse(
            status_code=503, content={"detail": "Redis service unavailable"}
        )

    # 根路径路由，返回应用信息
    @app.get("/", tags=["root"])
    async def root() -> dict[str, str]:
        return {"service": active_settings.app_name, "docs": "/docs"}

    # 包含各个模块的路由
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(users.router, prefix="/api/v1")
    app.include_router(home.router, prefix="/api/v1")
    app.include_router(health.router)
    # 返回配置完成的FastAPI应用实例
    return app


app = create_app()
