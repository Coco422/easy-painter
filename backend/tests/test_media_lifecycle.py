from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.generation_job import GenerationJob, JobStatus
from app.models.inspiration import Inspiration
from app.models.media import MediaDeletionStatus, MediaDeletionTask, MediaState
from app.models.reference_image import ReferenceImage
from app.services import media_lifecycle
from app.services.storage import StorageError


def make_session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_expired_media_is_hidden_queued_and_retried_without_touching_inspirations(monkeypatch):
    db = make_session()
    now = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
    job = GenerationJob(
        id="job-expired",
        prompt="expired",
        model="model",
        status=JobStatus.SUCCEEDED,
        object_key="generated/job.jpg",
        media_state=MediaState.AVAILABLE,
        media_expires_at=now - timedelta(seconds=1),
    )
    live_job = GenerationJob(
        id="job-live",
        prompt="live",
        model="model",
        status=JobStatus.PROCESSING,
        object_key="generated/live.jpg",
        media_state=MediaState.AVAILABLE,
        media_expires_at=now - timedelta(days=1),
    )
    reference = ReferenceImage(
        id="ref-expired",
        user_id="user-1",
        object_key="references/ref.png",
        content_type="image/png",
        filename="ref.png",
        media_state=MediaState.AVAILABLE,
        media_expires_at=now - timedelta(seconds=1),
    )
    inspiration = Inspiration(
        id="permanent",
        title="permanent",
        prompt="prompt",
        image_url="/api/v1/inspirations/permanent/file",
        image_object_key="inspirations/permanent.jpg",
        source="imported",
        media_state=MediaState.AVAILABLE,
    )
    db.add_all([job, live_job, reference, inspiration])
    db.commit()

    assert media_lifecycle.scan_expired_media(db, now=now) == 2
    assert media_lifecycle.scan_expired_media(db, now=now) == 0
    assert job.media_state == MediaState.DELETE_PENDING
    assert reference.media_state == MediaState.DELETE_PENDING
    assert live_job.media_state == MediaState.AVAILABLE
    assert inspiration.media_state == MediaState.AVAILABLE

    class FlakyStorage:
        def __init__(self):
            self.fail_job = True

        def delete_object(self, key: str) -> None:
            if key == "generated/job.jpg" and self.fail_job:
                self.fail_job = False
                raise StorageError("temporary")

        def delete_reference_image(self, _: str) -> None:
            return None

    storage = FlakyStorage()
    monkeypatch.setattr(media_lifecycle, "MinioStorageService", lambda: storage)
    first = media_lifecycle.process_media_deletions(db, now=now)
    assert first == {"completed": 1, "retried": 1}
    assert job.object_key == "generated/job.jpg"
    assert reference.media_state == MediaState.DELETED

    second = media_lifecycle.process_media_deletions(db, now=now + timedelta(hours=2))
    assert second == {"completed": 1, "retried": 0}
    assert job.object_key is None
    assert job.media_state == MediaState.DELETED
    assert inspiration.image_object_key == "inspirations/permanent.jpg"
    assert inspiration.media_state == MediaState.AVAILABLE
    db.close()


def test_manual_inspiration_deletion_task_clears_permanent_object(monkeypatch):
    db = make_session()
    now = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
    inspiration = Inspiration(
        id="curated",
        title="curated",
        prompt="prompt",
        image_url="/api/v1/inspirations/curated/file",
        image_object_key="inspirations/curated.jpg",
        source="community-curated",
        media_state=MediaState.DELETE_PENDING,
        deleted_at=now,
    )
    task = MediaDeletionTask(
        bucket_type="media",
        object_key=inspiration.image_object_key,
        resource_type="inspiration",
        resource_id=inspiration.id,
        next_attempt_at=now,
    )
    db.add_all([inspiration, task])
    db.commit()

    class Storage:
        def delete_object(self, _: str) -> None:
            return None

        def delete_reference_image(self, _: str) -> None:
            raise AssertionError("wrong bucket")

    monkeypatch.setattr(media_lifecycle, "MinioStorageService", Storage)
    assert media_lifecycle.process_media_deletions(db, now=now) == {"completed": 1, "retried": 0}
    assert task.status == MediaDeletionStatus.COMPLETED
    assert inspiration.image_object_key is None
    assert inspiration.media_state == MediaState.DELETED
    db.close()


def test_enqueue_deletion_is_idempotent_without_rolling_back_caller_transaction():
    db = make_session()
    job = GenerationJob(
        id="job-with-duplicate-cleanup",
        prompt="keep caller transaction",
        model="model",
        status=JobStatus.SUCCEEDED,
    )
    db.add(job)

    for _ in range(2):
        media_lifecycle.enqueue_deletion(
            db,
            bucket_type="media",
            object_key="generated/duplicate.jpg",
            resource_type="generation_job",
            resource_id=job.id,
        )
    db.commit()

    tasks = db.scalars(
        select(MediaDeletionTask).where(
            MediaDeletionTask.bucket_type == "media",
            MediaDeletionTask.object_key == "generated/duplicate.jpg",
        )
    ).all()
    assert len(tasks) == 1
    assert db.get(GenerationJob, job.id) is not None
    db.close()
