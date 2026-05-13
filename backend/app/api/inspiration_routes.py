from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.gallery_like import GalleryLike
from app.models.generation_job import GenerationJob, JobStatus
from app.models.inspiration import Inspiration
from app.models.user import User
from app.schemas.inspiration import InspirationFeedResponse, InspirationItemResponse

logger = logging.getLogger(__name__)
inspiration_router = APIRouter()


def _batch_usernames(db: Session, user_ids: list[str]) -> dict[str, str]:
    if not user_ids:
        return {}
    users = db.scalars(select(User).where(User.id.in_(user_ids))).all()
    return {u.id: u.username for u in users}


def _inspiration_to_response(item: Inspiration) -> InspirationItemResponse:
    categories = item.categories
    if isinstance(categories, dict):
        # Flatten nested category structure to a list of strings
        flat = []
        for values in categories.values():
            if isinstance(values, list):
                for v in values:
                    if isinstance(v, str):
                        flat.append(v)
                    elif isinstance(v, dict) and "name" in v:
                        flat.append(v["name"])
        categories = flat if flat else None
    elif not isinstance(categories, list):
        categories = None

    return InspirationItemResponse(
        id=item.id,
        title=item.title,
        description=item.description,
        prompt=item.prompt,
        image_url=item.image_url,
        source=item.source,
        source_url=item.source_url,
        author_name=item.author_name,
        author_url=item.author_url,
        language=item.language or "zh",
        categories=categories,
        is_featured=item.is_featured or False,
        like_count=item.like_count or 0,
        created_at=item.created_at,
    )


def _gallery_job_to_response(
    job: GenerationJob, username: str | None, like_count: int = 0
) -> InspirationItemResponse:
    title = job.prompt[:80] + ("..." if len(job.prompt) > 80 else "")
    prompt_text = "" if job.is_prompt_public is False else job.prompt
    return InspirationItemResponse(
        id=f"gallery:{job.id}",
        title=title,
        description=None,
        prompt=prompt_text,
        image_url=job.public_url or "",
        source="gallery",
        source_url=None,
        author_name=username,
        author_url=None,
        language="zh",
        categories=job.tags if isinstance(job.tags, list) else None,
        is_featured=False,
        like_count=like_count,
        created_at=job.finished_at or job.created_at,
    )


@inspiration_router.get("/inspirations", response_model=InspirationFeedResponse)
def list_inspirations(
    db: Session = Depends(get_db),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, max_length=200),
    source: str | None = Query(None, max_length=128),
    category: str | None = Query(None, max_length=100),
    sort: str = Query("recent", pattern="^(recent|featured)$"),
) -> InspirationFeedResponse:
    items: list[InspirationItemResponse] = []

    # 1. Query external inspirations (unless source=gallery or category filter is set)
    if source != "gallery" and not category:
        stmt = select(Inspiration)

        if q:
            like_pattern = f"%{q}%"
            stmt = stmt.where(
                Inspiration.title.ilike(like_pattern)
                | Inspiration.prompt.ilike(like_pattern)
                | Inspiration.description.ilike(like_pattern)
            )
        if source and source != "all":
            stmt = stmt.where(Inspiration.source == source)

        if sort == "featured":
            stmt = stmt.order_by(desc(Inspiration.is_featured), desc(Inspiration.created_at))
        else:
            stmt = stmt.order_by(desc(Inspiration.created_at))

        inspiration_rows = db.scalars(stmt).all()
        items.extend(_inspiration_to_response(row) for row in inspiration_rows)

    # 2. Query public gallery jobs
    # Skip gallery only when filtering by a specific external source
    include_gallery = source in (None, "", "all", "gallery")
    if include_gallery:
        gallery_stmt = (
            select(GenerationJob)
            .where(GenerationJob.status == JobStatus.SUCCEEDED)
            .where(GenerationJob.is_public.is_(True))
            .where(GenerationJob.public_url.isnot(None))
        )

        if q:
            like_pattern = f"%{q}%"
            gallery_stmt = gallery_stmt.where(GenerationJob.prompt.ilike(like_pattern))

        gallery_stmt = gallery_stmt.order_by(desc(GenerationJob.finished_at)).limit(500)
        jobs = db.scalars(gallery_stmt).all()

        # Filter by category (tags) in Python since tags is a JSON array
        if category:
            jobs = [
                j for j in jobs
                if isinstance(j.tags, list) and category in j.tags
            ]

        job_ids = [j.id for j in jobs]
        user_ids = list({j.user_id for j in jobs if j.user_id})
        usernames = _batch_usernames(db, user_ids)

        # Batch query like counts
        like_counts: dict[str, int] = {}
        if job_ids:
            rows = db.execute(
                select(GalleryLike.job_id, func.count())
                .where(GalleryLike.job_id.in_(job_ids))
                .group_by(GalleryLike.job_id)
            ).all()
            like_counts = {job_id: count for job_id, count in rows}

        items.extend(
            _gallery_job_to_response(
                job,
                usernames.get(job.user_id) if job.user_id else None,
                like_count=like_counts.get(job.id, 0),
            )
            for job in jobs
        )

    # 3. Sort combined results
    if sort == "featured":
        items.sort(key=lambda x: (not x.is_featured, x.created_at), reverse=False)
    else:
        items.sort(key=lambda x: x.created_at, reverse=True)

    # 4. Apply offset/limit to the combined list
    total = len(items)
    page_items = items[offset : offset + limit]

    return InspirationFeedResponse(
        items=page_items,
        total=total,
        offset=offset,
        limit=limit,
    )
