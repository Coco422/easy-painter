from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.api import routes
from app.db.base import Base
from app.models.generation_job import GenerationJob, JobStatus
from app.models.user import User
from app.services import tasks


def make_session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def test_retryable_upstream_error_marks_job_failed_after_retries_are_exhausted(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    job = GenerationJob(
        prompt="画一朵花",
        model="gpt-image-2-c",
        size="1024x1024",
        status=JobStatus.PROCESSING,
        user_id="user-1",
    )
    db.add(job)
    db.commit()
    job_id = job.id
    db.close()

    class FakeProviderConfig:
        def as_dict(self):
            return {"base_url": "https://test.example.com", "api_key": "test-key"}

    class TimeoutClient:
        def __init__(self, provider_config):
            self.provider_config = provider_config

        def generate_image(self, **kwargs):
            raise tasks.UpstreamServiceError("生成服务响应超时，请稍后再试。", retryable=True)

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "load_provider_for_model", lambda db, model: FakeProviderConfig())
    monkeypatch.setattr(tasks, "MinioStorageService", lambda: object())
    monkeypatch.setattr(tasks, "UpstreamImageClient", TimeoutClient)

    tasks.generate_image_task.push_request(retries=tasks.generate_image_task.max_retries, id="test-task")
    try:
        tasks.generate_image_task.run(job_id)
    finally:
        tasks.generate_image_task.pop_request()

    db = session_factory()
    saved_job = db.get(GenerationJob, job_id)
    assert saved_job.status == JobStatus.FAILED
    assert saved_job.error_message == "生成服务暂时不可用，请稍后重试。"
    assert saved_job.finished_at is not None
    db.close()


def test_retryable_upstream_error_records_retry_message_before_next_retry(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    job = GenerationJob(
        prompt="画一朵花",
        model="gpt-image-2-c",
        size="1024x1024",
        status=JobStatus.PROCESSING,
        user_id="user-1",
    )
    db.add(job)
    db.commit()
    job_id = job.id
    db.close()

    class FakeProviderConfig:
        def as_dict(self):
            return {"base_url": "https://test.example.com", "api_key": "test-key"}

    class TimeoutClient:
        def __init__(self, provider_config):
            self.provider_config = provider_config

        def generate_image(self, **kwargs):
            raise tasks.UpstreamServiceError("生成服务响应超时，请稍后再试。", retryable=True)

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "load_provider_for_model", lambda db, model: FakeProviderConfig())
    monkeypatch.setattr(tasks, "MinioStorageService", lambda: object())
    monkeypatch.setattr(tasks, "UpstreamImageClient", TimeoutClient)

    tasks.generate_image_task.push_request(retries=0, id="test-task")
    try:
        with pytest.raises(tasks.UpstreamServiceError):
            tasks.generate_image_task.run(job_id)
    finally:
        tasks.generate_image_task.pop_request()

    db = session_factory()
    saved_job = db.get(GenerationJob, job_id)
    assert saved_job.status == JobStatus.PROCESSING
    assert saved_job.error_message == "生成服务响应超时，请稍后再试。正在自动重试（1/2）。"
    assert saved_job.finished_at is None
    db.close()


def test_list_active_jobs_returns_only_current_users_live_jobs():
    session_factory = make_session_factory()
    db = session_factory()
    user = User(id="user-1", username="ray", password_hash="hash")
    other_user = User(id="user-2", username="other", password_hash="hash")
    base_time = datetime(2026, 5, 7, 8, 0, tzinfo=timezone.utc)
    older_job = GenerationJob(
        id="11111111-1111-1111-1111-111111111111",
        prompt="排队任务",
        model="gpt-image-2-c",
        size="1024x1024",
        status=JobStatus.QUEUED,
        user_id=user.id,
        created_at=base_time,
    )
    newer_job = GenerationJob(
        id="22222222-2222-2222-2222-222222222222",
        prompt="处理中任务",
        model="gpt-image-2-c",
        size="1024x1024",
        status=JobStatus.PROCESSING,
        user_id=user.id,
        created_at=base_time + timedelta(seconds=10),
    )
    failed_job = GenerationJob(
        id="33333333-3333-3333-3333-333333333333",
        prompt="失败任务",
        model="gpt-image-2-c",
        size="1024x1024",
        status=JobStatus.FAILED,
        user_id=user.id,
        created_at=base_time + timedelta(seconds=20),
    )
    other_job = GenerationJob(
        id="44444444-4444-4444-4444-444444444444",
        prompt="别人的任务",
        model="gpt-image-2-c",
        size="1024x1024",
        status=JobStatus.PROCESSING,
        user_id=other_user.id,
        created_at=base_time + timedelta(seconds=30),
    )
    db.add_all([user, other_user, older_job, newer_job, failed_job, other_job])
    db.commit()

    jobs = routes.list_active_jobs(db=db, current_user=user)

    assert [job.job_id for job in jobs] == [newer_job.id, older_job.id]
    assert [job.status for job in jobs] == [JobStatus.PROCESSING.value, JobStatus.QUEUED.value]
    db.close()
