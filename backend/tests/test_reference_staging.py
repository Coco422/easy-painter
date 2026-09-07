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

    items = reference_routes.list_staged_reference_images(db=db, current_user=user, page=1, page_size=50)
    assert items.total == 1
    assert [entry.id for entry in items.items] == [item.id]

    response = reference_routes.get_staged_reference_image_file(image_id=item.id, db=db, current_user=user)
    assert response.body == PNG_BYTES
    assert response.media_type == "image/png"
    assert response.headers["Cache-Control"] == "private, max-age=3600"

    reference_routes.delete_staged_reference_image(image_id=item.id, db=db, current_user=user)
    assert reference_routes.list_staged_reference_images(db=db, current_user=user, page=1, page_size=50).items == []
    assert storage.deleted == [f"references/2026/08/04/staging/{item.id}.png"]

    with pytest.raises(HTTPException) as exc_info:
        reference_routes.get_staged_reference_image_file(image_id=item.id, db=db, current_user=user)
    assert exc_info.value.status_code == 404
    db.close()


@pytest.mark.anyio
async def test_manual_delete_keeps_object_when_database_commit_fails(monkeypatch):
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
    object_key = f"references/2026/08/04/staging/{item.id}.png"
    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failed")))

    with pytest.raises(RuntimeError, match="commit failed"):
        reference_routes.delete_staged_reference_image(image_id=item.id, db=db, current_user=user)

    assert db.get(ReferenceImage, item.id) is not None
    assert object_key in storage.objects
    assert storage.deleted == []
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

    with pytest.raises(HTTPException) as exc_info:
        await reference_routes.upload_staged_reference_image(
            file=make_upload(),
            confirm_evict_oldest=False,
            db=db,
            current_user=user,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["max_reference_images"] == 3
    assert exc_info.value.detail["current_count"] == 3
    assert exc_info.value.detail["evict_count"] == 1

    item = await reference_routes.upload_staged_reference_image(
        file=make_upload(),
        confirm_evict_oldest=True,
        db=db,
        current_user=user,
    )

    remaining = reference_routes.list_staged_reference_images(db=db, current_user=user, page=1, page_size=50)
    assert len(remaining.items) == reference_routes.MAX_REFERENCE_IMAGES_PER_USER
    remaining_ids = {entry.id for entry in remaining.items}
    assert item.evicted_image_ids == ["old-0"]
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
            confirm_evict_oldest=True,
            db=db,
            current_user=user,
        )

    assert exc_info.value.status_code == 503
    assert db.scalar(select(func.count()).select_from(ReferenceImage)) == reference_routes.MAX_REFERENCE_IMAGES_PER_USER
    assert storage.deleted == []
    db.close()


@pytest.mark.anyio
async def test_capacity_transaction_failure_cleans_up_new_upload(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    user = make_user(db)
    storage = FakeStorage()
    monkeypatch.setattr(reference_routes, "MinioStorageService", lambda: storage)
    original_execute = db.execute
    monkeypatch.setattr(db, "execute", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("lock failed")))

    with pytest.raises(RuntimeError, match="lock failed"):
        await reference_routes.upload_staged_reference_image(
            file=make_upload(),
            confirm_evict_oldest=True,
            db=db,
            current_user=user,
        )

    monkeypatch.setattr(db, "execute", original_execute)
    assert db.scalar(select(func.count()).select_from(ReferenceImage)) == 0
    assert storage.objects == {}
    # Capacity is checked under the user lock before any upload begins.  A
    # lock failure therefore cannot leave an object that needs compensation.
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
            confirm_evict_oldest=True,
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


@pytest.mark.anyio
@pytest.mark.parametrize('count,limit', [(2, 2), (5, 5), (12, 12)])
async def test_multiple_references_preserve_order_and_same_filename(monkeypatch, count, limit):
    import json

    db = make_session_factory()()
    user = make_user(db)
    storage = FakeStorage()
    ids = [f'img-{index}' for index in range(count)]
    for index, image_id in enumerate(ids):
        key = f'staging/{image_id}.png'
        storage.objects[key] = PNG_BYTES + str(index).encode()
        db.add(ReferenceImage(id=image_id, user_id=user.id, object_key=key,
                              content_type='image/png', filename='same.png'))
    db.commit()
    monkeypatch.setattr(routes, 'MinioStorageService', lambda: storage)
    monkeypatch.setattr(routes, 'load_models_from_db', lambda db: [dict(MODEL_DICT, max_reference_images=limit)])
    monkeypatch.setattr(routes, 'GenerationRateLimiter', FakeRateLimiter)
    response = await routes.create_job(
        make_json_request(json.dumps(dict(prompt='combine', model=MODEL_DICT['id'], reference_image_ids=ids)).encode()),
        db=db, redis_client=object(), settings=Settings(), current_user=user,
    )
    job = db.get(GenerationJob, response.job_id)
    assert len(job.reference_images) == count
    assert len({item['object_key'] for item in job.reference_images}) == count
    assert [storage.objects[item['object_key']] for item in job.reference_images] == [PNG_BYTES + str(i).encode() for i in range(count)]
    assert all(item['filename'] == 'same.png' for item in job.reference_images)
    assert all(db.get(ReferenceImage, image_id).used_count == 1 for image_id in ids)
    db.close()


