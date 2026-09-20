from hashlib import sha256
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import canvas_routes as routes
from app.api import admin_routes
from app.core.auth import require_current_user
from app.db.base import Base
from app.db.session import get_db
from app.models.canvas import CanvasAsset, CanvasProject
from app.models.media import MediaDeletionTask
from app.models.user import User
from app.models.user_group import UserGroup
from app.services.storage import StorageError


@pytest.fixture
def setup(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    db.add_all(
        [UserGroup(code="vip", name="VIP"), UserGroup(code="standard", name="普通")]
    )
    users = [
        User(id=str(uuid4()), username=name, password_hash="test", group_code=group)
        for name, group in [("vip1", "vip"), ("vip2", "vip"), ("normal", "standard")]
    ]
    db.add_all(users)
    db.commit()
    selected = [users[0].id]
    app = FastAPI()
    app.include_router(routes.canvas_router, prefix="/api/v1")

    def session():
        with factory() as current:
            yield current

    def user():
        with factory() as current:
            return current.get(User, selected[0])

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[require_current_user] = user

    class Storage:
        def __init__(self):
            self.objects = {}
            self.uploads = 0
            self.fail = False

        def upload_canvas_asset(self, key, data, mime):
            self.uploads += 1
            if self.fail:
                raise StorageError("test")
            self.objects[key] = data

        def open_object(self, key):
            return BytesIO(self.objects[key])

        def iter_response(self, response):
            try:
                yield response.read()
            finally:
                response.close()

    storage = Storage()
    monkeypatch.setattr(routes, "MinioStorageService", lambda: storage)
    with TestClient(app) as client:
        yield client, db, users, selected, storage
    db.close()
    engine.dispose()


def create(client, title="云端测试"):
    id = str(uuid4())
    r = client.post("/api/v1/canvas/projects", json={"id": id, "title": title})
    assert r.status_code == 200, r.text
    return id


def picture():
    stream = BytesIO()
    Image.new("RGB", (12, 8), "red").save(stream, format="PNG")
    return stream.getvalue()


def document(id, user, digest=None):
    return {
        "schemaVersion": 1,
        "id": id,
        "ownerId": user.id,
        "title": "测试",
        "updatedAt": "2026-09-20T00:00:00Z",
        "revision": 1,
        "cloudVersion": None,
        "cloudEnabled": False,
        "viewport": {"x": 20, "y": 30, "scale": 1},
        "nodes": (
            [
                {
                    "id": "n1",
                    "type": "image",
                    "title": "图",
                    "x": 0,
                    "y": 0,
                    "width": 200,
                    "height": 180,
                    "assetId": digest,
                }
            ]
            if digest
            else []
        ),
        "edges": [],
        "runs": [],
    }


def test_normal_and_disabled_vip_cannot_write(setup):
    c, db, users, who, storage = setup
    who[0] = users[2].id
    assert c.get("/api/v1/canvas/capabilities").json()["can_write"] is False
    assert (
        c.post(
            "/api/v1/canvas/projects", json={"id": str(uuid4()), "title": "bad"}
        ).status_code
        == 403
    )
    who[0] = users[0].id
    db.get(UserGroup, "vip").is_enabled = False
    db.commit()
    assert c.get("/api/v1/canvas/capabilities").json()["can_write"] is False
    assert (
        c.post(
            "/api/v1/canvas/projects", json={"id": str(uuid4()), "title": "bad"}
        ).status_code
        == 403
    )


def test_upload_dedup_save_conflict_and_private_read(setup):
    c, db, users, who, storage = setup
    id = create(c)
    data = picture()
    digest = sha256(data).hexdigest()
    path = f"/api/v1/canvas/projects/{id}"
    payload = {"expected_version": 0, "document": document(id, users[0], digest)}
    assert (
        c.put(path, json=payload).status_code == 409
    )  # Missing media cannot be committed.
    for _ in range(2):
        assert (
            c.put(
                f"{path}/assets/{digest}", files={"file": ("x.png", data, "image/png")}
            ).status_code
            == 200
        )
    assert storage.uploads == 1
    r = c.put(path, json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 1
    assert c.put(path, json=payload).status_code == 409
    r = c.get(f"{path}/assets/{digest}")
    assert r.content == data
    assert r.headers["cache-control"] == "private, no-store"
    assert c.get(path).headers["cache-control"] == "private, no-store"
    who[0] = users[1].id
    assert c.get(path).status_code == 404
    assert c.get(f"{path}/assets/{digest}").status_code == 404
    assert c.delete(path).status_code == 404
    assert (
        c.put(f"{path}/assets/{digest}", files={"file": ("x.png", data)}).status_code
        == 404
    )
    assert (
        c.post(
            "/api/v1/canvas/projects", json={"id": id, "title": "takeover"}
        ).status_code
        == 404
    )
    assert c.get("/api/v1/canvas/projects").json() == []


def test_downgrade_preserves_download_and_delete_but_disallows_writes(setup):
    c, db, users, who, storage = setup
    id = create(c)
    data = picture()
    digest = sha256(data).hexdigest()
    path = f"/api/v1/canvas/projects/{id}"
    c.put(f"{path}/assets/{digest}", files={"file": ("x.png", data)})
    c.put(
        path, json={"expected_version": 0, "document": document(id, users[0], digest)}
    )
    users[0].group_code = "standard"
    db.commit()
    assert c.get(path).status_code == 200
    assert c.get(f"{path}/assets/{digest}").content == data
    assert (
        c.put(
            path,
            json={"expected_version": 1, "document": document(id, users[0], digest)},
        ).status_code
        == 403
    )
    assert c.delete(path).status_code == 204
    assert c.get(path).status_code == 404
    assert db.scalar(select(MediaDeletionTask)).resource_type == "canvas_asset"
    assert db.scalar(select(CanvasAsset)) is None


def test_asset_validation_quota_and_storage_compensation(setup, monkeypatch):
    c, db, users, who, storage = setup
    id = create(c)
    data = picture()
    digest = sha256(data).hexdigest()
    path = f"/api/v1/canvas/projects/{id}/assets"
    assert (
        c.put(f"{path}/{digest}", files={"file": ("x.png", b"bad")}).status_code == 422
    )
    bad = b"<svg></svg>"
    assert (
        c.put(
            f"{path}/{sha256(bad).hexdigest()}", files={"file": ("x.svg", bad)}
        ).status_code
        == 422
    )
    monkeypatch.setattr(routes, "MAX_BYTES", len(data) - 1)
    assert c.put(f"{path}/{digest}", files={"file": ("x.png", data)}).status_code == 409
    assert storage.uploads == 0
    monkeypatch.setattr(routes, "MAX_BYTES", len(data) * 2)
    storage.fail = True
    assert c.put(f"{path}/{digest}", files={"file": ("x.png", data)}).status_code == 503
    assert db.scalar(select(MediaDeletionTask)) is not None
    assert db.scalar(select(CanvasAsset)) is None


def test_project_limit_and_document_validation(setup, monkeypatch):
    c, db, users, who, storage = setup
    monkeypatch.setattr(routes, "MAX_PROJECTS", 1)
    id = create(c)
    assert (
        c.post(
            "/api/v1/canvas/projects", json={"id": str(uuid4()), "title": "excess"}
        ).status_code
        == 409
    )
    p = document(id, users[0])
    p["edges"] = [{"id": "e1", "from": "missing", "to": "also-missing"}]
    assert (
        c.put(
            f"/api/v1/canvas/projects/{id}", json={"expected_version": 0, "document": p}
        ).status_code
        == 422
    )

    p = document(id, users[0])
    p["viewport"]["scale"] = 0
    assert (
        c.put(
            f"/api/v1/canvas/projects/{id}", json={"expected_version": 0, "document": p}
        ).status_code
        == 422
    )


def test_asset_count_limit_preserves_existing_uploads(setup, monkeypatch):
    c, db, users, who, storage = setup
    monkeypatch.setattr(routes, "MAX_ASSETS", 1)
    id = create(c)
    data = picture()
    digest = sha256(data).hexdigest()
    path = f"/api/v1/canvas/projects/{id}/assets"
    assert c.put(f"{path}/{digest}", files={"file": ("x.png", data)}).status_code == 200
    assert c.put(f"{path}/{digest}", files={"file": ("x.png", data)}).status_code == 200
    assert (
        c.put(f"{path}/{'a' * 64}", files={"file": ("x.png", data)}).status_code == 409
    )
    assert storage.uploads == 1


def test_admin_account_deletion_enqueues_cloud_media(setup):
    c, db, users, who, storage = setup
    id = create(c)
    data = picture()
    digest = sha256(data).hexdigest()
    c.put(
        f"/api/v1/canvas/projects/{id}/assets/{digest}", files={"file": ("x.png", data)}
    )
    admin_routes.admin_delete_user(users[0].id, db, {"role": "admin"})
    assert db.scalar(select(CanvasProject)) is None
    assert db.scalar(select(CanvasAsset)) is None
    assert db.scalar(select(MediaDeletionTask)).resource_type == "canvas_asset"
