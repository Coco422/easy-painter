from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import ValidationError
from redis import Redis
from sqlalchemy import desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.core.auth import get_current_user_optional, require_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.gallery_like import GalleryLike
from app.models.generation_job import GenerationJob, JobStatus
from app.models.job_charge import JobCharge
from app.models.model_config import ModelConfig
from app.models.outbox_event import OutboxEvent
from app.models.reference_image import ReferenceImage
from app.models.upstream_provider import UpstreamProvider
from app.models.user import User
from app.schemas.job import (
    CreateJobRequest,
    CreateJobResponse,
    GalleryItem,
    GalleryPageResponse,
    HealthResponse,
    JobDetailResponse,
    PublicMetaResponse,
    TogglePublicRequest,
)
from app.services.model_service import load_models_from_db
from app.services.billing import InsufficientCreditsError, reserve_job_credits
from app.services.job_lifecycle import mark_generation_failed
from app.services.health import collect_core_health
from app.services.rate_limit import GenerationRateLimiter
from app.services.reference_images import ReferenceImagePayload, ReferenceImageValidationError, validate_reference_image
from app.services.redis_client import get_redis
from app.services.storage import MinioStorageService, StorageError


logger = logging.getLogger(__name__)
router = APIRouter()
ACTIVE_JOBS_LIMIT = 20
LIVE_JOB_STATUSES = (JobStatus.QUEUED, JobStatus.PROCESSING)
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _load_models(db: Session, settings: Settings) -> list[dict[str, str | bool | int | list[str]]]:
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
        registration_enabled=settings.registration_enabled,
        email_delivery_enabled=settings.smtp_configured,
        prompt_max_length=settings.prompt_max_length,
        polling_interval_ms=settings.polling_interval_ms,
        example_prompts=settings.example_prompts,
        models=_load_models(db, settings),
    )


