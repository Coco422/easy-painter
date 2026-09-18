from __future__ import annotations

from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.artwork import CommunitySubmission
from app.models.generation_job import GenerationJob
from app.models.inspiration import Inspiration
from app.models.media import MediaState
from app.models.user import User
from app.services.artworks import effective_submission, original_available, utcnow
from app.services.media_lifecycle import enqueue_deletion
from app.services.storage import MinioStorageService, StorageError


def withdraw_pending(db: Session, user_id: str) -> None:
    for sub in db.scalars(select(CommunitySubmission).where(
        CommunitySubmission.user_id == user_id, CommunitySubmission.status == 'pending',
    ).with_for_update().execution_options(populate_existing=True)).all():
        sub.status = 'withdrawn'
        sub.reviewed_at = utcnow()


def review_submission(db: Session, job_id: str, decision: str, reason: str = '', *, storage=None) -> CommunitySubmission:
    existing = db.get(CommunitySubmission, job_id)
    if not existing:
        raise HTTPException(404, '投稿不存在。')
    # All publishing paths lock owner before job, serializing master-switch changes.
    owner = db.scalar(select(User).where(User.id == existing.user_id).with_for_update().execution_options(populate_existing=True))
    job = db.scalar(select(GenerationJob).where(GenerationJob.id == job_id).with_for_update().execution_options(populate_existing=True))
    sub = db.scalar(select(CommunitySubmission).where(CommunitySubmission.job_id == job_id).with_for_update().execution_options(populate_existing=True))
    if sub.status == 'approved' and decision == 'approve':
        return sub
    state = effective_submission(sub, job, owner)
    if state != 'pending':
        sub.status = state
        db.commit()
        raise HTTPException(409, '投稿已撤回、已处理或图片已过期。')
    if decision == 'reject':
        if not reason.strip():
            raise HTTPException(422, '请填写拒绝理由。')
        sub.status, sub.review_reason, sub.reviewed_at = 'rejected', reason.strip(), utcnow()
        db.commit()
        return sub
    existing_copy = db.scalar(select(Inspiration).where(Inspiration.source == 'community-curated', Inspiration.external_id == job_id))
    if existing_copy:
        raise HTTPException(409, '该作品已有社区收录记录。')
    storage = storage or MinioStorageService()
    inspiration_id = str(uuid4())
    try:
        key = storage.copy_generated_image_to_inspiration(job.object_key, inspiration_id=inspiration_id)
    except StorageError:
        raise HTTPException(503, '收录图片复制失败，请重试。') from None
    # Copy can take time. Recheck the deadline while still holding the source lock.
    if not original_available(job):
        enqueue_deletion(db, bucket_type='media', object_key=key, resource_type='orphan_inspiration_copy', resource_id=inspiration_id)
        sub.status = 'expired'
        db.commit()
        raise HTTPException(409, '图片在审核期间已过期。')
    item = Inspiration(
        id=inspiration_id, title=job.prompt[:80], prompt=job.prompt,
        image_url=f'/api/v1/inspirations/{inspiration_id}/file', image_object_key=key,
        source='community-curated', external_id=job.id,
        author_name=owner.display_name or owner.username, categories=job.tags or [],
        source_job_id=job.id, source_user_id=job.user_id, curated_at=utcnow(),
        media_state=MediaState.AVAILABLE, media_size_bytes=job.media_size_bytes,
        media_content_type=job.media_content_type, media_hash=job.media_hash,
    )
    db.add(item)
    sub.status, sub.review_reason, sub.reviewed_at, sub.inspiration_id = 'approved', None, utcnow(), inspiration_id
    try:
        db.commit()
    except Exception:
        db.rollback()
        enqueue_deletion(db, bucket_type='media', object_key=key, resource_type='orphan_inspiration_copy', resource_id=inspiration_id)
        db.commit()
        raise
    return sub
