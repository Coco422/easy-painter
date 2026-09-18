from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.db.session import get_db
from app.models.artwork import CommunitySubmission
from app.services.community import review_submission
from app.models.generation_job import GenerationJob, JobStatus
from app.models.inspiration import Inspiration
from app.models.media import MediaState
from app.models.user import User
from app.schemas.inspiration import AdminInspirationItem
from app.schemas.pagination import PageResponse
from app.services.media_lifecycle import enqueue_deletion
from app.services.storage import MinioStorageService, StorageError


community_admin_router = APIRouter()
logger = logging.getLogger(__name__)


class CurateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=256)
    description: str | None = None
    is_featured: bool = False


class EditInspirationRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None
    prompt: str | None = Field(default=None, min_length=1)
    categories: list[str] | None = None
    is_featured: bool | None = None


class CommunityCandidate(BaseModel):
    job_id: str
    prompt: str
    revised_prompt: str | None = None
    image_url: str
    username: str
    display_name: str
    tags: list[str]
    finished_at: datetime | None = None


def _admin_response(item: Inspiration) -> AdminInspirationItem:
    return AdminInspirationItem(
        id=item.id,
        title=item.title,
        description=item.description,
        prompt=item.prompt,
        image_url=f"/api/v1/inspirations/{item.id}/file",
        thumbnail_url=f'/api/v1/artworks/inspiration/{item.id}/file?variant=thumbnail&v={item.thumbnail_hash}' if item.thumbnail_key else None,
        image_object_key=item.image_object_key,
        external_id=item.external_id,
        source=item.source,
        source_url=item.source_url,
        author_name=item.author_name,
        author_url=item.author_url,
        language=item.language or "zh",
        categories=item.categories if isinstance(item.categories, list) else None,
        is_featured=bool(item.is_featured),
        like_count=item.like_count or 0,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@community_admin_router.get("/admin/inspirations/candidates", response_model=PageResponse[CommunityCandidate])
def list_community_candidates(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> PageResponse[CommunityCandidate]:
    now = datetime.now(timezone.utc)
    already_curated = select(Inspiration.id).where(
        Inspiration.source_job_id == GenerationJob.id
    ).exists()
    base = select(GenerationJob, User).join(User, GenerationJob.user_id == User.id).join(CommunitySubmission, CommunitySubmission.job_id == GenerationJob.id).where(
        CommunitySubmission.status == "pending",
        GenerationJob.status == JobStatus.SUCCEEDED,
        User.is_public.is_(True),
        GenerationJob.deleted_at.is_(None),
        GenerationJob.media_state == MediaState.AVAILABLE,
        GenerationJob.object_key.is_not(None),
        or_(GenerationJob.media_expires_at.is_(None), GenerationJob.media_expires_at > now),
        ~already_curated,
    )
    total = int(db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = db.execute(
        base.order_by(desc(GenerationJob.finished_at), desc(GenerationJob.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    candidates = [
        {
            "job_id": job.id,
            "prompt": job.prompt,
            "revised_prompt": job.revised_prompt,
            "image_url": f"/api/v1/admin/community-submissions/{job.id}/file",
            "username": user.username,
            "display_name": user.display_name,
            "tags": job.tags or [],
            "finished_at": job.finished_at,
        }
        for job, user in rows
    ]
    return PageResponse[CommunityCandidate](items=candidates, total=total, page=page, page_size=page_size)


@community_admin_router.post(
    "/admin/inspirations/from-job/{job_id}",
    response_model=AdminInspirationItem,
    status_code=status.HTTP_201_CREATED,
)
def curate_job(
    job_id: str,
    body: CurateRequest = CurateRequest(),
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> AdminInspirationItem:
    sub = db.get(CommunitySubmission, job_id)
    if sub and sub.status == "approved":
        raise HTTPException(409, "该作品已被收录。")
    reviewed = review_submission(db, job_id, "approve", storage=MinioStorageService())
    item = db.get(Inspiration, reviewed.inspiration_id)
    if body.title:
        item.title = body.title
    item.description, item.is_featured = body.description, body.is_featured
    db.commit()
    return _admin_response(item)


@community_admin_router.put("/admin/inspirations/{inspiration_id}", response_model=AdminInspirationItem)
def edit_community_inspiration(
    inspiration_id: str,
    body: EditInspirationRequest,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> AdminInspirationItem:
    item = db.get(Inspiration, inspiration_id)
    if not item or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="灵感不存在。")
    for field in ("title", "prompt"):
        if field in body.model_fields_set:
            value = getattr(body, field)
            if value is None:
                raise HTTPException(status_code=422, detail=f"{field} 不能为空。")
            setattr(item, field, value)
    for field in ("description", "categories"):
        if field in body.model_fields_set:
            setattr(item, field, getattr(body, field))
    if "is_featured" in body.model_fields_set and body.is_featured is not None:
        item.is_featured = body.is_featured
    db.commit()
    db.refresh(item)
    return _admin_response(item)