@router.post("/jobs", response_model=CreateJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    db: Session = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(require_current_user),
) -> CreateJobResponse:
    parsed_payload = await _parse_create_job_payload(request)
    payload = parsed_payload.request
    prompt = payload.prompt.strip()
    if idempotency_key is not None and not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Idempotency-Key 只能包含字母、数字、点、下划线、冒号或连字符，且最长 128 字符。",
        )
    effective_idempotency_key = idempotency_key or str(uuid4())
    request_fingerprint = _job_request_fingerprint(parsed_payload, prompt)

    if idempotency_key is not None:
        existing_job = db.scalar(
            select(GenerationJob).where(
                GenerationJob.user_id == current_user.id,
                GenerationJob.idempotency_key == effective_idempotency_key,
            )
        )
        if existing_job:
            if existing_job.request_fingerprint != request_fingerprint:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="该 Idempotency-Key 已用于不同的生成参数。",
                )
            return _build_create_job_response(
                db=db,
                job=existing_job,
                balance=db.scalar(select(User.credits).where(User.id == current_user.id)) or 0,
                rate_limit_remaining=settings.generate_rate_limit_count,
                settings=settings,
            )

    if not prompt:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="提示词不能为空。")
    if len(prompt) > settings.prompt_max_length:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"提示词不能超过 {settings.prompt_max_length} 个字符。",
        )

    enabled_models = {item["id"]: item for item in _load_models(db, settings) if item["enabled"]}
    model_config = enabled_models.get(payload.model)
    if not model_config:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="当前模型不可用。")
    staged_reference_image = None
    if payload.reference_image_id:
        staged_reference_image = db.scalar(
            select(ReferenceImage).where(
                ReferenceImage.id == payload.reference_image_id,
                ReferenceImage.user_id == current_user.id,
            )
        )
        if not staged_reference_image:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="参考图不存在或已删除。",
            )
    if (parsed_payload.reference_image or staged_reference_image) and not model_config.get("supports_reference_image", True):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="当前模型不支持参考图，请切换到支持参考图的模型。",
        )
    supported_sizes = model_config.get("supported_sizes", [])
    if isinstance(supported_sizes, list) and supported_sizes and payload.size not in supported_sizes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="当前模型不支持该尺寸，请切换尺寸或模型。",
        )

    raw_credit_cost = model_config.get("credit_cost", 1)
    credit_cost = raw_credit_cost if isinstance(raw_credit_cost, int) and raw_credit_cost > 0 else 0
    model_row = db.get(ModelConfig, payload.model)
    provider_row = db.get(UpstreamProvider, model_row.provider_id) if model_row else None

    job = GenerationJob(
        prompt=prompt,
        model=payload.model,
        size=payload.size,
        aspect_ratio=payload.aspect_ratio or "auto",
        status=JobStatus.QUEUED,
        user_id=current_user.id,
        model_label_snapshot=str(model_config.get("label") or payload.model),
        provider_id_snapshot=provider_row.id if provider_row else None,
        provider_name_snapshot=provider_row.name if provider_row else None,
        credit_cost_snapshot=credit_cost,
        idempotency_key=effective_idempotency_key,
        request_fingerprint=request_fingerprint,
    )
    db.add(job)
    copied_reference_key: str | None = None
    try:
        # Flush the idempotency row before any side effects. Concurrent replays
        # block on the unique key and never consume rate-limit quota or copy an
        # object twice.
        db.flush()
        limiter = GenerationRateLimiter(
            redis_client=redis_client,
            limit=settings.generate_rate_limit_count,
            window_seconds=settings.generate_rate_limit_window_seconds,
        )
        rate_limit_result = limiter.check(f"user:{current_user.id}")
        if not rate_limit_result.allowed:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="生成请求过于频繁，请稍后再试。",
            )
        if parsed_payload.reference_image:
            try:
                copied_reference_key = MinioStorageService().upload_reference_image(
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
            job.reference_image_key = copied_reference_key
            job.reference_image_content_type = parsed_payload.reference_image.content_type
            job.reference_image_filename = parsed_payload.reference_image.filename
        elif staged_reference_image:
            try:
                copied_reference_key = MinioStorageService().copy_reference_image_to_job(
                    staged_reference_image.object_key,
                    job_id=job.id,
                    filename=staged_reference_image.filename,
                    content_type=staged_reference_image.content_type,
                )
            except StorageError:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="参考图保存失败，请稍后重试。",
                ) from None
            job.reference_image_key = copied_reference_key
            job.reference_image_content_type = staged_reference_image.content_type
            job.reference_image_filename = staged_reference_image.filename
            staged_reference_image.used_count = (staged_reference_image.used_count or 0) + 1
            staged_reference_image.last_used_at = utcnow()
        _, balance_after = reserve_job_credits(
            db,
            job=job,
            user_id=current_user.id,
            amount=credit_cost,
            model_label=job.model_label_snapshot or job.model,
            provider_name=job.provider_name_snapshot,
        )
        db.add(
            OutboxEvent(
                event_type="generation.job.created",
                aggregate_id=job.id,
                payload={"job_id": job.id},
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        if copied_reference_key:
            MinioStorageService().delete_reference_image(copied_reference_key)
        existing_job = db.scalar(
            select(GenerationJob).where(
                GenerationJob.user_id == current_user.id,
                GenerationJob.idempotency_key == effective_idempotency_key,
            )
        )
        if existing_job and existing_job.request_fingerprint == request_fingerprint:
            return _build_create_job_response(
                db=db,
                job=existing_job,
                balance=db.scalar(select(User.credits).where(User.id == current_user.id)) or 0,
                rate_limit_remaining=settings.generate_rate_limit_count,
                settings=settings,
            )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该请求已被其他操作占用。") from None
    except InsufficientCreditsError as exc:
        db.rollback()
        if copied_reference_key:
            MinioStorageService().delete_reference_image(copied_reference_key)
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "message": "灵感丝线不足，请前往个人中心兑换。",
                "required": exc.required,
                "balance": exc.balance,
            },
        ) from None
    except HTTPException:
        if copied_reference_key:
            MinioStorageService().delete_reference_image(copied_reference_key)
        raise
    except Exception:
        db.rollback()
        if copied_reference_key:
            MinioStorageService().delete_reference_image(copied_reference_key)
        raise

    return _build_create_job_response(
        db=db,
        job=job,
        balance=balance_after,
        rate_limit_remaining=rate_limit_result.remaining,
        settings=settings,
    )


