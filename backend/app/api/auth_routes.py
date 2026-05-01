from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import create_access_token, verify_password
from app.core.config import Settings, get_settings
from app.core.network import extract_client_ip, rate_limit_identity
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import AdminVerifyRequest, LoginRequest, TokenResponse
from app.services.rate_limit import GenerationRateLimiter
from app.services.redis_client import get_redis

auth_router = APIRouter()


@auth_router.post("/auth/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    db: Session = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
    request: Request = None,
) -> TokenResponse:
    limiter = GenerationRateLimiter(redis_client=redis_client, limit=10, window_seconds=60)
    identity = rate_limit_identity(extract_client_ip(request))
    result = limiter.check(f"login:{identity}")
    if not result.allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="登录尝试过于频繁，请稍后再试。")

    user = db.scalar(select(User).where(User.username == body.username))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误。")

    token = create_access_token({"sub": user.id})
    return TokenResponse(access_token=token)


@auth_router.post("/admin/verify", response_model=TokenResponse)
def admin_verify(
    body: AdminVerifyRequest,
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    if not settings.admin_secret_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="后台管理未启用。")
    if body.secret_key != settings.admin_secret_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="密钥错误。")
    token = create_access_token({"sub": "admin", "role": "admin"})
    return TokenResponse(access_token=token)
