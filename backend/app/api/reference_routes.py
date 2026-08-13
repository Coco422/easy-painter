from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from app.core.auth import require_current_user
from app.db.session import get_db
from app.models.reference_image import ReferenceImage
from app.models.media import MediaState
from app.models.user import User
from app.schemas.reference_image import ReferenceImageItem
from app.services.reference_images import ReferenceImageValidationError, validate_reference_image
from app.services.group_policy import resolve_user_policy
from app.services.media_lifecycle import enqueue_deletion
from app.services.storage import MinioStorageService, StorageError


logger = logging.getLogger(__name__)
reference_router = APIRouter()
# Compatibility export for integrations that previously imported the old global.
# Runtime limits always come from the current user group.
MAX_REFERENCE_IMAGES_PER_USER = 3


def _expired(value: datetime | None) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= datetime.now(timezone.utc)


def _build_reference_image_item(image: ReferenceImage) -> ReferenceImageItem:
    return ReferenceImageItem(
        id=image.id,
        filename=image.filename,
        content_type=image.content_type,
        used_count=image.used_count,
        created_at=image.created_at,
        last_used_at=image.last_used_at,
        media_expires_at=image.media_expires_at,
    )


def _reference_cache_control(image: ReferenceImage) -> str:
    if image.media_expires_at is None:
        return "private, max-age=3600"
    expires_at = image.media_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    remaining = max(0, min(3600, int((expires_at - datetime.now(timezone.utc)).total_seconds())))
    return f"private, max-age={remaining}"


@reference_router.post("/reference-images", response_model=ReferenceImageItem, status_code=status.HTTP_201_CREATED)
async def upload_staged_reference_image(
    file: UploadFile = File(...),
    confirm_evict_oldest: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> ReferenceImageItem:
    image_bytes = await file.read()
    try:
        payload = validate_reference_image(
            filename=file.filename,
            content_type=file.content_type,
            image_bytes=image_bytes,
        )
    except ReferenceImageValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    oldest_images: list[ReferenceImage] = []
    image_id = str(uuid4())
    storage = MinioStorageService()
    object_key: str | None = None
    try:
        # 同一用户的上传必须串行计算容量，否则并发请求可能同时看到 49 张并最终写入 51 张。
        locked_user = db.execute(
            select(User).where(User.id == current_user.id).with_for_update()
        ).scalar_one_or_none()
        if not locked_user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录。")
        _, policy = resolve_user_policy(db, locked_user)
        if policy.max_reference_images == 0:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前用户组不支持参考图。")
        policy_now = datetime.now(timezone.utc)
        existing_count = db.scalar(
            select(func.count()).select_from(ReferenceImage).where(
                ReferenceImage.user_id == current_user.id,
                ReferenceImage.media_state == MediaState.AVAILABLE,
                (ReferenceImage.media_expires_at.is_(None)) | (ReferenceImage.media_expires_at > policy_now),
            )
        ) or 0
        if existing_count >= policy.max_reference_images:
            excess = existing_count - policy.max_reference_images + 1
            if confirm_evict_oldest is not True:
                db.rollback()
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
                    "message": "参考图数量已达上限，请确认后自动淘汰最旧图片。",
                    "max_reference_images": policy.max_reference_images,
                    "current_count": existing_count,
                    "evict_count": excess,
                })
            oldest_images = list(
                db.scalars(
                    select(ReferenceImage)
                    .where(
                        ReferenceImage.user_id == current_user.id,
                        ReferenceImage.media_state == MediaState.AVAILABLE,
                        (ReferenceImage.media_expires_at.is_(None)) | (ReferenceImage.media_expires_at > policy_now),
                    )
                    .order_by(asc(ReferenceImage.created_at))
                    .limit(excess)
                ).all()
            )
        try:
            object_key = storage.upload_staging_reference_image(
                image_id=image_id,
                image_bytes=payload.image_bytes,
                content_type=payload.content_type,
            )
        except StorageError:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="参考图保存失败，请稍后重试。") from None
        image = ReferenceImage(
            id=image_id, user_id=current_user.id, object_key=object_key,
            content_type=payload.content_type, filename=payload.filename,
            group_code_snapshot=policy.code, group_name_snapshot=policy.name,
            retention_hours_snapshot=policy.reference_retention_hours,
            media_expires_at=policy_now + timedelta(hours=policy.reference_retention_hours),
            media_size_bytes=len(payload.image_bytes), media_state=MediaState.AVAILABLE,
        )
        db.add(image)
        for old_image in oldest_images:
            old_image.media_state = MediaState.DELETE_PENDING
            enqueue_deletion(db, bucket_type="reference", object_key=old_image.object_key, resource_type="reference_image", resource_id=old_image.id)
        db.commit()
    except Exception:
        db.rollback()
        try:
            if object_key:
                storage.delete_reference_image(object_key)
        except Exception:
            logger.warning("Failed to clean up newly uploaded MinIO reference %s", object_key)
        raise

    db.refresh(image)
    # Queueing is authoritative; eager deletion is only a best-effort cost
    # optimization and preserves the prior immediate-cleanup behavior.
    for old_image in oldest_images:
        try:
            storage.delete_reference_image(old_image.object_key)
        except StorageError:
            logger.warning("Failed to eagerly delete evicted reference %s", old_image.object_key)
    return _build_reference_image_item(image)


@reference_router.get("/reference-images", response_model=list[ReferenceImageItem])
def list_staged_reference_images(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> list[ReferenceImageItem]:
    images = db.scalars(
        select(ReferenceImage)
        .where(ReferenceImage.user_id == current_user.id)
        .where(ReferenceImage.media_state == MediaState.AVAILABLE)
        .where((ReferenceImage.media_expires_at.is_(None)) | (ReferenceImage.media_expires_at > datetime.now(timezone.utc)))
        .order_by(desc(ReferenceImage.created_at))
    ).all()
    return [_build_reference_image_item(image) for image in images]


@reference_router.get("/reference-images/{image_id}/file")
def get_staged_reference_image_file(
    image_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Response:
    image = db.get(ReferenceImage, image_id)
    if not image or image.user_id != current_user.id or image.media_state != MediaState.AVAILABLE or _expired(image.media_expires_at):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片不存在。")
    storage = MinioStorageService()
    if not hasattr(storage, "open_object") or not hasattr(storage, "iter_response"):
        # Compatibility for small test/dummy storage adapters; production
        # storage always takes the streaming path above.
        stored = storage.download_reference_image(image.object_key, image.content_type)
        return Response(content=stored.image_bytes, media_type=image.content_type, headers={"Cache-Control": _reference_cache_control(image)})
    from fastapi.responses import StreamingResponse
    try:
        opened = storage.open_object(image.object_key, reference=True)
    except StorageError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="参考图读取失败。",
            headers={"Cache-Control": "no-store"},
        ) from None
    return StreamingResponse(
        storage.iter_response(opened),
        media_type=image.content_type,
        headers={"Cache-Control": _reference_cache_control(image)},
    )


@reference_router.delete("/reference-images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_staged_reference_image(
    image_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> None:
    image = db.get(ReferenceImage, image_id)
    if not image or image.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片不存在。")
    image.media_state = MediaState.DELETE_PENDING
    enqueue_deletion(db, bucket_type="reference", object_key=image.object_key, resource_type="reference_image", resource_id=image.id)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    try:
        MinioStorageService().delete_reference_image(image.object_key)
    except StorageError:
        logger.warning("Failed to eagerly delete reference %s", image.object_key)
