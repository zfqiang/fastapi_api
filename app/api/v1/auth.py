import anyio
import jwt
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, RedisClient
from app.core.security import decode_token, hash_password, verify_password
from app.models import User
from app.schemas.auth import Credentials, RefreshRequest, TokenPair
from app.services.auth import consume_refresh_token, issue_token_pair

# APIRouter 是一个路由器，用于定义API的路径和对应的处理函数
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(
    payload: Credentials, request: Request, session: DbSession, redis: RedisClient
) -> TokenPair:
    email = str(payload.email).lower()
    existing = await session.scalar(select(User.id).where(User.email == email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )

    user = User(
        email=email,
        password_hash=await anyio.to_thread.run_sync(hash_password, payload.password),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        ) from None
    await session.refresh(user)
    tokens = await issue_token_pair(redis, user.id, request.app.state.settings)
    return TokenPair(**tokens)


@router.post("/login", response_model=TokenPair)
async def login(
    payload: Credentials, request: Request, session: DbSession, redis: RedisClient
) -> TokenPair:
    email = str(payload.email).lower()
    user = await session.scalar(select(User).where(User.email == email))
    password_matches = False
    if user is not None:
        password_matches = await anyio.to_thread.run_sync(
            verify_password, payload.password, user.password_hash
        )
    if user is None or not password_matches or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    tokens = await issue_token_pair(redis, user.id, request.app.state.settings)
    return TokenPair(**tokens)


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    payload: RefreshRequest, request: Request, redis: RedisClient
) -> TokenPair:
    settings = request.app.state.settings
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
    )
    try:
        token_data = decode_token(payload.refresh_token, settings)
        if token_data.get("type") != "refresh":
            raise invalid
        user_id = int(str(token_data["sub"]))
        token_id = str(token_data["jti"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise invalid from None

    is_valid = await consume_refresh_token(redis, token_id, user_id)
    if not is_valid:
        raise invalid
    tokens = await issue_token_pair(redis, user_id, settings)
    return TokenPair(**tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: RefreshRequest, request: Request, redis: RedisClient
) -> None:
    try:
        token_data = decode_token(payload.refresh_token, request.app.state.settings)
        if token_data.get("type") != "refresh":
            return
        await consume_refresh_token(
            redis,
            str(token_data["jti"]),
            int(str(token_data["sub"])),
        )
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        return
