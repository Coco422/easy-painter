from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.auth_session import AuthSession
from app.models.user import User

ACCESS_LIFETIME = timedelta(minutes=15)
IDLE_LIFETIME = timedelta(days=30)
ABSOLUTE_LIFETIME = timedelta(days=180)
ROTATION_GRACE = timedelta(seconds=30)
COOKIE_NAME = "easy-painter-refresh"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def password_digest(user: User) -> str:
    return hashlib.sha256(user.password_hash.encode()).hexdigest()


def refresh_token(session: AuthSession) -> str:
    # Deterministic per generation permits concurrent refresh retries to receive
    # the same successor without storing a recoverable refresh token in the DB.
    value = f"{session.id}.{session.generation}"
    signature = hmac.new(get_settings().jwt_secret_key.encode(), f"refresh:{value}".encode(), hashlib.sha256).hexdigest()
    return f"{value}.{signature}"


def parse_refresh(token: str) -> tuple[str, int] | None:
    try:
        session_id, generation_text, signature = token.split(".")
        generation = int(generation_text)
        if not 0 <= generation <= 2_147_483_647 or str(generation) != generation_text:
            return None
        expected = refresh_token(AuthSession(id=session_id, generation=generation)).rsplit(".", 1)[1]
        return (session_id, generation) if hmac.compare_digest(signature, expected) else None
    except (ValueError, TypeError):
        return None


def valid_session(session: AuthSession | None, user: User | None) -> bool:
    now = utcnow()
    return bool(session and user and session.user_id == user.id and not session.revoked_at
                and as_utc(session.expires_at) > now and as_utc(session.absolute_expires_at) > now
                and hmac.compare_digest(session.password_digest, password_digest(user)))


def create_session(db: Session, user: User) -> AuthSession:
    now = utcnow()
    session = AuthSession(id=str(uuid4()), user_id=user.id, generation=0,
                          password_digest=password_digest(user), created_at=now, rotated_at=now,
                          expires_at=now + IDLE_LIFETIME, absolute_expires_at=now + ABSOLUTE_LIFETIME)
    db.add(session)
    db.commit()
    return session


def rotate_session(db: Session, token: str) -> AuthSession:
    parsed = parse_refresh(token)
    if not parsed:
        raise HTTPException(401, "登录已过期，请重新登录。")
    session_id, generation = parsed
    session = db.scalar(select(AuthSession).where(AuthSession.id == session_id)
                        .with_for_update().execution_options(populate_existing=True))
    user = db.get(User, session.user_id, populate_existing=True) if session else None
    if not valid_session(session, user):
        raise HTTPException(401, "登录已过期，请重新登录。")
    now = utcnow()
    if generation == session.generation:
        session.generation += 1
        session.rotated_at = now
        session.expires_at = min(now + IDLE_LIFETIME, as_utc(session.absolute_expires_at))
    elif generation == session.generation - 1 and now - as_utc(session.rotated_at) <= ROTATION_GRACE:
        pass  # Concurrent tabs / a lost response: resend the same successor.
    else:
        session.revoked_at = now
        db.commit()
        raise HTTPException(401, "登录凭证已失效，请重新登录。")
    db.commit()
    return session


def check_session_request(request: Request) -> None:
    # A custom header prevents simple cross-site forms; same-origin checks also
    # reject sibling-site attacks. No credentialed CORS is enabled by the API.
    from urllib.parse import urlsplit

    origin = request.headers.get("origin")
    try:
        parsed_origin = urlsplit(origin) if origin else None
    except ValueError:
        raise HTTPException(403, "请从本站发起登录操作。") from None
    settings = get_settings()
    development_origin = settings.app_env != "production" and origin in settings.allowed_origins
    if (request.headers.get("x-session-request") != "1"
            or request.headers.get("sec-fetch-site") == "cross-site"
            or (parsed_origin and not development_origin and (parsed_origin.netloc != request.headers.get("host")
                                   or parsed_origin.scheme not in {"http", "https"}))):
        raise HTTPException(403, "请从本站发起登录操作。")


def set_session_cookie(response: Response, session: AuthSession) -> None:
    settings = get_settings()
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(COOKIE_NAME, refresh_token(session),
                        max_age=max(0, int((as_utc(session.expires_at) - utcnow()).total_seconds())),
                        path=f"{settings.api_v1_prefix}/auth", httponly=True,
                        secure=settings.app_env == "production", samesite="strict")


def clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie(COOKIE_NAME, path=f"{settings.api_v1_prefix}/auth",
                           httponly=True, secure=settings.app_env == "production", samesite="strict")
