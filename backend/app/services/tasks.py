from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from celery import Celery
from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.models.generation_job import GenerationJob, JobStatus
from app.services.job_lifecycle import (
    claim_generation_job,
    mark_generation_failed,
    mark_generation_succeeded,
    update_retry_message,
)
from app.services.model_service import (
    load_failover_providers_for_model,
    load_size_route_providers_for_model,
    load_primary_upstream_model_id,
    load_provider_by_id,
    load_provider_for_model,
)
from app.services.media_lifecycle import enqueue_deletion
from app.services.reference_images import job_reference_images
from app.services.storage import MinioStorageService, StorageError
from app.services.upstream import ReferenceImageForUpstream, UpstreamImageClient, UpstreamServiceError
from app.services.model_pricing import size_pricing_tier


configure_logging()
settings = get_settings()
logger = logging.getLogger(__name__)
INTERRUPTED_JOB_MESSAGE = "服务中断导致生成任务未完成，灵感丝线已自动退回。"
LIVE_JOB_STATUSES = (JobStatus.QUEUED, JobStatus.PROCESSING)

celery_app = Celery(
    "easy_painter",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _generate_with_failover(
    db,
    *,
    job: GenerationJob,
    provider_config: dict,
    reference_images: list[ReferenceImageForUpstream],
):
    routed = load_size_route_providers_for_model(db, job.model, job.size)
    if routed:
        last_error: UpstreamServiceError | None = None
        for provider in routed:
            if len(reference_images) > provider.max_reference_images:
                logger.info(
                    "Skipping size route provider=%s because it supports at most %s reference images.",
                    provider.name,
                    provider.max_reference_images,
                )
                continue
            logger.info(
                "Routing image generation size=%s model=%s to provider=%s model=%s.",
                job.size,
                job.model,
                provider.name,
                provider.model_id,
            )
            try:
                return UpstreamImageClient(provider.config.as_dict()).generate_image(
                    prompt=job.prompt,
                    model=provider.model_id,
                    size=job.size,
                    quality=getattr(job, "quality", None),
                    aspect_ratio=job.aspect_ratio,
                    reference_images=reference_images,
                )
            except UpstreamServiceError as error:
                last_error = error
                if not error.failover_safe:
                    raise
        if last_error:
            raise last_error

    # 4K is an explicitly paid, provider-specific capability. Never silently
    # send it to the ordinary 1K channel when the dedicated route is missing.
    if size_pricing_tier(job.size) == "4k":
        raise UpstreamServiceError(
            "当前模型的 4K 专用渠道不可用，请稍后选择 1K 或 2K。",
            retryable=False,
        )

    request = {
        "prompt": job.prompt,
        "model": load_primary_upstream_model_id(job.model),
        "size": job.size,
        "quality": getattr(job, "quality", None),
        "aspect_ratio": job.aspect_ratio,
        "reference_images": reference_images,
    }
    try:
        return UpstreamImageClient(provider_config).generate_image(**request)
    except UpstreamServiceError as primary_error:
        if not primary_error.failover_safe:
            raise

        fallbacks = load_failover_providers_for_model(db, job.model)
        if not fallbacks:
            raise

        last_error = primary_error
        for fallback in fallbacks:
            if len(reference_images) > fallback.max_reference_images:
                logger.info(
                    "Skipping fallback provider=%s because it supports at most %s reference images.",
                    fallback.name,
                    fallback.max_reference_images,
                )
                continue
            logger.warning(
                "Primary upstream failed with a known unsuccessful response; trying configured fallback provider=%s model=%s.",
                fallback.name,
                fallback.model_id,
            )
            try:
                return UpstreamImageClient(fallback.config.as_dict()).generate_image(
                    **{**request, "model": fallback.model_id}
                )
            except UpstreamServiceError as fallback_error:
                last_error = fallback_error
                logger.warning(
                    "Fallback upstream failed provider=%s model=%s failover_safe=%s.",
                    fallback.name,
                    fallback.model_id,
                    fallback_error.failover_safe,
                )
                if not fallback_error.failover_safe:
                    raise

        raise last_error


@celery_app.task(name="app.generate_image_task", bind=True, max_retries=2)
def generate_image_task(self, job_id: str) -> None:
    db = SessionLocal()
    execution_token = str(self.request.id or uuid4())
    storage: MinioStorageService | None = None
    stored_object_key: str | None = None
    try:
        job = claim_generation_job(
            db,
            job_id=job_id,
            execution_token=execution_token,
            is_retry=self.request.retries > 0,
            lease_seconds=settings.generation_job_stale_seconds,
        )
        if not job:
            logger.info("Generation job %s was already claimed or settled.", job_id)
            return

        try:
            provider_config = (
                load_provider_by_id(db, job.provider_id_snapshot)
                if job.provider_id_snapshot
                else load_provider_for_model(db, job.model)
            )
            if not provider_config:
                mark_generation_failed(
                    db,
                    job_id=job.id,
                    execution_token=execution_token,
                    message="模型配置不存在，请联系管理员。",
                )
                return

            storage = MinioStorageService()
            reference_images = []
            for reference in job_reference_images(job):
                stored_reference = storage.download_reference_image(
                    reference["object_key"], reference["content_type"],
                )
                reference_images.append(ReferenceImageForUpstream(
                    filename=reference["filename"],
                    content_type=stored_reference.content_type,
                    image_bytes=stored_reference.image_bytes,
                ))

            result = _generate_with_failover(
                db,
                job=job,
                provider_config=provider_config.as_dict(),
                reference_images=reference_images,
            )
            stored = storage.upload_generated_image(
                job_id=job.id,
                image_bytes=result.image_bytes,
                content_type=result.content_type,
            )
            stored_object_key = stored.object_key
            if not mark_generation_succeeded(
                db,
                job_id=job.id,
                execution_token=execution_token,
                result=result,
                object_key=stored.object_key,
                public_url=stored.public_url,
            ):
                try:
                    storage.delete_object(stored.object_key)
                except StorageError:
                    enqueue_deletion(
                        db,
                        bucket_type="media",
                        object_key=stored.object_key,
                        resource_type="orphan_generation_result",
                        resource_id=job.id,
                    )
                    db.commit()
                stored_object_key = None
                logger.warning("Discarded late result for already settled job %s.", job.id)
                return
            stored_object_key = None
            logger.info("Generation job %s succeeded object_key=%s.", job.id, stored.object_key)
            # The delivered image and charge are already committed. Preview
            # failures must never enter the generation/refund error path.
            try:
                from app.services.thumbnails import prepare_thumbnail
                source = db.scalar(select(GenerationJob).where(GenerationJob.id == job.id)
                                   .with_for_update().execution_options(populate_existing=True))
                prepare_thumbnail(db, source, data=result.image_bytes, storage=storage)
            except Exception:
                db.rollback()
                logger.warning("Preview deferred for delivered job %s.", job.id)
        except UpstreamServiceError as exc:
            logger.warning(
                "Upstream generation error for job %s retryable=%s: %s",
                job.id,
                exc.retryable,
                exc.user_message,
            )
            if exc.retryable and _can_retry(self):
                retry_number = self.request.retries + 1
                retry_total = self.max_retries or retry_number
                update_retry_message(
                    db,
                    job_id=job.id,
                    execution_token=execution_token,
                    message=f"{exc.user_message}正在自动重试（{retry_number}/{retry_total}）。",
                    lease_seconds=settings.generation_job_stale_seconds,
                )
                raise self.retry(exc=exc, countdown=15 * retry_number)
            mark_generation_failed(
                db,
                job_id=job.id,
                execution_token=execution_token,
                message="生成服务暂时不可用，请稍后重试。" if exc.retryable else exc.user_message,
            )
        except StorageError:
            logger.exception("Storage error for generation job %s.", job.id)
            if _can_retry(self):
                retry_number = self.request.retries + 1
                retry_total = self.max_retries or retry_number
                update_retry_message(
                    db,
                    job_id=job.id,
                    execution_token=execution_token,
                    message=f"图片保存失败，正在自动重试（{retry_number}/{retry_total}）。",
                    lease_seconds=settings.generation_job_stale_seconds,
                )
                raise self.retry(countdown=15 * retry_number)
            mark_generation_failed(
                db,
                job_id=job.id,
                execution_token=execution_token,
                message="图片保存失败，请稍后重试。",
            )
        except Exception:
            logger.exception("Unexpected generation task failure for job %s.", job.id)
            db.rollback()
            orphan_object_key: str | None = None
            if storage and stored_object_key:
                try:
                    storage.delete_object(stored_object_key)
                except StorageError:
                    logger.exception("Failed to clean generated object %s after task failure.", stored_object_key)
                    orphan_object_key = stored_object_key
                stored_object_key = None
            mark_generation_failed(
                db,
                job_id=job.id,
                execution_token=execution_token,
                message="生成任务执行失败，请稍后重试。",
            )
            if orphan_object_key:
                enqueue_deletion(
                    db,
                    bucket_type="media",
                    object_key=orphan_object_key,
                    resource_type="orphan_generation_result",
                    resource_id=job.id,
                )
                db.commit()
    finally:
        db.close()


def mark_interrupted_generation_jobs_failed(
    *,
    session_factory=SessionLocal,
    now: datetime | None = None,
) -> int:
    db = session_factory()
    try:
        job_ids = [
            job.id
            for job in db.scalars(
                select(GenerationJob).where(GenerationJob.status.in_(LIVE_JOB_STATUSES))
            ).all()
        ]
    finally:
        db.close()

    changed = 0
    for job_id in job_ids:
        db = session_factory()
        try:
            if mark_generation_failed(
                db,
                job_id=job_id,
                message=INTERRUPTED_JOB_MESSAGE,
                now=now,
            ):
                changed += 1
        finally:
            db.close()
    return changed


def _can_retry(task) -> bool:
    max_retries = task.max_retries
    if max_retries is None:
        return True
    return task.request.retries < max_retries


@celery_app.task(name="app.backfill_media_thumbnails", ignore_result=True)
def backfill_media_thumbnails() -> None:
    from app.services.thumbnails import backfill_thumbnails
    with SessionLocal() as db:
        backfill_thumbnails(db)


@celery_app.task(name="app.reconcile_recharges", ignore_result=True)
def reconcile_recharges() -> None:
    from app.services.payments import reconcile_recharge_orders
    reconcile_recharge_orders(session_factory=SessionLocal, settings=settings)
