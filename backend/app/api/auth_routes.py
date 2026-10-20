from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import create_access_token, decode_access_token, hash_password, require_current_user, verify_password
from app.core.config import Settings, get_settings
from app.core.network import extract_client_ip, rate_limit_identity
from app.db.session import get_db
from app.models.user import User
from app.models.user_group import STANDARD_GROUP_CODE
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
from app.services.group_policy import get_default_group
from app.models.auth_session import AuthSession
from app.services.auth_sessions import (
    ACCESS_LIFETIME, COOKIE_NAME, check_session_request, clear_session_cookie,
    create_session, parse_refresh, rotate_session, set_session_cookie, utcnow,
)

auth_router = APIRouter()


def _session_response(db: Session, user: User, response: Response | None) -> TokenResponse:
    session = create_session(db, user)
    if response is not None:
        set_session_cookie(response, session)
    return TokenResponse(access_token=create_access_token(
        {"sub": user.id, "sid": session.id, "typ": "access"}, expires_delta=ACCESS_LIFETIME,
    ))


@auth_router.post("/auth/session", response_model=TokenResponse)
def exchange_legacy_session(
    request: Request, response: Response,
    user: User = Depends(require_current_user), db: Session = Depends(get_db),
) -> TokenResponse:
    check_session_request(request)
    payload = decode_access_token(request.headers.get("authorization", "").split(" ", 1)[-1])
    if payload.get("sid") or payload.get("typ"):
        raise HTTPException(401, "请使用刷新凭证续期。")
    return _session_response(db, user, response)


@auth_router.post("/auth/refresh", response_model=TokenResponse)
def refresh_session(request: Request, response: Response, db: Session = Depends(get_db)):
    check_session_request(request)
    try:
        session = rotate_session(db, request.cookies.get(COOKIE_NAME, ""))
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        failure = JSONResponse({"detail": exc.detail}, status_code=401)
        clear_session_cookie(failure)
        return failure
    set_session_cookie(response, session)
    return TokenResponse(access_token=create_access_token(
        {"sub": session.user_id, "sid": session.id, "typ": "access"}, expires_delta=ACCESS_LIFETIME,
    ))


@auth_router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_session(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    check_session_request(request)
    parsed = parse_refresh(request.cookies.get(COOKIE_NAME, ""))
    if parsed:
        session = db.scalar(select(AuthSession).where(AuthSession.id == parsed[0]).with_for_update())
        if session:
            session.revoked_at = utcnow()
            db.commit()
    clear_session_cookie(response)


@auth_router.post("/auth/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    db: Session = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
    request: Request = None,
    response: Response = None,
) -> TokenResponse:
    if isinstance(request, Request):
        check_session_request(request)
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

    return _session_response(db, user, response)


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
    response: Response = None,
    request: Request = None,
) -> TokenResponse:
    if isinstance(request, Request):
        check_session_request(request)
    if not settings.registration_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前未开放注册。")

    email = normalize_email(str(body.email))
    username = body.username
    if username is not None:
        if db.scalar(select(User.id).where(func.lower(User.username) == username)):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在。")
    else:
        for _ in range(3):
            username = f"user_{secrets.token_hex(8)}"
            if not db.scalar(select(User.id).where(func.lower(User.username) == username)):
                break
        else:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="账号创建暂时失败，请重试。")
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

    default_group = get_default_group(db)
    user = User(
        username=username,
        email=email,
        password_hash=hash_password(body.password),
        display_name=body.display_name.strip() or (body.username if body.username else f"画友{username[-6:]}"),
        group_code=default_group.code if default_group else STANDARD_GROUP_CODE,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名或邮箱已存在。")
    consume_email_code(redis_client, email=email, purpose=EmailCodePurpose.REGISTER)
    return _session_response(db, user, response)


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
