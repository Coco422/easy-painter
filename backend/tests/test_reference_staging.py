from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.datastructures import Headers, UploadFile
from starlette.requests import Request

from app.api import reference_routes, routes
from app.core.config import Settings
from app.db.base import Base
from app.models.generation_job import GenerationJob
from app.models.reference_image import ReferenceImage
from app.models.user import User
from app.services.storage import StorageError, StoredReferenceImage


PNG_BYTES = b"\x89PNG\r\n\x1a\nsample"
MODEL_DICT = {
    "id": "gpt-image-2-c",
    "label": "GPT-Image-2 C",
    "enabled": True,
    "supports_reference_image": True,
    "supported_sizes": [],
    "credit_cost": 0,
}


def make_session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class FakeStorage:
    def __init__(self):
        self.objects = {}
        self.deleted = []
        self.copies = []
        self.uploads = []

    def upload_staging_reference_image(self, *, image_id, image_bytes, content_type):
        object_key = f"references/2026/08/04/staging/{image_id}.png"
        self.objects[object_key] = image_bytes
        return object_key

    def download_reference_image(self, object_key, content_type):
        return StoredReferenceImage(
            object_key=object_key,
            image_bytes=self.objects[object_key],
            content_type=content_type,
        )

    def delete_reference_image(self, object_key):
        self.deleted.append(object_key)
        self.objects.pop(object_key, None)

    def copy_reference_image_to_job(self, src_key, *, job_id, filename, content_type):
        dest_key = f"references/2026/08/04/{job_id}/sample.png"
        self.objects[dest_key] = self.objects[src_key]
        self.copies.append({"src_key": src_key, "job_id": job_id, "filename": filename, "content_type": content_type})
        return dest_key

    def upload_reference_image(self, *, job_id, image_bytes, content_type, filename):
        dest_key = f"references/2026/08/04/{job_id}/sample.png"
        self.objects[dest_key] = image_bytes
        self.uploads.append({"job_id": job_id, "filename": filename, "content_type": content_type})
        return dest_key


class FakeRateLimiter:
    def __init__(self, **kwargs):
        pass

    def check(self, identity):
        return type("Result", (), {"allowed": True, "remaining": 9})()


class FakeTask:
    def delay(self, job_id):
        pass


def make_upload(filename="sample.png", content_type="image/png", image_bytes=PNG_BYTES):
    return UploadFile(
        file=BytesIO(image_bytes),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def make_json_request(payload: bytes) -> Request:
    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/jobs",
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
    )


def make_multipart_request() -> Request:
    boundary = "----easy-painter-staging-test"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="prompt"\r\n\r\n'
        "hello\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="model"\r\n\r\n'
        "gpt-image-2-c\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="size"\r\n\r\n'
        "1024x1024\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="reference_image"; filename="sample.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode() + PNG_BYTES + b"\r\n" + f"--{boundary}--\r\n".encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/jobs",
            "headers": [(b"content-type", f"multipart/form-data; boundary={boundary}".encode())],
        },
        receive,
    )


def make_user(db, user_id="user-1", username="ray"):
    user = User(id=user_id, username=username, password_hash="hash")
    db.add(user)
    db.commit()
    return user


