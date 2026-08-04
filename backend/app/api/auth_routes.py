from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis import Redis
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import create_access_token, hash_password, verify_password
from app.core.config import Settings, get_settings
from app.core.network import extract_client_ip, rate_limit_identity
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import (
    AdminVerifyRequest,
    EmailCodePurpose,
    EmailCodeRequest,
    EmailCodeResponse,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.services.email_codes import (
    EmailCodeRateLimitExceeded,
    consume_email_code,
    enforce_email_code_send_limits,
    normalize_email,
    release_email_code_cooldown,
    store_email_code,
    verify_email_code,
)
from app.services.mailer import EmailDeliveryError, SmtpEmailSender
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

    identifier = body.username.strip()
    normalized_identifier = identifier.lower()
    user = db.scalar(
        select(User).where(
            or_(
                User.username == identifier,
                func.lower(User.email) == normalized_identifier,
            )
        )
    )
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误。")

    token = create_access_token({"sub": user.id})
    return TokenResponse(access_token=token)


@auth_router.post(
    "/auth/email-codes",
    response_model=EmailCodeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_email_code(
    body: EmailCodeRequest,
    request: Request,
    db: Session = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> EmailCodeResponse:
    if body.purpose == EmailCodePurpose.REGISTER and not settings.registration_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前未开放注册。")
    if not settings.smtp_configured:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="邮件服务尚未配置。")

    email = normalize_email(str(body.email))
    ip_identity = rate_limit_identity(extract_client_ip(request))
    try:
        enforce_email_code_send_limits(
            redis_client,
            settings,
            email=email,
            ip_identity=ip_identity,
        )
    except EmailCodeRateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="验证码发送过于频繁，请稍后再试。",
            headers={"Retry-After": str(exc.retry_after)},
        ) from None

    existing_user = db.scalar(select(User).where(func.lower(User.email) == email))
    if body.purpose == EmailCodePurpose.REGISTER and existing_user:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已注册。")
    if body.purpose == EmailCodePurpose.RESET_PASSWORD and not existing_user:
        return EmailCodeResponse(
            message="如果该邮箱已注册，验证码将发送到邮箱。",
            expires_in=settings.email_code_expire_seconds,
            retry_after=settings.email_code_cooldown_seconds,
        )

    code = f"{secrets.randbelow(1_000_000):06d}"
    store_email_code(
        redis_client,
        settings,
        email=email,
        purpose=body.purpose,
        code=code,
    )
    try:
        SmtpEmailSender(settings).send_verification_code(
            recipient=email,
            code=code,
            purpose=body.purpose,
        )
    except EmailDeliveryError:
        consume_email_code(redis_client, email=email, purpose=body.purpose)
        release_email_code_cooldown(redis_client, email=email)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="验证码邮件发送失败，请稍后再试。")

    return EmailCodeResponse(
        message="验证码已发送，请检查邮箱。",
        expires_in=settings.email_code_expire_seconds,
        retry_after=settings.email_code_cooldown_seconds,
    )


@auth_router.post("/auth/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterRequest,
    db: Session = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    if not settings.registration_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前未开放注册。")

    email = normalize_email(str(body.email))
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在。")
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已注册。")
    if not verify_email_code(
        redis_client,
        settings,
        email=email,
        purpose=EmailCodePurpose.REGISTER,
        code=body.email_code,
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码无效或已过期。")

    user = User(
        username=body.username,
        email=email,
        password_hash=hash_password(body.password),
        display_name=body.display_name.strip() or body.username,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名或邮箱已存在。")
    consume_email_code(redis_client, email=email, purpose=EmailCodePurpose.REGISTER)
    return TokenResponse(access_token=create_access_token({"sub": user.id}))


@auth_router.post("/auth/password/reset", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    body: ResetPasswordRequest,
    db: Session = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> None:
    email = normalize_email(str(body.email))
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if not user or not verify_email_code(
        redis_client,
        settings,
        email=email,
        purpose=EmailCodePurpose.RESET_PASSWORD,
        code=body.email_code,
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码无效或已过期。")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    consume_email_code(redis_client, email=email, purpose=EmailCodePurpose.RESET_PASSWORD)


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
