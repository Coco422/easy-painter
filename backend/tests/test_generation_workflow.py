from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.api import routes
from app.core.config import Settings
from app.db.base import Base
from app.models.generation_job import GenerationJob, JobStatus
from app.models.user import User
from app.services import dispatcher, tasks
from app.services.storage import StoredImage
from app.services.upstream import GeneratedImageResult


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
        status=JobStatus.QUEUED,
        user_id="user-1",
        provider_id_snapshot="provider-snapshot",
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

    provider_calls = []
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(
        tasks,
        "load_provider_by_id",
        lambda db, provider_id: provider_calls.append(provider_id) or FakeProviderConfig(),
    )
    monkeypatch.setattr(
        tasks,
        "load_provider_for_model",
        lambda db, model: pytest.fail("snapshot jobs must not follow the model's current provider"),
    )
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
    assert provider_calls == ["provider-snapshot"]
    db.close()


def test_retryable_upstream_error_records_retry_message_before_next_retry(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    job = GenerationJob(
        prompt="画一朵花",
        model="gpt-image-2-c",
        size="1024x1024",
        status=JobStatus.QUEUED,
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


def test_manual_interrupted_job_recovery_marks_live_jobs_failed():
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
    assert db.get(GenerationJob, queued_job.id).error_message == tasks.INTERRUPTED_JOB_MESSAGE
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


def test_generation_commit_failure_cleans_late_object_and_fails_job(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    job = GenerationJob(
        prompt="画一朵花",
        model="gpt-image-2-c",
        size="1024x1024",
        status=JobStatus.QUEUED,
        user_id="user-1",
    )
    db.add(job)
    db.commit()
    job_id = job.id
    db.close()

    class FakeProviderConfig:
        def as_dict(self):
            return {"base_url": "https://test.example.com", "api_key": "test-key"}

    class SuccessfulClient:
        def __init__(self, provider_config):
            self.provider_config = provider_config

        def generate_image(self, **kwargs):
            return GeneratedImageResult(
                image_bytes=b"image",
                content_type="image/png",
                revised_prompt=None,
                provider_meta={"source": "test"},
            )

    class FakeStorage:
        deleted = []

        def upload_generated_image(self, **kwargs):
            return StoredImage(object_key="generated/job.png", public_url="/media/generated/job.png")

        def delete_object(self, object_key):
            self.deleted.append(object_key)

    session_class = session_factory.class_
    original_commit = session_class.commit
    commit_calls = 0

    def fail_success_commit(self):
        nonlocal commit_calls
        commit_calls += 1
        if commit_calls == 2:
            raise RuntimeError("database commit failed")
        return original_commit(self)

    monkeypatch.setattr(session_class, "commit", fail_success_commit)
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "load_provider_for_model", lambda db, model: FakeProviderConfig())
    monkeypatch.setattr(tasks, "MinioStorageService", FakeStorage)
    monkeypatch.setattr(tasks, "UpstreamImageClient", SuccessfulClient)

    tasks.generate_image_task.push_request(retries=0, id="test-task")
    try:
        tasks.generate_image_task.run(job_id)
    finally:
        tasks.generate_image_task.pop_request()

    db = session_factory()
    saved_job = db.get(GenerationJob, job_id)
    assert saved_job.status == JobStatus.FAILED
    assert saved_job.public_url is None
    assert FakeStorage.deleted == ["generated/job.png"]
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
    )

    assert [job.job_id for job in jobs] == [newer_job.id, older_job.id]
    assert [job.status for job in jobs] == [JobStatus.PROCESSING.value, JobStatus.QUEUED.value]
    db.close()


def test_watchdog_marks_stale_live_jobs_failed(monkeypatch):
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

    db.close()
    monkeypatch.setattr(dispatcher, "SessionLocal", session_factory)
    monkeypatch.setattr(
        dispatcher,
        "settings",
        Settings(generation_job_stale_seconds=60, generation_queue_stale_seconds=60),
    )

    changed = dispatcher.run_watchdog(
        now=datetime(2026, 5, 7, 8, 31, 30, tzinfo=timezone.utc)
    )

    db = session_factory()
    assert changed == 1
    saved_stale_job = db.get(GenerationJob, stale_job.id)
    assert saved_stale_job.status == JobStatus.FAILED
    assert saved_stale_job.error_message == "生成任务长时间没有响应，灵感丝线已自动退回。"
    assert saved_stale_job.finished_at.replace(tzinfo=timezone.utc) == datetime(2026, 5, 7, 8, 31, 30, tzinfo=timezone.utc)
    assert db.get(GenerationJob, fresh_job.id).status == JobStatus.QUEUED
    db.close()


def test_get_job_requires_ownership():
    session_factory = make_session_factory()
    db = session_factory()
    job = GenerationJob(
        id="11111111-1111-1111-1111-111111111111",
        prompt="旧任务",
        model="gpt-image-2-c",
        size="1024x1024",
        status=JobStatus.SUCCEEDED,
        user_id="user-1",
        created_at=datetime(2026, 5, 7, 8, 0, tzinfo=timezone.utc),
        started_at=datetime(2026, 5, 7, 8, 1, tzinfo=timezone.utc),
    )
    db.add(job)
    db.commit()

    owner = User(id="user-1", username="owner", password_hash="hash")
    stranger = User(id="user-2", username="stranger", password_hash="hash")
    db.add_all([owner, stranger])
    db.commit()

    response = routes.get_job(job_id=job.id, db=db, current_user=owner)
    assert response.status == JobStatus.SUCCEEDED.value
    with pytest.raises(HTTPException) as exc_info:
        routes.get_job(job_id=job.id, db=db, current_user=stranger)
    assert exc_info.value.status_code == 404
    db.close()


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('outcome', ['success', 'failure', 'retry'])
def test_worker_loads_ordered_reference_snapshots_and_cleans_only_terminal_jobs(monkeypatch, legacy, outcome):
    from sqlalchemy import select
    from app.models.media import MediaDeletionTask
    from app.services.storage import StoredReferenceImage

    session_factory = make_session_factory()
    db = session_factory()
    refs = [{'object_key': f'references/{i}.png', 'content_type': 'image/png', 'filename': 'same.png'} for i in range(1 if legacy else 3)]
    job = GenerationJob(prompt='combine', model='gpt-image-2-b', status=JobStatus.QUEUED,
                        reference_image_key=refs[0]['object_key'], reference_image_content_type='image/png',
                        reference_image_filename='same.png', reference_images=None if legacy else refs)
    db.add(job)
    db.commit()
    job_id = job.id
    db.close()
    received = []
    class Provider:
        def as_dict(self): return {}
    class Client:
        def __init__(self, config): pass
        def generate_image(self, **kwargs):
            received.extend(kwargs['reference_images'])
            if outcome != 'success':
                raise tasks.UpstreamServiceError('test upstream failure', retryable=outcome == 'retry')
            return GeneratedImageResult(b'output', 'image/png', None, {})
    class Storage:
        def download_reference_image(self, key, content_type):
            return StoredReferenceImage(key, key.encode(), content_type)
        def upload_generated_image(self, **kwargs):
            return StoredImage('generated/output.png', '')
    monkeypatch.setattr(tasks, 'SessionLocal', session_factory)
    monkeypatch.setattr(tasks, 'load_provider_for_model', lambda db, model: Provider())
    monkeypatch.setattr(tasks, 'UpstreamImageClient', Client)
    monkeypatch.setattr(tasks, 'MinioStorageService', Storage)
    tasks.generate_image_task.push_request(retries=0, id='multi-test')
    try:
        if outcome == 'retry':
            with pytest.raises(tasks.UpstreamServiceError):
                tasks.generate_image_task.run(job_id)
        else:
            tasks.generate_image_task.run(job_id)
    finally:
        tasks.generate_image_task.pop_request()
    assert [item.image_bytes for item in received] == [item['object_key'].encode() for item in refs]
    db = session_factory()
    job = db.get(GenerationJob, job_id)
    deletions = db.scalars(select(MediaDeletionTask)).all()
    if outcome == 'retry':
        assert job.status == JobStatus.PROCESSING
        assert not deletions
        assert job.reference_image_key == refs[0]['object_key']
        assert job.reference_images == (None if legacy else refs)
    else:
        assert job.status == (JobStatus.SUCCEEDED if outcome == 'success' else JobStatus.FAILED)
        assert job.reference_images is None
        assert job.reference_image_key is None
        assert {item.object_key for item in deletions} == {item['object_key'] for item in refs}
    db.close()
