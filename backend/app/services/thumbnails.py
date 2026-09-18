"""Bounded background derivatives: never generate a preview on a GET request."""
from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
from io import BytesIO
import logging
import warnings
from uuid import uuid4

from PIL import Image, ImageOps
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.generation_job import GenerationJob
from app.models.inspiration import Inspiration
from app.models.media import MediaState
from app.models.reference_image import ReferenceImage
from app.services.artworks import expired, live_original_clause, original_available, utcnow
from app.services.media_lifecycle import enqueue_deletion
from app.services.storage import MinioStorageService

logger = logging.getLogger(__name__)


def make_thumbnail(data: bytes) -> bytes:
    if len(data) > 64 * 1024 * 1024:
        raise ValueError('Image exceeds thumbnail input limit')
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(BytesIO(data)) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError('Image exceeds thumbnail pixel limit')
            image.seek(0)
            image = ImageOps.exif_transpose(image)
            image.thumbnail((640, 640), Image.Resampling.LANCZOS)
            image = image.convert('RGBA' if 'A' in image.getbands() else 'RGB')
            output = BytesIO()
            image.save(output, 'WEBP', quality=75, method=4)
            return output.getvalue()


def source_available(source) -> bool:
    if isinstance(source, GenerationJob):
        return original_available(source)
    if isinstance(source, ReferenceImage):
        return source.media_state == MediaState.AVAILABLE and not expired(source.media_expires_at)
    return source.media_state == MediaState.AVAILABLE and source.deleted_at is None and bool(source.image_object_key)


def prepare_thumbnail(db: Session, source, *, data: bytes | None = None, storage=None) -> bool:
    storage = storage or MinioStorageService()
    if source.thumbnail_key or not source_available(source):
        return False
    reference = isinstance(source, ReferenceImage)
    key = source.image_object_key if isinstance(source, Inspiration) else source.object_key
    preview_key = f'thumbnails/{source.__tablename__}/{source.id}/{uuid4()}.webp'
    uploaded = False
    try:
        if data is None:
            opened = storage.open_object(key, reference=reference)
            try:
                data = opened.read(64 * 1024 * 1024 + 1)
            finally:
                opened.close()
                opened.release_conn()
        thumbnail = make_thumbnail(data)
        storage.upload_thumbnail(preview_key, thumbnail, reference=reference)
        uploaded = True
        if not source_available(source):
            enqueue_deletion(db, bucket_type='reference' if reference else 'media', object_key=preview_key, resource_type='thumbnail', resource_id=source.id)
            db.commit()
            return False
        source.thumbnail_key = preview_key
        source.thumbnail_hash = sha256(thumbnail).hexdigest()
        source.thumbnail_size_bytes = len(thumbnail)
        source.media_hash = sha256(data).hexdigest()
        source.thumbnail_retry_at = None
        db.commit()
        return True
    except Exception:
        db.rollback()
        # A failed preview must never fail or refund a successfully delivered job.
        if uploaded:
            enqueue_deletion(db, bucket_type='reference' if reference else 'media', object_key=preview_key, resource_type='thumbnail', resource_id=source.id)
        source.thumbnail_attempts = (source.thumbnail_attempts or 0) + 1
        source.thumbnail_retry_at = utcnow() + timedelta(minutes=min(60, 2 ** source.thumbnail_attempts))
        db.commit()
        logger.warning('Thumbnail deferred for %s %s', source.__tablename__, source.id)
        return False


def backfill_thumbnails(db: Session, *, limit: int = 2) -> int:
    """At most two images per table per run; row locks serialize with cleanup."""
    count = 0
    for model in (GenerationJob, ReferenceImage, Inspiration):
        available = live_original_clause() if model is GenerationJob else (
            (model.media_state == MediaState.AVAILABLE) &
            (or_(model.media_expires_at.is_(None), model.media_expires_at > utcnow()) if model is ReferenceImage else (model.deleted_at.is_(None) & model.image_object_key.is_not(None)))
        )
        # One row per transaction: prepare_thumbnail commits and releases its lock.
        for _ in range(limit):
            source = db.scalar(select(model).where(
                available, model.thumbnail_key.is_(None), model.thumbnail_attempts < 5,
                or_(model.thumbnail_retry_at.is_(None), model.thumbnail_retry_at <= utcnow()),
            ).order_by(model.created_at.desc(), model.id).limit(1).with_for_update(skip_locked=True).execution_options(populate_existing=True))
            if source is None:
                db.rollback()
                break
            count += int(prepare_thumbnail(db, source))
    return count
