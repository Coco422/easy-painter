from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.generation_job import GenerationJob, JobStatus
from app.models.inspiration import Inspiration
from app.models.media import MediaDeletionStatus, MediaDeletionTask, MediaState
from app.models.reference_image import ReferenceImage
from app.services.storage import MinioStorageService, StorageError


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def enqueue_deletion(
    db: Session,
    *,
    bucket_type: str,
    object_key: str,
    resource_type: str,
    resource_id: str | None,
    now: datetime | None = None,
) -> None:
    values = {
        "id": str(uuid4()),
        "bucket_type": bucket_type,
        "object_key": object_key,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "status": MediaDeletionStatus.PENDING,
        "attempts": 0,
        "next_attempt_at": now or utcnow(),
        "created_at": now or utcnow(),
    }
    try:
        dialect_name = db.get_bind().dialect.name
    except (AttributeError, NotImplementedError):
        # Small unit-test adapters do not expose a SQLAlchemy bind. Production
        # always takes the atomic PostgreSQL path below.
        task = db.scalar(
            select(MediaDeletionTask).where(
                MediaDeletionTask.bucket_type == bucket_type,
                MediaDeletionTask.object_key == object_key,
            )
        )
        if task is None:
            db.add(MediaDeletionTask(**values))
        return

    if dialect_name == "postgresql":
        statement = pg_insert(MediaDeletionTask).values(**values).on_conflict_do_nothing(
            index_elements=["bucket_type", "object_key"]
        )
    elif dialect_name == "sqlite":
        statement = sqlite_insert(MediaDeletionTask).values(**values).on_conflict_do_nothing(
            index_elements=["bucket_type", "object_key"]
        )
    else:
        task = db.scalar(
            select(MediaDeletionTask).where(
                MediaDeletionTask.bucket_type == bucket_type,
                MediaDeletionTask.object_key == object_key,
            )
        )
        if task is None:
            db.add(MediaDeletionTask(**values))
        return
    db.execute(statement)


def scan_expired_media(db: Session, *, now: datetime | None = None) -> int:
    now = now or utcnow()
    changed = 0
    jobs = db.scalars(select(GenerationJob).where(
        GenerationJob.status == JobStatus.SUCCEEDED,
        GenerationJob.media_state == MediaState.AVAILABLE,
        GenerationJob.media_expires_at.is_not(None),
        GenerationJob.media_expires_at <= now,
    ).with_for_update(skip_locked=True)).all()
    for job in jobs:
        if job.object_key:
            enqueue_deletion(db, bucket_type="media", object_key=job.object_key, resource_type="generation_job", resource_id=job.id, now=now)
        job.media_state = MediaState.DELETE_PENDING
        changed += 1
    refs = db.scalars(select(ReferenceImage).where(
        ReferenceImage.media_state == MediaState.AVAILABLE,
        ReferenceImage.media_expires_at.is_not(None),
        ReferenceImage.media_expires_at <= now,
    ).with_for_update(skip_locked=True)).all()
    for ref in refs:
        enqueue_deletion(db, bucket_type="reference", object_key=ref.object_key, resource_type="reference_image", resource_id=ref.id, now=now)
        ref.media_state = MediaState.DELETE_PENDING
        changed += 1
    db.commit()
    return changed


def enqueue_terminal_reference_cleanup(db: Session, job: GenerationJob) -> None:
    """Job-specific reference copies cannot outlive terminal jobs unnecessarily."""
    if job.reference_image_key and job.status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
        enqueue_deletion(db, bucket_type="reference", object_key=job.reference_image_key, resource_type="job_reference", resource_id=job.id)
        job.reference_image_key = None


def process_media_deletions(db: Session, *, now: datetime | None = None, limit: int = 100) -> dict[str, int]:
    now = now or utcnow()
    tasks = db.scalars(select(MediaDeletionTask).where(
        MediaDeletionTask.status == MediaDeletionStatus.PENDING,
        MediaDeletionTask.next_attempt_at <= now,
    ).order_by(MediaDeletionTask.next_attempt_at).limit(limit).with_for_update(skip_locked=True)).all()
    storage = MinioStorageService()
    counts = {"completed": 0, "retried": 0}
    for task in tasks:
        try:
            if task.bucket_type == "reference":
                storage.delete_reference_image(task.object_key)
            else:
                storage.delete_object(task.object_key)
        except StorageError as exc:
            task.attempts += 1
            task.last_error = str(exc)[:1000]
            task.next_attempt_at = now + timedelta(seconds=min(3600, 2 ** min(task.attempts, 12)))
            counts["retried"] += 1
            continue
        task.status = MediaDeletionStatus.COMPLETED
        task.completed_at = now
        task.last_error = None
        if task.resource_type == "generation_job" and task.resource_id:
            job = db.get(GenerationJob, task.resource_id)
            if job:
                job.object_key = None
                job.public_url = None
                job.media_state = MediaState.DELETED
                job.media_deleted_at = now
        elif task.resource_type == "reference_image" and task.resource_id:
            ref = db.get(ReferenceImage, task.resource_id)
            if ref:
                ref.media_state = MediaState.DELETED
                ref.media_deleted_at = now
        elif task.resource_type == "inspiration" and task.resource_id:
            inspiration = db.get(Inspiration, task.resource_id)
            if inspiration:
                inspiration.image_object_key = None
                inspiration.image_url = ""
                inspiration.media_state = MediaState.DELETED
        counts["completed"] += 1
    db.commit()
    return counts
