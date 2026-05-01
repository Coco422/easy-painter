from app.api import admin_routes
from app.db import init_db


def test_generation_job_user_id_index_is_created_before_connection_closes(monkeypatch):
    class FakeInspector:
        def get_columns(self, table_name):
            assert table_name == "generation_jobs"
            return [{"name": "id"}, {"name": "size"}, {"name": "aspect_ratio"}]

    class FakeConnection:
        def __init__(self):
            self.closed = False
            self.statements = []

        def execute(self, statement):
            assert not self.closed
            self.statements.append(str(statement))

    class FakeBegin:
        def __init__(self, connection):
            self.connection = connection

        def __enter__(self):
            return self.connection

        def __exit__(self, exc_type, exc, tb):
            self.connection.closed = True
            return False

    class FakeEngine:
        def __init__(self):
            self.connection = FakeConnection()

        def begin(self):
            return FakeBegin(self.connection)

    fake_engine = FakeEngine()
    monkeypatch.setattr(init_db, "engine", fake_engine)
    monkeypatch.setattr(init_db, "inspect", lambda engine: FakeInspector())

    init_db._ensure_generation_job_columns()

    assert any(
        "CREATE INDEX IF NOT EXISTS ix_generation_jobs_user_id" in item
        for item in fake_engine.connection.statements
    )


def test_admin_delete_job_removes_reference_image_from_reference_bucket(monkeypatch):
    class FakeJob:
        object_key = "generated/job.png"
        reference_image_key = "references/job/source.png"

    class FakeDb:
        def __init__(self):
            self.deleted = None
            self.committed = False

        def get(self, model, job_id):
            assert job_id == "job-1"
            return FakeJob()

        def delete(self, job):
            self.deleted = job

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
