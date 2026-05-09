from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import ValidationError
from redis import Redis
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.core.auth import get_current_user_optional, require_current_user
from app.core.config import Settings, get_settings
from app.core.network import extract_client_ip, rate_limit_identity
from app.db.session import get_db
from app.models.credit_transaction import CreditTransaction
from app.models.gallery_like import GalleryLike
from app.models.generation_job import GenerationJob, JobStatus
from app.models.user import User
from app.schemas.job import (
    CreateJobRequest,
    CreateJobResponse,
    GalleryItem,
    GalleryPageResponse,
    HealthResponse,
    JobDetailResponse,
    PublicMetaResponse,
)
from app.services.model_service import load_models_from_db
from app.services.rate_limit import GenerationRateLimiter
from app.services.reference_images import ReferenceImagePayload, ReferenceImageValidationError, validate_reference_image
from app.services.redis_client import get_redis
from app.services.storage import MinioStorageService, StorageError
from app.services.tasks import generate_image_task


logger = logging.getLogger(__name__)
router = APIRouter()
ACTIVE_JOBS_LIMIT = 20
LIVE_JOB_STATUSES = (JobStatus.QUEUED, JobStatus.PROCESSING)
STALE_JOB_MESSAGE = "生成任务长时间没有响应，可能已在服务重启或 worker 中断后丢失，请重新生成。"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _load_models(db: Session, settings: Settings) -> list[dict[str, str | bool | list[str]]]:
    try:
        return load_models_from_db(db)
    except Exception:
        logger.exception("Failed to load model configs from database; falling back to settings.")
    return settings.public_models


@dataclass(slots=True)
class ParsedCreateJobPayload:
    request: CreateJobRequest
    reference_image: ReferenceImagePayload | None = None


@router.get("/meta/public", response_model=PublicMetaResponse)
def get_public_meta(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PublicMetaResponse:
    return PublicMetaResponse(
        site_name=settings.site_name,
        prompt_max_length=settings.prompt_max_length,
        polling_interval_ms=settings.polling_interval_ms,
        example_prompts=settings.example_prompts,
        models=_load_models(db, settings),
    )


@router.post("/jobs", response_model=CreateJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    request: Request,
    db: Session = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(require_current_user),
) -> CreateJobResponse:
    parsed_payload = await _parse_create_job_payload(request)
    payload = parsed_payload.request
    prompt = payload.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="提示词不能为空。")
    if len(prompt) > settings.prompt_max_length:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"提示词不能超过 {settings.prompt_max_length} 个字符。",
        )

    enabled_models = {item["id"]: item for item in _load_models(db, settings) if item["enabled"]}
    model_config = enabled_models.get(payload.model)
    if not model_config:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="当前模型不可用。")
    if parsed_payload.reference_image and not model_config.get("supports_reference_image", True):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="当前模型不支持参考图，请切换到支持参考图的模型。",
        )
    supported_sizes = model_config.get("supported_sizes", [])
    if isinstance(supported_sizes, list) and supported_sizes and payload.size not in supported_sizes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="当前模型不支持该尺寸，请切换尺寸或模型。",
        )

    limiter = GenerationRateLimiter(
        redis_client=redis_client,
        limit=settings.generate_rate_limit_count,
        window_seconds=settings.generate_rate_limit_window_seconds,
    )
    rate_identity = f"user:{current_user.id}"
    rate_limit_result = limiter.check(rate_identity)
    if not rate_limit_result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="当前 IP 请求过于频繁，请 1 分钟后再试。",
        )

    credit_cost = model_config.get("credit_cost", 1)
    if isinstance(credit_cost, int) and credit_cost > 0:
        db.refresh(current_user)
        if (current_user.credits or 0) < credit_cost:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "message": "灵感丝线不足，请前往个人中心兑换。",
                    "required": credit_cost,
                    "balance": current_user.credits or 0,
                },
            )
        current_user.credits -= credit_cost
        db.flush()

    job = GenerationJob(
        prompt=prompt,
        model=payload.model,
        size=payload.size,
        aspect_ratio=payload.aspect_ratio or "auto",
        status=JobStatus.QUEUED,
        user_id=current_user.id,
    )
    db.add(job)
    try:
        db.flush()
        if isinstance(credit_cost, int) and credit_cost > 0:
            txn = CreditTransaction(
                user_id=current_user.id,
                amount=-credit_cost,
                balance_after=current_user.credits,
                reason=f"job:{job.id}",
            )
            db.add(txn)
        if parsed_payload.reference_image:
            try:
                object_key = MinioStorageService().upload_reference_image(
                    job_id=job.id,
                    image_bytes=parsed_payload.reference_image.image_bytes,
                    content_type=parsed_payload.reference_image.content_type,
                    filename=parsed_payload.reference_image.filename,
                )
            except StorageError:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="参考图保存失败，请稍后重试。",
                ) from None
            job.reference_image_key = object_key
            job.reference_image_content_type = parsed_payload.reference_image.content_type
            job.reference_image_filename = parsed_payload.reference_image.filename
        db.commit()
        db.refresh(job)
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise

    try:
        generate_image_task.delay(job.id)
    except Exception:
        logger.error("Failed to enqueue generation job.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="任务队列暂时不可用，请稍后重试。",
        ) from None

    return CreateJobResponse(
        job_id=job.id,
        status=job.status.value,
        poll_url=f"{settings.api_v1_prefix}/jobs/{job.id}",
        rate_limit_remaining=rate_limit_result.remaining,
    )