@pytest.mark.anyio
@pytest.mark.parametrize('limit,count', [(2, 3), (5, 6), (12, 13)])
async def test_multiple_references_limit_rejected_before_copies_or_charges(monkeypatch, limit, count):
    import json

    monkeypatch.setattr(routes, 'load_models_from_db', lambda db: [dict(MODEL_DICT, max_reference_images=limit)])
    with pytest.raises(HTTPException) as error:
        await routes.create_job(
            make_json_request(json.dumps(dict(prompt='test', model=MODEL_DICT['id'], reference_image_ids=[str(i) for i in range(count)])).encode()),
            db=object(), redis_client=object(), settings=Settings(),
        )
    assert error.value.status_code == 422
    assert str(limit) in error.value.detail


@pytest.mark.anyio
async def test_partial_multi_reference_copy_failure_cleans_all_copies(monkeypatch):
    import json

    db = make_session_factory()()
    user = make_user(db)
    storage = FakeStorage()
    for index in range(3):
        key = f'staging/{index}.png'
        storage.objects[key] = PNG_BYTES
        db.add(ReferenceImage(id=str(index), user_id=user.id, object_key=key,
                              content_type='image/png', filename='same.png'))
    db.commit()
    original_copy = storage.copy_reference_image_to_job
    def copy(src_key, **kwargs):
        if src_key == 'staging/2.png':
            raise StorageError('copy failed')
        return original_copy(src_key, **kwargs)
    storage.copy_reference_image_to_job = copy
    monkeypatch.setattr(routes, 'MinioStorageService', lambda: storage)
    monkeypatch.setattr(routes, 'load_models_from_db', lambda db: [MODEL_DICT])
    monkeypatch.setattr(routes, 'GenerationRateLimiter', FakeRateLimiter)
    with pytest.raises(HTTPException) as error:
        await routes.create_job(
            make_json_request(json.dumps(dict(prompt='test', model=MODEL_DICT['id'], reference_image_ids=['0', '1', '2'])).encode()),
            db=db, redis_client=object(), settings=Settings(), current_user=user,
        )
    assert error.value.status_code == 503
    assert len(storage.deleted) == 2
    assert set(storage.objects) == {f'staging/{i}.png' for i in range(3)}
    assert db.scalar(select(func.count()).select_from(GenerationJob)) == 0
    assert all(db.get(ReferenceImage, str(i)).used_count == 0 for i in range(3))
    db.close()


@pytest.mark.anyio
@pytest.mark.parametrize('invalid_kind', ['other_user', 'expired', 'deleted', 'missing'])
async def test_all_multi_reference_ids_are_validated_before_copy(monkeypatch, invalid_kind):
    import json
    from app.models.media import MediaState

    db = make_session_factory()()
    user = make_user(db)
    db.add(ReferenceImage(id='valid', user_id=user.id, object_key='valid.png', content_type='image/png', filename='valid.png'))
    if invalid_kind != 'missing':
        db.add(ReferenceImage(
            id='invalid', user_id='someone-else' if invalid_kind == 'other_user' else user.id,
            object_key='invalid.png', content_type='image/png', filename='invalid.png',
            media_expires_at=datetime.now(timezone.utc) - timedelta(hours=1) if invalid_kind == 'expired' else None,
            media_state=MediaState.DELETE_PENDING if invalid_kind == 'deleted' else MediaState.AVAILABLE,
        ))
    db.commit()
    monkeypatch.setattr(routes, 'load_models_from_db', lambda db: [MODEL_DICT])
    monkeypatch.setattr(routes, 'MinioStorageService', lambda: pytest.fail('must validate all IDs before copying'))
    with pytest.raises(HTTPException) as error:
        await routes.create_job(
            make_json_request(json.dumps(dict(prompt='test', model=MODEL_DICT['id'], reference_image_ids=['valid', 'invalid'])).encode()),
            db=db, redis_client=object(), settings=Settings(), current_user=user,
        )
    assert error.value.status_code == 422
    assert db.scalar(select(func.count()).select_from(GenerationJob)) == 0
    db.close()


@pytest.mark.anyio
async def test_multi_reference_replay_does_not_copy_or_charge_twice(monkeypatch):
    import json
    from app.models.job_charge import JobCharge

    db = make_session_factory()()
    user = make_user(db)
    user.credits = 10
    storage = FakeStorage()
    for image_id in ['a', 'b']:
        storage.objects[image_id] = PNG_BYTES
        db.add(ReferenceImage(id=image_id, user_id=user.id, object_key=image_id, content_type='image/png', filename='same.png'))
    db.commit()
    monkeypatch.setattr(routes, 'MinioStorageService', lambda: storage)
    monkeypatch.setattr(routes, 'load_models_from_db', lambda db: [dict(MODEL_DICT, credit_cost=2)])
    monkeypatch.setattr(routes, 'GenerationRateLimiter', FakeRateLimiter)
    async def submit(ids):
        return await routes.create_job(
            make_json_request(json.dumps(dict(prompt='test', model=MODEL_DICT['id'], reference_image_ids=ids)).encode()),
            idempotency_key='multi-replay', db=db, redis_client=object(), settings=Settings(), current_user=user,
        )
    first = await submit(['a', 'b'])
    second = await submit(['a', 'b'])
    assert first.job_id == second.job_id
    assert len(storage.copies) == 2
    assert db.scalar(select(func.count()).select_from(JobCharge)) == 1
    db.refresh(user)
    assert user.credits == 8
    with pytest.raises(HTTPException) as error:
        await submit(['b', 'a'])
    assert error.value.status_code == 409
    assert len(storage.copies) == 2
    db.close()
