from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.generation_job import GenerationJob, JobStatus
from app.models.media import MediaState
from app.models.outbox_event import OutboxEvent, OutboxEventStatus
from app.services.billing import refund_job_charge, settle_job_charge
from app.services.media_lifecycle import enqueue_terminal_reference_cleanup
from app.services.upstream import GeneratedImageResult


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def claim_generation_job(
    db: Session,
    *,
    job_id: str,
    execution_token: str,
    is_retry: bool,
    lease_seconds: int,
    now: datetime | None = None,
) -> GenerationJob | None:
    claimed_at = now or utcnow()
    job = db.scalar(select(GenerationJob).where(GenerationJob.id == job_id).with_for_update())
    if not job:
        return None
    if job.status == JobStatus.QUEUED:
        job.status = JobStatus.PROCESSING
        job.execution_token = execution_token
        job.started_at = job.started_at or claimed_at
    elif not (
        is_retry
        and job.status == JobStatus.PROCESSING
        and job.execution_token == execution_token
    ):
        return None
    job.lease_expires_at = claimed_at + timedelta(seconds=lease_seconds)
    job.error_message = None
    db.commit()
    db.refresh(job)
    return job


def mark_generation_succeeded(
    db: Session,
    *,
    job_id: str,
    execution_token: str,
    result: GeneratedImageResult,
    object_key: str,
    public_url: str,
    now: datetime | None = None,
) -> bool:
    finished_at = now or utcnow()
    job = db.scalar(select(GenerationJob).where(GenerationJob.id == job_id).with_for_update())
    if not job or job.status != JobStatus.PROCESSING or job.execution_token != execution_token:
        db.rollback()
        return False

    job.status = JobStatus.SUCCEEDED
    job.revised_prompt = result.revised_prompt
    job.object_key = object_key
    # Browser links are short-lived API capabilities generated on demand.  The
    # legacy column remains only for a forward-compatible rollout.
    job.public_url = None
    job.media_state = MediaState.AVAILABLE
    job.media_size_bytes = len(result.image_bytes)
    job.media_content_type = result.content_type
    job.provider_job_meta = result.provider_meta
    job.finished_at = finished_at
    if job.generated_retention_hours_snapshot:
        job.media_expires_at = finished_at + timedelta(hours=job.generated_retention_hours_snapshot)
    job.error_message = None
    job.execution_token = None
    job.lease_expires_at = None
    settle_job_charge(db, job_id=job.id, now=finished_at)
    enqueue_terminal_reference_cleanup(db, job)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return True


def mark_generation_failed(
    db: Session,
    *,
    job_id: str,
    message: str,
    execution_token: str | None = None,
    now: datetime | None = None,
) -> bool:
    failed_at = now or utcnow()
    job = db.scalar(select(GenerationJob).where(GenerationJob.id == job_id).with_for_update())
    if not job or job.status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
        db.rollback()
        return False
    if execution_token is not None and job.execution_token != execution_token:
        db.rollback()
        return False

    job.status = JobStatus.FAILED
    job.error_message = message
    job.finished_at = failed_at
    job.execution_token = None
    job.lease_expires_at = None
    refund_job_charge(db, job_id=job.id, reason=message, now=failed_at)
    enqueue_terminal_reference_cleanup(db, job)
    for event in db.scalars(
        select(OutboxEvent).where(
            OutboxEvent.aggregate_id == job.id,
            OutboxEvent.status == OutboxEventStatus.PENDING,
        )
    ).all():
        event.status = OutboxEventStatus.DISCARDED
        event.last_error = "job already failed"
    db.commit()
    return True


def update_retry_message(
    db: Session,
    *,
    job_id: str,
    execution_token: str,
    message: str,
    lease_seconds: int,
    now: datetime | None = None,
) -> bool:
    updated_at = now or utcnow()
    job = db.scalar(select(GenerationJob).where(GenerationJob.id == job_id).with_for_update())
    if not job or job.status != JobStatus.PROCESSING or job.execution_token != execution_token:
        db.rollback()
        return False
    job.error_message = message
    job.lease_expires_at = updated_at + timedelta(seconds=lease_seconds)
    db.commit()
    return True
