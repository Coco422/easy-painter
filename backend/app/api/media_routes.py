from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.generation_job import GenerationJob, JobStatus
from app.models.media import MediaState
from app.models.user import User
from app.services.storage import MinioStorageService, StorageError


media_router = APIRouter()


def _media_error(status_code: int, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=detail,
        headers={"Cache-Control": "no-store"},
    )


def _expired(value: datetime | None, *, now: datetime) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= now


def issue_job_media_token(*, job_id: str, user_id: str | None) -> str:
    """Issue a deliberately narrow, short-lived capability for one job image."""
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.media_token_ttl_seconds)
    payload = {"typ": "job_media", "aud": "media", "job_id": job_id, "exp": expires_at}
    if user_id is not None:
        payload["sub"] = user_id
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def job_media_url(*, job_id: str, user_id: str | None) -> str:
    return f"{get_settings().api_v1_prefix}/media/jobs/{job_id}?token={issue_job_media_token(job_id=job_id, user_id=user_id)}"


def _decode_capability(token: str, job_id: str) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            audience="media",
        )
    except jwt.PyJWTError as exc:
        raise _media_error(status.HTTP_401_UNAUTHORIZED, "媒体链接已失效。") from exc
    if payload.get("typ") != "job_media" or payload.get("job_id") != job_id:
        raise _media_error(status.HTTP_401_UNAUTHORIZED, "无效的媒体链接。")
    return payload


@media_router.api_route("/media/jobs/{job_id}", methods=["GET", "HEAD"])
def stream_job_media(job_id: str, request: Request, token: str = Query(...)):
    """Stream an image after rechecking policy; capabilities never bypass the DB."""
    payload = _decode_capability(token, job_id)
    db: Session = SessionLocal()
    try:
        job = db.get(GenerationJob, job_id)
        now = datetime.now(timezone.utc)
        if (
            not job
            or job.status != JobStatus.SUCCEEDED
            or job.deleted_at is not None
            or job.media_state != MediaState.AVAILABLE
            or not job.object_key
            or _expired(job.media_expires_at, now=now)
        ):
            raise _media_error(status.HTTP_404_NOT_FOUND, "图片不存在或已过期。")
        subject = payload.get("sub")
        if subject is None:
            # Anonymous/public capabilities are revoked as soon as the work is
            # unpublished, deleted, or expires because every request rechecks DB.
            owner = db.get(User, job.user_id) if job.user_id else None
            if not job.is_public or (owner is not None and not owner.is_public):
                raise _media_error(status.HTTP_404_NOT_FOUND, "图片不存在或已过期。")
        elif subject != job.user_id:
            raise _media_error(status.HTTP_403_FORBIDDEN, "无权访问该图片。")
        expires_at = payload.get("exp", int(now.timestamp()))
        media_expires_at = job.media_expires_at
        if media_expires_at is not None and media_expires_at.tzinfo is None:
            media_expires_at = media_expires_at.replace(tzinfo=timezone.utc)
        resource_ttl = (
            int((media_expires_at - now).total_seconds())
            if media_expires_at is not None
            else 3600
        )
        max_age = max(0, min(3600, resource_ttl, int(expires_at - now.timestamp())))
        headers = {"Cache-Control": f"private, max-age={max_age}", "X-Content-Type-Options": "nosniff"}
        if request.method == "HEAD":
            return StreamingResponse(iter(()), media_type=job.media_content_type or "image/jpeg", headers=headers)
        try:
            storage = MinioStorageService()
            if hasattr(storage, "open_object") and hasattr(storage, "iter_response"):
                opened = storage.open_object(job.object_key)
                stream = storage.iter_response(opened)
            else:
                stream = storage.iter_object(job.object_key)
            return StreamingResponse(stream, media_type=job.media_content_type or "image/jpeg", headers=headers)
        except StorageError:
            raise _media_error(status.HTTP_503_SERVICE_UNAVAILABLE, "图片读取失败。") from None
    finally:
        db.close()
