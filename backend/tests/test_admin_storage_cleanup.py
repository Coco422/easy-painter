from app.api import admin_routes
from app.db import init_db


def test_init_db_only_runs_seed_steps(monkeypatch):
    calls = []
    monkeypatch.setattr(init_db, "_ensure_default_user", lambda: calls.append("user"))
    monkeypatch.setattr(init_db, "_seed_providers_and_models", lambda: calls.append("models"))

    init_db.init_db()

    assert calls == ["user", "models"]


def test_admin_delete_job_removes_reference_image_from_reference_bucket(monkeypatch):
    class FakeJob:
        id = "job-1"
        object_key = "generated/job.png"
        reference_image_key = "references/job/source.png"

    class FakeScalars:
        def all(self):
            return []

    class FakeDb:
        def __init__(self):
            self.deleted = None
            self.committed = False

        def get(self, model, job_id):
            assert job_id == "job-1"
            return FakeJob()

        def delete(self, job):
            self.deleted = job

        def scalars(self, statement):
            return FakeScalars()

        def commit(self):
            self.committed = True

    class FakeStorage:
        def __init__(self):
            self.deleted_objects = []
            self.deleted_references = []

        def delete_object(self, object_key):
            self.deleted_objects.append(object_key)

        def delete_reference_image(self, object_key):
            self.deleted_references.append(object_key)

    storage = FakeStorage()
    monkeypatch.setattr(admin_routes, "MinioStorageService", lambda: storage)
    db = FakeDb()

    admin_routes.admin_delete_job("job-1", db=db, _={})

    assert storage.deleted_objects == ["generated/job.png"]
    assert storage.deleted_references == ["references/job/source.png"]
    assert db.deleted is not None
    assert db.committed