def _job_request_fingerprint(parsed_payload: ParsedCreateJobPayload, prompt: str) -> str:
    payload = parsed_payload.request
    reference_value = payload.reference_image_id
    if parsed_payload.reference_image:
        reference_value = hashlib.sha256(parsed_payload.reference_image.image_bytes).hexdigest()
    canonical = json.dumps(
        {
            "prompt": prompt,
            "model": payload.model,
            "size": payload.size,
            "aspect_ratio": payload.aspect_ratio or "auto",
            "reference": reference_value,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_create_job_response(
    *,
    db: Session,
    job: GenerationJob,
    balance: int,
    rate_limit_remaining: int,
    settings: Settings,
) -> CreateJobResponse:
    charge = db.scalar(select(JobCharge).where(JobCharge.job_id == job.id))
    return CreateJobResponse(
        job_id=job.id,
        status=job.status.value,
        poll_url=f"{settings.api_v1_prefix}/jobs/{job.id}",
        rate_limit_remaining=rate_limit_remaining,
        credit_cost=charge.amount if charge else job.credit_cost_snapshot,
        balance_after=balance,
        billing_status=charge.status.value if charge else "not_charged",
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
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.errors()) from exc

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
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
        return ParsedCreateJobPayload(request=payload, reference_image=reference_image)

    try:
        payload = CreateJobRequest.model_validate(await request.json())
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.errors()) from exc
    return ParsedCreateJobPayload(request=payload)


@router.get("/jobs/active", response_model=list[JobDetailResponse])
def list_active_jobs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> list[JobDetailResponse]:
    stmt = (
        select(GenerationJob)
        .where(GenerationJob.user_id == current_user.id)
        .where(GenerationJob.status.in_(LIVE_JOB_STATUSES))
        .order_by(desc(GenerationJob.created_at))
        .limit(ACTIVE_JOBS_LIMIT)
    )
    jobs = db.scalars(stmt).all()
    return [_build_job_detail_response(db, job) for job in jobs]


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> JobDetailResponse:
    job = db.get(GenerationJob, job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在。")
    return _build_job_detail_response(db, job)


def _build_job_detail_response(db: Session, job: GenerationJob) -> JobDetailResponse:
    charge = db.scalar(select(JobCharge).where(JobCharge.job_id == job.id))
    return JobDetailResponse(
        job_id=job.id,
        status=job.status.value,
        image_url=job.public_url,
        prompt=job.prompt,
        revised_prompt=job.revised_prompt,
        model=job.model,
        model_label=job.model_label_snapshot,
        provider_name=job.provider_name_snapshot,
        size=job.size,
        aspect_ratio=job.aspect_ratio,
        error_message=job.error_message,
        credit_cost=charge.amount if charge else job.credit_cost_snapshot,
        billing_status=charge.status.value if charge else "not_charged",
        refunded_at=charge.refunded_at if charge else None,
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
    if job.status in LIVE_JOB_STATUSES:
        mark_generation_failed(
            db,
            job_id=job.id,
            message="用户删除了尚未完成的任务，灵感丝线已自动退回。",
        )
        job = db.get(GenerationJob, job_id)
        if not job:
            return
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
    body: TogglePublicRequest = TogglePublicRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> dict[str, bool]:
    job = db.get(GenerationJob, job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在。")
    if not job.is_public:
        if job.status != JobStatus.SUCCEEDED:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="只能公开已完成的作品。")
        # Publishing: accept tags and prompt visibility setting
        job.is_public = True
        job.tags = body.tags
        job.is_prompt_public = body.is_prompt_public
    else:
        # Unpublishing: just toggle off, clear tags
        job.is_public = False
    db.commit()
    return {"is_public": job.is_public}


@router.get("/tags/popular")
def get_popular_tags(
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=50),
) -> list[str]:
    jobs = db.scalars(
        select(GenerationJob.tags)
        .outerjoin(User, GenerationJob.user_id == User.id)
        .where(GenerationJob.is_public.is_(True))
        .where(or_(GenerationJob.user_id.is_(None), User.is_public.is_(True)))
        .where(GenerationJob.tags.isnot(None))
        .limit(1000)
    ).all()
    tag_counts: dict[str, int] = {}
    for tags in jobs:
        if not isinstance(tags, list):
            continue
        for tag in tags:
            if isinstance(tag, str) and tag.strip():
                tag_counts[tag.strip()] = tag_counts.get(tag.strip(), 0) + 1
    sorted_tags = sorted(tag_counts, key=lambda t: tag_counts[t], reverse=True)
    return sorted_tags[:limit]


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
        .outerjoin(User, GenerationJob.user_id == User.id)
        .where(GenerationJob.status == JobStatus.SUCCEEDED)
        .where(GenerationJob.is_public.is_(True))
        .where(or_(GenerationJob.user_id.is_(None), User.is_public.is_(True)))
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
    if not user or not user.is_public:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该用户不存在或未公开画廊。")
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
        is_prompt_public=job.is_prompt_public if job.is_prompt_public is not None else True,
        is_favorite=job.is_favorite,
        tags=job.tags,
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


@router.get("/health/live", response_model=HealthResponse)
def health_live() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=HealthResponse)
def health_ready(
    response: Response,
    db: Session = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    components = collect_core_health(db=db, redis_client=redis_client, settings=settings)
    if any(component.get("status") != "ok" for component in components.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded", components=components)
    return HealthResponse(status="ok", components=components)


@router.get("/healthz", response_model=HealthResponse)
def healthz(
    response: Response,
    db: Session = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    return health_ready(response=response, db=db, redis_client=redis_client, settings=settings)
