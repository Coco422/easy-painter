from app.api import admin_routes
from app.db import init_db
from app.models.generation_job import JobStatus
from app.models.media import MediaDeletionTask, MediaState


def test_init_db_only_runs_seed_steps(monkeypatch):
    calls = []
    monkeypatch.setattr(init_db, "_ensure_default_user", lambda: calls.append("user"))
    monkeypatch.setattr(init_db, "_seed_providers_and_models", lambda: calls.append("models"))

    init_db.init_db()

    assert calls == ["user", "models"]


def test_admin_delete_job_queues_media_and_preserves_job():
    class FakeJob:
        id = "job-1"
        object_key = "generated/job.png"
        reference_image_key = "references/job/source.png"
        status = JobStatus.SUCCEEDED
        media_state = MediaState.AVAILABLE
        deleted_at = None
        is_public = True

    class FakeDb:
        def __init__(self):
            self.committed = False
            self.added = []

        def get(self, model, job_id):
            assert job_id == "job-1"
            return FakeJob()

        def scalar(self, statement):
            return None

        def add(self, value):
            self.added.append(value)

        def commit(self):
            self.committed = True

    db = FakeDb()

    admin_routes.admin_delete_job("job-1", db=db, _={})

    assert len(db.added) == 2
    assert all(isinstance(item, MediaDeletionTask) for item in db.added)
    assert {item.object_key for item in db.added} == {
        "generated/job.png",
        "references/job/source.png",
    }
    assert db.committed
