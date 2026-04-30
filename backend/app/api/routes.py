from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import ValidationError
from redis import Redis
from sqlalchemy import desc, select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.core.config import Settings, get_settings
from app.core.network import extract_client_ip, rate_limit_identity
from app.db.session import get_db
from app.models.generation_job import GenerationJob, JobStatus
from app.schemas.job import (
    CreateJobRequest,
    CreateJobResponse,
    GalleryItem,
    HealthResponse,
    JobDetailResponse,
    PublicMetaResponse,
)
from app.services.rate_limit import GenerationRateLimiter
from app.services.reference_images import ReferenceImagePayload, ReferenceImageValidationError, validate_reference_image
from app.services.redis_client import get_redis
from app.services.storage import MinioStorageService, StorageError
from app.services.tasks import generate_image_task


logger = logging.getLogger(__name__)
router = APIRouter()


@dataclass(slots=True)
class ParsedCreateJobPayload:
    request: CreateJobRequest
    reference_image: ReferenceImagePayload | None = None


@router.get("/meta/public", response_model=PublicMetaResponse)
def get_public_meta(settings: Settings = Depends(get_settings)) -> PublicMetaResponse:
    return PublicMetaResponse(
        site_name=settings.site_name,
        prompt_max_length=settings.prompt_max_length,
        polling_interval_ms=settings.polling_interval_ms,
        example_prompts=settings.example_prompts,
        models=settings.public_models,
    )


@router.post("/jobs", response_model=CreateJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    request: Request,
    db: Session = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
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

    enabled_models = {item["id"]: item for item in settings.public_models if item["enabled"]}
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
    client_identity = rate_limit_identity(extract_client_ip(request))
    rate_limit_result = limiter.check(client_identity)
    if not rate_limit_result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="当前 IP 请求过于频繁，请 1 分钟后再试。",
        )

    job = GenerationJob(
        prompt=prompt,
        model=payload.model,
        size=payload.size,
        aspect_ratio=payload.aspect_ratio or "auto",
        status=JobStatus.QUEUED,
    )
    db.add(job)
    try:
        db.flush()
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


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
def get_job(job_id: str, db: Session = Depends(get_db)) -> JobDetailResponse:
    job = db.get(GenerationJob, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在。")
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


@router.get("/gallery", response_model=list[GalleryItem])
def get_gallery(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[GalleryItem]:
    stmt = (
        select(GenerationJob)
        .where(GenerationJob.status == JobStatus.SUCCEEDED)
        .order_by(desc(GenerationJob.finished_at))
        .limit(settings.gallery_limit)
    )
    jobs = db.scalars(stmt).all()
    return [
        GalleryItem(
            job_id=job.id,
            image_url=job.public_url or "",
            prompt=job.prompt,
            revised_prompt=job.revised_prompt,
            model=job.model,
            size=job.size,
            aspect_ratio=job.aspect_ratio,
            finished_at=job.finished_at,
        )
        for job in jobs
        if job.public_url and job.finished_at
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
