from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.api import routes
from app.core.config import Settings
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


def test_worker_startup_marks_interrupted_live_jobs_failed():
    session_factory = make_session_factory()
    db = session_factory()
    queued_job = GenerationJob(
        id="11111111-1111-1111-1111-111111111111",
        prompt="排队任务",
        model="gpt-image-2-c",
        size="1024x1024",
        status=JobStatus.QUEUED,
        user_id="user-1",
    )
    processing_job = GenerationJob(
        id="22222222-2222-2222-2222-222222222222",
        prompt="处理中任务",
        model="gpt-image-2-c",
        size="1024x1024",
        status=JobStatus.PROCESSING,
        user_id="user-1",
    )
    succeeded_job = GenerationJob(
        id="33333333-3333-3333-3333-333333333333",
        prompt="成功任务",
        model="gpt-image-2-c",
        size="1024x1024",
        status=JobStatus.SUCCEEDED,
        user_id="user-1",
    )
    db.add_all([queued_job, processing_job, succeeded_job])
    db.commit()
    db.close()

    changed_count = tasks.mark_interrupted_generation_jobs_failed(session_factory=session_factory)

    db = session_factory()
    assert changed_count == 2
    assert db.get(GenerationJob, queued_job.id).status == JobStatus.FAILED
    assert db.get(GenerationJob, processing_job.id).status == JobStatus.FAILED
    assert db.get(GenerationJob, succeeded_job.id).status == JobStatus.SUCCEEDED
    assert db.get(GenerationJob, queued_job.id).error_message == "服务重启后生成任务已中断，请重新生成。"
    db.close()


def test_generation_task_ignores_terminal_jobs(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    job = GenerationJob(
        prompt="画一朵花",
        model="gpt-image-2-c",
        size="1024x1024",
        status=JobStatus.FAILED,
        user_id="user-1",
        error_message="服务重启后生成任务已中断，请重新生成。",
        finished_at=datetime(2026, 5, 7, 8, 0, tzinfo=timezone.utc),
    )
    db.add(job)
    db.commit()
    job_id = job.id
    db.close()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("terminal jobs must not call upstream")

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "load_provider_for_model", fail_if_called)

    tasks.generate_image_task.run(job_id)

    db = session_factory()
    saved_job = db.get(GenerationJob, job_id)
    assert saved_job.status == JobStatus.FAILED
    assert saved_job.error_message == "服务重启后生成任务已中断，请重新生成。"
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

    jobs = routes.list_active_jobs(
        db=db,
        current_user=user,
        settings=Settings(),
        now=base_time + timedelta(seconds=20),
    )

    assert [job.job_id for job in jobs] == [newer_job.id, older_job.id]
    assert [job.status for job in jobs] == [JobStatus.PROCESSING.value, JobStatus.QUEUED.value]
    db.close()


def test_list_active_jobs_marks_stale_live_jobs_failed():
    session_factory = make_session_factory()
    db = session_factory()
    user = User(id="user-1", username="ray", password_hash="hash")
    stale_job = GenerationJob(
        id="11111111-1111-1111-1111-111111111111",
        prompt="旧任务",
        model="gpt-image-2-c",
        size="1024x1024",
        status=JobStatus.PROCESSING,
        user_id=user.id,
        created_at=datetime(2026, 5, 7, 8, 0, tzinfo=timezone.utc),
        started_at=datetime(2026, 5, 7, 8, 1, tzinfo=timezone.utc),
    )
    fresh_job = GenerationJob(
        id="22222222-2222-2222-2222-222222222222",
        prompt="新任务",
        model="gpt-image-2-c",
        size="1024x1024",
        status=JobStatus.QUEUED,
        user_id=user.id,
        created_at=datetime(2026, 5, 7, 8, 31, tzinfo=timezone.utc),
    )
    db.add_all([user, stale_job, fresh_job])
    db.commit()

    jobs = routes.list_active_jobs(
        db=db,
        current_user=user,
        settings=Settings(generation_job_stale_seconds=60),
        now=datetime(2026, 5, 7, 8, 31, 30, tzinfo=timezone.utc),
    )

    assert [job.job_id for job in jobs] == [fresh_job.id]
    saved_stale_job = db.get(GenerationJob, stale_job.id)
    assert saved_stale_job.status == JobStatus.FAILED
    assert saved_stale_job.error_message == "生成任务长时间没有响应，可能已在服务重启或 worker 中断后丢失，请重新生成。"
    assert saved_stale_job.finished_at == datetime(2026, 5, 7, 8, 31, 30, tzinfo=timezone.utc)
    db.close()


def test_get_job_marks_stale_live_job_failed():
    session_factory = make_session_factory()
    db = session_factory()
    job = GenerationJob(
        id="11111111-1111-1111-1111-111111111111",
        prompt="旧任务",
        model="gpt-image-2-c",
        size="1024x1024",
        status=JobStatus.PROCESSING,
        user_id="user-1",
        created_at=datetime(2026, 5, 7, 8, 0, tzinfo=timezone.utc),
        started_at=datetime(2026, 5, 7, 8, 1, tzinfo=timezone.utc),
    )
    db.add(job)
    db.commit()

    response = routes.get_job(
        job_id=job.id,
        db=db,
        settings=Settings(generation_job_stale_seconds=60),
        now=datetime(2026, 5, 7, 8, 31, 30, tzinfo=timezone.utc),
    )

    assert response.status == JobStatus.FAILED.value
    assert response.error_message == "生成任务长时间没有响应，可能已在服务重启或 worker 中断后丢失，请重新生成。"
    db.close()