@pytest.mark.anyio
async def test_upload_list_file_and_delete_flow(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    user = make_user(db)
    storage = FakeStorage()
    monkeypatch.setattr(reference_routes, "MinioStorageService", lambda: storage)

    item = await reference_routes.upload_staged_reference_image(
        file=make_upload(),
        db=db,
        current_user=user,
    )

    assert item.filename == "sample.png"
    assert item.content_type == "image/png"
    assert item.used_count == 0
    assert item.created_at is not None

    items = reference_routes.list_staged_reference_images(db=db, current_user=user)
    assert [entry.id for entry in items] == [item.id]

    response = reference_routes.get_staged_reference_image_file(image_id=item.id, db=db, current_user=user)
    assert response.body == PNG_BYTES
    assert response.media_type == "image/png"
    assert response.headers["Cache-Control"] == "private, max-age=3600"

    reference_routes.delete_staged_reference_image(image_id=item.id, db=db, current_user=user)
    assert reference_routes.list_staged_reference_images(db=db, current_user=user) == []
    assert storage.deleted == [f"references/2026/08/04/staging/{item.id}.png"]

    with pytest.raises(HTTPException) as exc_info:
        reference_routes.get_staged_reference_image_file(image_id=item.id, db=db, current_user=user)
    assert exc_info.value.status_code == 404
    db.close()


@pytest.mark.anyio
async def test_upload_rejects_invalid_image(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    user = make_user(db)
    monkeypatch.setattr(reference_routes, "MinioStorageService", lambda: FakeStorage())

    with pytest.raises(HTTPException) as exc_info:
        await reference_routes.upload_staged_reference_image(
            file=make_upload(filename="sample.gif", content_type="image/gif", image_bytes=b"GIF89a"),
            db=db,
            current_user=user,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "参考图仅支持 PNG、JPEG 或 WebP。"
    db.close()


@pytest.mark.anyio
async def test_upload_evicts_oldest_images_beyond_limit(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    user = make_user(db)
    storage = FakeStorage()
    monkeypatch.setattr(reference_routes, "MinioStorageService", lambda: storage)

    base_time = datetime(2026, 5, 7, 8, 0, tzinfo=timezone.utc)
    for index in range(reference_routes.MAX_REFERENCE_IMAGES_PER_USER):
        object_key = f"references/2026/05/07/staging/old-{index}.png"
        storage.objects[object_key] = PNG_BYTES
        db.add(
            ReferenceImage(
                id=f"old-{index}",
                user_id=user.id,
                object_key=object_key,
                content_type="image/png",
                filename=f"old-{index}.png",
                created_at=base_time + timedelta(seconds=index),
            )
        )
    db.commit()

    item = await reference_routes.upload_staged_reference_image(
        file=make_upload(),
        db=db,
        current_user=user,
    )

    remaining = reference_routes.list_staged_reference_images(db=db, current_user=user)
    assert len(remaining) == reference_routes.MAX_REFERENCE_IMAGES_PER_USER
    remaining_ids = {entry.id for entry in remaining}
    assert "old-0" not in remaining_ids
    assert item.id in remaining_ids
    assert storage.deleted == ["references/2026/05/07/staging/old-0.png"]
    assert "references/2026/05/07/staging/old-0.png" not in storage.objects
    db.close()


@pytest.mark.anyio
async def test_upload_failure_does_not_evict_existing_images(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    user = make_user(db)
    storage = FakeStorage()
    for index in range(reference_routes.MAX_REFERENCE_IMAGES_PER_USER):
        object_key = f"references/2026/05/07/staging/old-{index}.png"
        storage.objects[object_key] = PNG_BYTES
        db.add(
            ReferenceImage(
                id=f"old-{index}",
                user_id=user.id,
                object_key=object_key,
                content_type="image/png",
                filename=f"old-{index}.png",
            )
        )
    db.commit()

    def fail_upload(**kwargs):
        raise StorageError("failed")

    storage.upload_staging_reference_image = fail_upload
    monkeypatch.setattr(reference_routes, "MinioStorageService", lambda: storage)

    with pytest.raises(HTTPException) as exc_info:
        await reference_routes.upload_staged_reference_image(
            file=make_upload(),
            db=db,
            current_user=user,
        )

    assert exc_info.value.status_code == 503
    assert db.scalar(select(func.count()).select_from(ReferenceImage)) == reference_routes.MAX_REFERENCE_IMAGES_PER_USER
    assert storage.deleted == []
    db.close()


@pytest.mark.anyio
async def test_database_failure_cleans_up_new_upload_without_evicting_oldest(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    user = make_user(db)
    storage = FakeStorage()
    old_key = "references/2026/05/07/staging/old.png"
    storage.objects[old_key] = PNG_BYTES
    db.add(
        ReferenceImage(
            id="old",
            user_id=user.id,
            object_key=old_key,
            content_type="image/png",
            filename="old.png",
        )
    )
    db.commit()
    monkeypatch.setattr(reference_routes, "MAX_REFERENCE_IMAGES_PER_USER", 1)
    monkeypatch.setattr(reference_routes, "MinioStorageService", lambda: storage)
    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failed")))

    with pytest.raises(RuntimeError, match="commit failed"):
        await reference_routes.upload_staged_reference_image(
            file=make_upload(),
            db=db,
            current_user=user,
        )

    assert db.get(ReferenceImage, "old") is not None
    assert old_key in storage.objects
    assert storage.deleted and storage.deleted[0] != old_key
    db.close()


@pytest.mark.anyio
async def test_create_job_with_reference_image_id_copies_staging_image(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    user = make_user(db)
    staged = ReferenceImage(
        id="img-1",
        user_id=user.id,
        object_key="references/2026/08/04/staging/img-1.png",
        content_type="image/png",
        filename="sample.png",
    )
    db.add(staged)
    db.commit()

    storage = FakeStorage()
    storage.objects[staged.object_key] = PNG_BYTES
    monkeypatch.setattr(routes, "MinioStorageService", lambda: storage)
    monkeypatch.setattr(routes, "load_models_from_db", lambda db: [MODEL_DICT])
    monkeypatch.setattr(routes, "GenerationRateLimiter", FakeRateLimiter)
    monkeypatch.setattr(routes, "generate_image_task", FakeTask())

    request = make_json_request(
        b'{"prompt":"\xe7\x94\xbb\xe4\xb8\x80\xe6\x9c\xb5\xe8\x8a\xb1","model":"gpt-image-2-c","size":"1024x1024","reference_image_id":"img-1"}'
    )
    response = await routes.create_job(
        request,
        db=db,
        redis_client=object(),
        settings=Settings(),
        current_user=user,
    )

    job = db.get(GenerationJob, response.job_id)
    assert storage.copies == [
        {"src_key": staged.object_key, "job_id": job.id, "filename": "sample.png", "content_type": "image/png"}
    ]
    assert job.reference_image_key == f"references/2026/08/04/{job.id}/sample.png"
    assert job.reference_image_content_type == "image/png"
    assert job.reference_image_filename == "sample.png"
    assert job.reference_image_key in storage.objects

    db.refresh(staged)
    assert staged.used_count == 1
    assert staged.last_used_at is not None
    db.close()


@pytest.mark.anyio
async def test_create_job_keeps_legacy_multipart_reference_upload(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    user = make_user(db)
    storage = FakeStorage()
    monkeypatch.setattr(routes, "MinioStorageService", lambda: storage)
    monkeypatch.setattr(routes, "load_models_from_db", lambda db: [MODEL_DICT])
    monkeypatch.setattr(routes, "GenerationRateLimiter", FakeRateLimiter)
    monkeypatch.setattr(routes, "generate_image_task", FakeTask())

    response = await routes.create_job(
        make_multipart_request(),
        db=db,
        redis_client=object(),
        settings=Settings(),
        current_user=user,
    )

    job = db.get(GenerationJob, response.job_id)
    assert storage.uploads == [
        {"job_id": job.id, "filename": "sample.png", "content_type": "image/png"}
    ]
    assert job.reference_image_key == f"references/2026/08/04/{job.id}/sample.png"
    assert job.reference_image_filename == "sample.png"
    db.close()


@pytest.mark.anyio
async def test_create_job_with_other_users_reference_image_id_returns_422(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    user = make_user(db, user_id="user-1", username="ray")
    other_user = make_user(db, user_id="user-2", username="other")
    staged = ReferenceImage(
        id="img-1",
        user_id=other_user.id,
        object_key="references/2026/08/04/staging/img-1.png",
        content_type="image/png",
        filename="sample.png",
    )
    db.add(staged)
    db.commit()
    monkeypatch.setattr(routes, "load_models_from_db", lambda db: [MODEL_DICT])

    request = make_json_request(
        b'{"prompt":"hello","model":"gpt-image-2-c","size":"1024x1024","reference_image_id":"img-1"}'
    )
    with pytest.raises(HTTPException) as exc_info:
        await routes.create_job(
            request,
            db=db,
            redis_client=object(),
            settings=Settings(),
            current_user=user,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "参考图不存在或已删除。"
    db.close()


@pytest.mark.anyio
async def test_create_job_rejects_reference_image_id_for_unsupported_model(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    user = make_user(db)
    staged = ReferenceImage(
        id="img-1",
        user_id=user.id,
        object_key="references/2026/08/04/staging/img-1.png",
        content_type="image/png",
        filename="sample.png",
    )
    db.add(staged)
    db.commit()
    monkeypatch.setattr(
        routes,
        "load_models_from_db",
        lambda db: [dict(MODEL_DICT, supports_reference_image=False)],
    )

    request = make_json_request(
        b'{"prompt":"hello","model":"gpt-image-2-c","size":"1024x1024","reference_image_id":"img-1"}'
    )
    with pytest.raises(HTTPException) as exc_info:
        await routes.create_job(
            request,
            db=db,
            redis_client=object(),
            settings=Settings(),
            current_user=user,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "当前模型不支持参考图，请切换到支持参考图的模型。"
    db.close()


def test_file_endpoint_rejects_other_users_image(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    user = make_user(db, user_id="user-1", username="ray")
    other_user = make_user(db, user_id="user-2", username="other")
    staged = ReferenceImage(
        id="img-1",
        user_id=other_user.id,
        object_key="references/2026/08/04/staging/img-1.png",
        content_type="image/png",
        filename="sample.png",
    )
    db.add(staged)
    db.commit()
    monkeypatch.setattr(reference_routes, "MinioStorageService", lambda: FakeStorage())

    with pytest.raises(HTTPException) as exc_info:
        reference_routes.get_staged_reference_image_file(image_id=staged.id, db=db, current_user=user)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "图片不存在。"
    db.close()
