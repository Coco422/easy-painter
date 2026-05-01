from __future__ import annotations

import logging
from datetime import datetime, timezone

from celery import Celery
from celery.exceptions import MaxRetriesExceededError

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.models.generation_job import GenerationJob, JobStatus
from app.services.model_service import load_provider_for_model
from app.services.storage import MinioStorageService, StorageError
from app.services.upstream import GeneratedImageResult, ReferenceImageForUpstream, UpstreamImageClient, UpstreamServiceError


configure_logging()
settings = get_settings()
logger = logging.getLogger(__name__)

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
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@celery_app.task(name="app.generate_image_task", bind=True, max_retries=2)
def generate_image_task(self, job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(GenerationJob, job_id)
        if not job:
            logger.warning("Generation job missing.")
            return

        if job.status == JobStatus.SUCCEEDED:
            return

        job.status = JobStatus.PROCESSING
        job.started_at = job.started_at or utcnow()
        job.error_message = None
        db.commit()

        try:
            provider_config = load_provider_for_model(db, job.model)
            if not provider_config:
                _mark_failed(db=db, job=job, message="模型配置不存在，请联系管理员。")
                return

            storage = MinioStorageService()
            reference_image = None
            if job.reference_image_key and job.reference_image_content_type:
                stored_reference = storage.download_reference_image(
                    job.reference_image_key,
                    job.reference_image_content_type,
                )
                reference_image = ReferenceImageForUpstream(
                    filename=job.reference_image_filename or "reference",
                    content_type=stored_reference.content_type,
                    image_bytes=stored_reference.image_bytes,
                )

            result = UpstreamImageClient(provider_config.as_dict()).generate_image(
                prompt=job.prompt,
                model=job.model,
                size=job.size,
                aspect_ratio=job.aspect_ratio,
                reference_image=reference_image,
            )
            stored = storage.upload_generated_image(
                job_id=job.id,
                image_bytes=result.image_bytes,
                content_type=result.content_type,
            )
            _mark_succeeded(db=db, job=job, result=result, object_key=stored.object_key, public_url=stored.public_url)
        except UpstreamServiceError as exc:
            logger.warning("Upstream generation error for job %s retryable=%s: %s", job.id, exc.retryable, exc.user_message)
            if exc.retryable:
                try:
                    raise self.retry(exc=exc, countdown=15 * (self.request.retries + 1))
                except MaxRetriesExceededError:
                    _mark_failed(db=db, job=job, message="生成服务暂时不可用，请稍后重试。")
            else:
                _mark_failed(db=db, job=job, message=exc.user_message)
        except StorageError:
            logger.exception("Storage error for generation job %s.", job.id)
            try:
                raise self.retry(countdown=15 * (self.request.retries + 1))
            except MaxRetriesExceededError:
                _mark_failed(db=db, job=job, message="图片保存失败，请稍后重试。")
        except Exception:
            logger.exception("Unexpected generation task failure for job %s.", job.id)
            _mark_failed(db=db, job=job, message="生成任务执行失败，请稍后重试。")
    finally:
        db.close()


def _mark_succeeded(
    *,
    db,
    job: GenerationJob,
    result: GeneratedImageResult,
    object_key: str,
    public_url: str,
) -> None:
    job.status = JobStatus.SUCCEEDED
    job.revised_prompt = result.revised_prompt
    job.object_key = object_key
    job.public_url = public_url
    job.provider_job_meta = result.provider_meta
    job.finished_at = utcnow()
    job.error_message = None
    db.commit()
    logger.info("Generation job %s succeeded object_key=%s.", job.id, object_key)


def _mark_failed(*, db, job: GenerationJob, message: str) -> None:
    job.status = JobStatus.FAILED
    job.error_message = message
    job.finished_at = utcnow()
    db.commit()
    logger.info("Generation job %s failed message=%s.", job.id, message)
