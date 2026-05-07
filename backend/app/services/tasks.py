from __future__ import annotations

import logging
from datetime import datetime, timezone

from celery import Celery
from celery.signals import worker_ready
from sqlalchemy import select

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
INTERRUPTED_JOB_MESSAGE = "服务重启后生成任务已中断，请重新生成。"
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

        if job.status not in LIVE_JOB_STATUSES:
            logger.info("Generation job %s already settled status=%s.", job.id, job.status.value)
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
            if exc.retryable and _can_retry(self):
                retry_number = self.request.retries + 1
                retry_total = self.max_retries or retry_number
                job.error_message = f"{exc.user_message}正在自动重试（{retry_number}/{retry_total}）。"
                db.commit()
                raise self.retry(exc=exc, countdown=15 * retry_number)
            _mark_failed(
                db=db,
                job=job,
                message="生成服务暂时不可用，请稍后重试。" if exc.retryable else exc.user_message,
            )
        except StorageError:
            logger.exception("Storage error for generation job %s.", job.id)
            if _can_retry(self):
                retry_number = self.request.retries + 1
                retry_total = self.max_retries or retry_number
                job.error_message = f"图片保存失败，正在自动重试（{retry_number}/{retry_total}）。"
                db.commit()
                raise self.retry(countdown=15 * retry_number)
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


def mark_interrupted_generation_jobs_failed(
    *,
    session_factory=SessionLocal,
    now: datetime | None = None,
) -> int:
    db = session_factory()
    failed_at = now or utcnow()
    try:
        jobs = db.scalars(select(GenerationJob).where(GenerationJob.status.in_(LIVE_JOB_STATUSES))).all()
        for job in jobs:
            job.status = JobStatus.FAILED
            job.error_message = INTERRUPTED_JOB_MESSAGE
            job.finished_at = failed_at
        if jobs:
            db.commit()
        return len(jobs)
    finally:
        db.close()


@worker_ready.connect
def _mark_interrupted_jobs_on_worker_ready(**_: object) -> None:
    try:
        failed_count = mark_interrupted_generation_jobs_failed()
    except Exception:
        logger.exception("Failed to mark interrupted generation jobs.")
        return
    if failed_count:
        logger.warning("Marked %s interrupted generation jobs as failed.", failed_count)


def _can_retry(task) -> bool:
    max_retries = task.max_retries
    if max_retries is None:
        return True
    return task.request.retries < max_retries
