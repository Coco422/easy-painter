from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from app.core.auth import require_current_user
from app.db.session import get_db
from app.models.reference_image import ReferenceImage
from app.models.user import User
from app.schemas.reference_image import ReferenceImageItem
from app.services.reference_images import ReferenceImageValidationError, validate_reference_image
from app.services.storage import MinioStorageService, StorageError


logger = logging.getLogger(__name__)
reference_router = APIRouter()
MAX_REFERENCE_IMAGES_PER_USER = 50


def _build_reference_image_item(image: ReferenceImage) -> ReferenceImageItem:
    return ReferenceImageItem(
        id=image.id,
        filename=image.filename,
        content_type=image.content_type,
        used_count=image.used_count,
        created_at=image.created_at,
        last_used_at=image.last_used_at,
    )


@reference_router.post("/reference-images", response_model=ReferenceImageItem, status_code=status.HTTP_201_CREATED)
async def upload_staged_reference_image(
    file: UploadFile = File(...),
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

    image_id = str(uuid4())
    storage = MinioStorageService()
    try:
        object_key = storage.upload_staging_reference_image(
            image_id=image_id,
            image_bytes=payload.image_bytes,
            content_type=payload.content_type,
        )
    except StorageError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="参考图保存失败，请稍后重试。",
        ) from None

    existing_count = db.scalar(
        select(func.count()).select_from(ReferenceImage).where(ReferenceImage.user_id == current_user.id)
    ) or 0
    oldest_images: list[ReferenceImage] = []
    if existing_count >= MAX_REFERENCE_IMAGES_PER_USER:
        excess = existing_count - MAX_REFERENCE_IMAGES_PER_USER + 1
        oldest_images = list(
            db.scalars(
                select(ReferenceImage)
                .where(ReferenceImage.user_id == current_user.id)
                .order_by(asc(ReferenceImage.created_at))
                .limit(excess)
            ).all()
        )

    image = ReferenceImage(
        id=image_id,
        user_id=current_user.id,
        object_key=object_key,
        content_type=payload.content_type,
        filename=payload.filename,
    )
    try:
        db.add(image)
        for old_image in oldest_images:
            db.delete(old_image)
        db.commit()
    except Exception:
        db.rollback()
        try:
            storage.delete_reference_image(object_key)
        except Exception:
            logger.warning("Failed to clean up newly uploaded MinIO reference %s", object_key)
        raise

    db.refresh(image)
    for old_image in oldest_images:
        try:
            storage.delete_reference_image(old_image.object_key)
        except Exception:
            logger.warning("Failed to delete evicted MinIO reference %s", old_image.object_key)
    return _build_reference_image_item(image)


@reference_router.get("/reference-images", response_model=list[ReferenceImageItem])
def list_staged_reference_images(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> list[ReferenceImageItem]:
    images = db.scalars(
        select(ReferenceImage)
        .where(ReferenceImage.user_id == current_user.id)
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
    if not image or image.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片不存在。")
    try:
        stored = MinioStorageService().download_reference_image(image.object_key, image.content_type)
    except StorageError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="参考图读取失败，请稍后重试。",
        ) from None
    return Response(
        content=stored.image_bytes,
        media_type=image.content_type,
        headers={"Cache-Control": "private, max-age=3600"},
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
    db.delete(image)
    try:
        MinioStorageService().delete_reference_image(image.object_key)
    except Exception:
        logger.warning("Failed to delete MinIO reference %s", image.object_key)
    db.commit()