async def _parse_create_job_payload(request: Request) -> ParsedCreateJobPayload:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        raw_payload = {
            "prompt": form.get("prompt"),
            "model": form.get("model"),
            "size": form.get("size") or None,
            "aspect_ratio": form.get("aspect_ratio") or "auto",
        }
        try:
            payload = CreateJobRequest.model_validate(raw_payload)
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc

        upload = form.get("reference_image")
        reference_image = None
        if isinstance(upload, StarletteUploadFile):
            image_bytes = await upload.read()
            try:
                reference_image = validate_reference_image(
                    filename=upload.filename,
                    content_type=upload.content_type,
                    image_bytes=image_bytes,
                )
            except ReferenceImageValidationError as exc:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        return ParsedCreateJobPayload(request=payload, reference_image=reference_image)

    try:
        payload = CreateJobRequest.model_validate(await request.json())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc
    return ParsedCreateJobPayload(request=payload)


@router.get("/jobs/active", response_model=list[JobDetailResponse])
def list_active_jobs(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(require_current_user),
    now: datetime = Depends(utcnow),
) -> list[JobDetailResponse]:
    stmt = (
        select(GenerationJob)
        .where(GenerationJob.user_id == current_user.id)
        .where(GenerationJob.status.in_(LIVE_JOB_STATUSES))
        .order_by(desc(GenerationJob.created_at))
        .limit(ACTIVE_JOBS_LIMIT)
    )
    jobs = db.scalars(stmt).all()
    _settle_stale_live_jobs(db=db, jobs=jobs, settings=settings, now=now)
    return [_build_job_detail_response(job) for job in jobs if _is_live_job(job)]


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    now: datetime = Depends(utcnow),
) -> JobDetailResponse:
    job = db.get(GenerationJob, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在。")
    _settle_stale_live_jobs(db=db, jobs=[job], settings=settings, now=now)
    return _build_job_detail_response(job)


def _settle_stale_live_jobs(
    *,
    db: Session,
    jobs: list[GenerationJob],
    settings: Settings,
    now: datetime,
) -> None:
    if settings.generation_job_stale_seconds <= 0:
        return
    stale_cutoff = _as_utc(now) - timedelta(seconds=settings.generation_job_stale_seconds)
    changed = False
    for job in jobs:
        anchor = job.started_at or job.created_at
        if _is_live_job(job) and anchor and _as_utc(anchor) <= stale_cutoff:
            job.status = JobStatus.FAILED
            job.error_message = STALE_JOB_MESSAGE
            job.finished_at = now
            changed = True
    if changed:
        db.commit()


def _is_live_job(job: GenerationJob) -> bool:
    return job.status in LIVE_JOB_STATUSES


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _build_job_detail_response(job: GenerationJob) -> JobDetailResponse:
    return JobDetailResponse(
        job_id=job.id,
        status=job.status.value,
        image_url=job.public_url,
        prompt=job.prompt,
        revised_prompt=job.revised_prompt,
        model=job.model,
        size=job.size,
        aspect_ratio=job.aspect_ratio,
        error_message=job.error_message,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> None:
    job = db.get(GenerationJob, job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在。")
    if job.object_key:
        try:
            MinioStorageService().delete_object(job.object_key)
        except Exception:
            logger.warning("Failed to delete MinIO object %s", job.object_key)
    if job.reference_image_key:
        try:
            MinioStorageService().delete_reference_image(job.reference_image_key)
        except Exception:
            logger.warning("Failed to delete MinIO reference %s", job.reference_image_key)
    for like in db.scalars(select(GalleryLike).where(GalleryLike.job_id == job.id)).all():
        db.delete(like)
    db.delete(job)
    db.commit()


@router.put("/jobs/{job_id}/public")
def toggle_job_public(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> dict[str, bool]:
    job = db.get(GenerationJob, job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在。")
    job.is_public = not job.is_public
    db.commit()
    return {"is_public": job.is_public}


@router.put("/jobs/{job_id}/favorite")
def toggle_job_favorite(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> dict[str, bool]:
    job = db.get(GenerationJob, job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在。")
    job.is_favorite = not job.is_favorite
    db.commit()
    return {"is_favorite": job.is_favorite}


@router.post("/gallery/{job_id}/like")
def like_gallery_item(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> dict[str, int]:
    job = db.get(GenerationJob, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="作品不存在。")
    existing = db.scalar(
        select(GalleryLike).where(
            GalleryLike.job_id == job_id, GalleryLike.user_id == current_user.id
        )
    )
    if not existing:
        db.add(GalleryLike(job_id=job_id, user_id=current_user.id))
        db.commit()
    count = _get_like_count(db, job_id)
    return {"like_count": count}


@router.delete("/gallery/{job_id}/like", status_code=status.HTTP_204_NO_CONTENT)
def unlike_gallery_item(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> None:
    existing = db.scalar(
        select(GalleryLike).where(
            GalleryLike.job_id == job_id, GalleryLike.user_id == current_user.id
        )
    )
    if existing:
        db.delete(existing)
        db.commit()


@router.get("/gallery", response_model=GalleryPageResponse)
def get_gallery(
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, max_length=200),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
) -> GalleryPageResponse:
    if not current_user:
        return GalleryPageResponse(items=[], total=0, page=page, page_size=page_size)

    base = (
        select(GenerationJob)
        .where(GenerationJob.status == JobStatus.SUCCEEDED)
        .where(GenerationJob.user_id == current_user.id)
    )
    if q:
        base = base.where(GenerationJob.prompt.ilike(f"%{q}%"))
    if from_date:
        try:
            base = base.where(GenerationJob.finished_at >= datetime.fromisoformat(from_date))
        except ValueError:
            pass
    if to_date:
        try:
            dt = datetime.fromisoformat(to_date)
            if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
                dt = dt.replace(hour=23, minute=59, second=59)
            base = base.where(GenerationJob.finished_at <= dt)
        except ValueError:
            pass

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    stmt = (
        base.order_by(desc(GenerationJob.finished_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    jobs = [j for j in db.scalars(stmt).all() if j.public_url and j.finished_at]
    items = _build_gallery_items(db, jobs, current_user.id)
    return GalleryPageResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/gallery/public", response_model=list[GalleryItem])
def get_public_gallery(
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
    sort: str = Query("recent", pattern="^(recent|liked)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> list[GalleryItem]:
    stmt = (
        select(GenerationJob)
        .where(GenerationJob.status == JobStatus.SUCCEEDED)
        .where(GenerationJob.is_public.is_(True))
    )
    if sort == "liked":
        like_count_sub = (
            select(GalleryLike.job_id, func.count().label("cnt"))
            .group_by(GalleryLike.job_id)
            .subquery()
        )
        stmt = stmt.outerjoin(like_count_sub, GenerationJob.id == like_count_sub.c.job_id)
        stmt = stmt.order_by(desc(like_count_sub.c.cnt), desc(GenerationJob.finished_at))
    else:
        stmt = stmt.order_by(desc(GenerationJob.finished_at))
    stmt = stmt.offset(offset).limit(limit)
    jobs = [j for j in db.scalars(stmt).all() if j.public_url and j.finished_at]
    return _build_gallery_items(db, jobs, current_user.id if current_user else None)


@router.get("/gallery/{username}", response_model=list[GalleryItem])
def get_user_gallery(
    username: str,
    db: Session = Depends(get_db),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> list[GalleryItem]:
    user = db.scalar(select(User).where(User.username == username))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该用户不存在。")
    stmt = (
        select(GenerationJob)
        .where(GenerationJob.status == JobStatus.SUCCEEDED)
        .where(GenerationJob.user_id == user.id)
        .where(GenerationJob.is_public.is_(True))
        .order_by(desc(GenerationJob.finished_at))
        .offset(offset)
        .limit(limit)
    )
    jobs = [j for j in db.scalars(stmt).all() if j.public_url and j.finished_at]
    return _build_gallery_items(db, jobs, None)


def _get_like_count(db: Session, job_id: str) -> int:
    return db.scalar(
        select(func.count()).select_from(GalleryLike).where(GalleryLike.job_id == job_id)
    ) or 0


def _batch_like_counts(db: Session, job_ids: list[str]) -> dict[str, int]:
    if not job_ids:
        return {}
    rows = db.execute(
        select(GalleryLike.job_id, func.count()).where(GalleryLike.job_id.in_(job_ids)).group_by(GalleryLike.job_id)
    ).all()
    return {job_id: count for job_id, count in rows}


def _batch_user_likes(db: Session, job_ids: list[str], user_id: str | None) -> set[str]:
    if not user_id or not job_ids:
        return set()
    rows = db.scalars(
        select(GalleryLike.job_id).where(
            GalleryLike.job_id.in_(job_ids), GalleryLike.user_id == user_id
        )
    ).all()
    return set(rows)


def _batch_usernames(db: Session, user_ids: list[str]) -> dict[str, str]:
    if not user_ids:
        return {}
    users = db.scalars(select(User).where(User.id.in_(user_ids))).all()
    return {u.id: u.username for u in users}


def _build_gallery_item(
    job: GenerationJob,
    username: str | None,
    like_counts: dict[str, int],
    liked_job_ids: set[str],
) -> GalleryItem:
    return GalleryItem(
        job_id=job.id,
        image_url=job.public_url or "",
        prompt=job.prompt,
        revised_prompt=job.revised_prompt,
        model=job.model,
        size=job.size,
        aspect_ratio=job.aspect_ratio,
        finished_at=job.finished_at,
        username=username,
        is_public=job.is_public,
        is_favorite=job.is_favorite,
        like_count=like_counts.get(job.id, 0),
        liked_by_me=job.id in liked_job_ids,
    )


def _build_gallery_items(
    db: Session,
    jobs: list[GenerationJob],
    viewer_user_id: str | None,
) -> list[GalleryItem]:
    job_ids = [j.id for j in jobs]
    user_ids = [j.user_id for j in jobs if j.user_id]
    like_counts = _batch_like_counts(db, job_ids)
    liked_job_ids = _batch_user_likes(db, job_ids, viewer_user_id)
    usernames = _batch_usernames(db, user_ids)
    return [
        _build_gallery_item(
            job=job,
            username=usernames.get(job.user_id) if job.user_id else None,
            like_counts=like_counts,
            liked_job_ids=liked_job_ids,
        )
        for job in jobs
    ]


@router.get("/healthz", response_model=HealthResponse)
def healthz(
    response: Response,
    db: Session = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
) -> HealthResponse:
    try:
        db.execute(select(1))
        redis_client.ping()
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded")
    return HealthResponse(status="ok")
