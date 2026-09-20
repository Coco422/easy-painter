from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import require_current_user
from app.db.session import get_db
from app.models.canvas import CanvasAsset, CanvasProject
from app.models.user import User
from app.models.user_group import UserGroup, VIP_GROUP_CODE
from app.schemas.canvas import CreateCanvas, SaveCanvas
from app.services.media_lifecycle import enqueue_deletion
from app.services.storage import MinioStorageService, StorageError

canvas_router = APIRouter(prefix="/canvas", tags=["canvas"])
MAX_PROJECTS = 20
MAX_BYTES = 256 * 1024 * 1024
MAX_PROJECT_BYTES = 128 * 1024 * 1024
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_ASSETS = 1000


def lock_owner(db: Session, user: User) -> User:
    owner = db.scalar(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if owner is None:
        raise HTTPException(401, "请重新登录。")
    return owner


def can_write(db: Session, user: User) -> bool:
    group = db.get(UserGroup, user.group_code)
    return bool(group and group.code == VIP_GROUP_CODE and group.is_enabled)


def require_write(db: Session, user: User):
    if not can_write(db, user):
        raise HTTPException(
            403, "VIP 用户组可使用云端保存；本地画布与已有云端项目的恢复不受影响。"
        )


def owned_project(db: Session, user: User, project_id: str) -> CanvasProject:
    project = db.scalar(
        select(CanvasProject).where(
            CanvasProject.id == project_id, CanvasProject.user_id == user.id
        )
    )
    if not project:
        raise HTTPException(404, "云端画布不存在。")
    return project


def usage(db: Session, user: User) -> int:
    return db.scalar(
        select(func.coalesce(func.sum(CanvasAsset.size_bytes), 0))
        .join(CanvasProject)
        .where(CanvasProject.user_id == user.id)
    )


def describe(db: Session, project: CanvasProject, *, detail=False):
    assets = db.scalars(
        select(CanvasAsset).where(CanvasAsset.project_id == project.id)
    ).all()
    result = {
        "id": project.id,
        "title": project.title,
        "version": project.version,
        "updated_at": project.updated_at,
        "bytes": sum(a.size_bytes for a in assets),
    }
    if detail:
        result.update(document=project.document, asset_ids=[a.digest for a in assets])
    return result


@canvas_router.get("/capabilities")
def capabilities(
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "can_write": can_write(db, current_user),
        "max_projects": MAX_PROJECTS,
        "max_bytes": MAX_BYTES,
        "used_bytes": usage(db, current_user),
    }


@canvas_router.get("/projects")
def list_projects(
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    response.headers["Cache-Control"] = "private, no-store"
    projects = db.scalars(
        select(CanvasProject)
        .where(CanvasProject.user_id == current_user.id)
        .order_by(CanvasProject.updated_at.desc())
    ).all()
    return [describe(db, project) for project in projects]


@canvas_router.post("/projects")
def create_project(
    body: CreateCanvas,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    response.headers["Cache-Control"] = "private, no-store"
    user = lock_owner(db, current_user)
    require_write(db, user)
    project = db.get(CanvasProject, str(body.id))
    if project:
        if project.user_id != user.id:
            raise HTTPException(404, "云端画布不存在。")
        return describe(db, project, detail=True)
    count = db.scalar(
        select(func.count())
        .select_from(CanvasProject)
        .where(CanvasProject.user_id == user.id)
    )
    if count >= MAX_PROJECTS:
        raise HTTPException(
            409, f"云端最多保存 {MAX_PROJECTS} 张画布，请导出并删除不再需要的云端项目。"
        )
    project = CanvasProject(
        id=str(body.id), user_id=user.id, title=body.title, version=0
    )
    db.add(project)
    db.commit()
    return describe(db, project, detail=True)


@canvas_router.get("/projects/{project_id}")
def get_project(
    project_id: UUID,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    response.headers["Cache-Control"] = "private, no-store"
    return describe(db, owned_project(db, current_user, str(project_id)), detail=True)


@canvas_router.put("/projects/{project_id}")
def save_project(
    project_id: UUID,
    body: SaveCanvas,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    response.headers["Cache-Control"] = "private, no-store"
    user = lock_owner(db, current_user)
    require_write(db, user)
    project = owned_project(db, user, str(project_id))
    if project.version != body.expected_version:
        raise HTTPException(409, "云端版本已更新，请先恢复云端副本再对比保存。")
    if body.document.id != project_id:
        raise HTTPException(422, "画布 ID 不匹配。")
    document = body.document.model_dump(mode="json", by_alias=True, exclude_none=True)
    if len(body.document.model_dump_json().encode()) > 2 * 1024 * 1024:
        raise HTTPException(413, "画布结构超过 2 MB，请拆分画布。")
    existing = set(
        db.scalars(
            select(CanvasAsset.digest).where(CanvasAsset.project_id == project.id)
        ).all()
    )
    if not body.document.asset_ids().issubset(existing):
        raise HTTPException(409, "部分素材尚未上传，画布未保存。请重试同步。")
    project.version += 1
    document.update(ownerId=user.id, cloudVersion=project.version, cloudEnabled=True)
    project.title = body.document.title
    project.document = document
    project.updated_at = datetime.now(timezone.utc)
    db.commit()
    return describe(db, project, detail=True)


@canvas_router.put("/projects/{project_id}/assets/{digest}")
def upload_asset(
    project_id: UUID,
    digest: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    user = lock_owner(db, current_user)
    require_write(db, user)
    project = owned_project(db, user, str(project_id))
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise HTTPException(422, "素材标识无效。")
    existing = db.get(CanvasAsset, (project.id, digest))
    if existing:
        return {"id": digest, "bytes": existing.size_bytes}
    asset_count = db.scalar(
        select(func.count())
        .select_from(CanvasAsset)
        .where(CanvasAsset.project_id == project.id)
    )
    if asset_count >= MAX_ASSETS:
        raise HTTPException(409, "每张云端画布最多保存 1000 份素材，请另建画布。")
    data = file.file.read(MAX_IMAGE_BYTES + 1)
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "单张素材不得超过 12 MB。")
    if sha256(data).hexdigest() != digest:
        raise HTTPException(422, "素材校验失败。")
    try:
        with Image.open(BytesIO(data)) as image:
            mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(
                image.format
            )
            if not mime or image.width * image.height > 40_000_000:
                raise ValueError("unsupported image")
            image.verify()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
    ) as exc:
        raise HTTPException(
            422, "请选择有效的 PNG、JPEG 或 WebP 图片（最多 4000 万像素）。"
        ) from exc
    project_bytes = db.scalar(
        select(func.coalesce(func.sum(CanvasAsset.size_bytes), 0)).where(
            CanvasAsset.project_id == project.id
        )
    )
    if (
        usage(db, user) + len(data) > MAX_BYTES
        or project_bytes + len(data) > MAX_PROJECT_BYTES
    ):
        raise HTTPException(409, "云端素材容量不足，请导出并删除不再需要的云端项目。")
    key = f"canvas/{user.id}/{project.id}/{uuid4().hex}"
    storage = MinioStorageService()
    try:
        storage.upload_canvas_asset(key, data, mime)
    except StorageError as exc:
        # Compensate even if an object-store timeout happened after the write.
        enqueue_deletion(
            db,
            bucket_type="media",
            object_key=key,
            resource_type="canvas_asset",
            resource_id=project.id,
        )
        db.commit()
        raise HTTPException(503, "云端素材暂时无法保存，请稍后重试。") from exc
    db.add(
        CanvasAsset(
            project_id=project.id,
            digest=digest,
            object_key=key,
            content_type=mime,
            size_bytes=len(data),
        )
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        enqueue_deletion(
            db,
            bucket_type="media",
            object_key=key,
            resource_type="canvas_asset",
            resource_id=project.id,
        )
        db.commit()
        raise
    return {"id": digest, "bytes": len(data)}


@canvas_router.get("/projects/{project_id}/assets/{digest}")
def get_asset(
    project_id: UUID,
    digest: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    project = owned_project(db, current_user, str(project_id))
    asset = db.get(CanvasAsset, (project.id, digest))
    if not asset:
        raise HTTPException(404, "云端素材不存在。")
    storage = MinioStorageService()
    try:
        stream = storage.open_object(asset.object_key)
    except StorageError as exc:
        raise HTTPException(503, "云端素材暂时无法读取。") from exc
    return StreamingResponse(
        storage.iter_response(stream),
        media_type=asset.content_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Length": str(asset.size_bytes),
            "X-Content-Type-Options": "nosniff",
        },
    )


def delete_owned_project(db: Session, project: CanvasProject):
    for asset in db.scalars(
        select(CanvasAsset).where(CanvasAsset.project_id == project.id)
    ).all():
        enqueue_deletion(
            db,
            bucket_type="media",
            object_key=asset.object_key,
            resource_type="canvas_asset",
            resource_id=project.id,
        )
        db.delete(asset)
    db.delete(project)


@canvas_router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    user = lock_owner(db, current_user)
    delete_owned_project(db, owned_project(db, user, str(project_id)))
    db.commit()
    return Response(status_code=204)
