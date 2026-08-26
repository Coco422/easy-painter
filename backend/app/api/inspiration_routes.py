from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user_optional
from app.db.session import get_db
from app.models.inspiration import Inspiration
from app.models.media import MediaState
from app.models.user import User
from app.schemas.inspiration import InspirationFeedResponse, InspirationItemResponse
from app.services.storage import MinioStorageService, StorageError

logger = logging.getLogger(__name__)
inspiration_router = APIRouter()
GUEST_INSPIRATION_PREVIEW_LIMIT = 20


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
        image_url=f"/api/v1/inspirations/{item.id}/file" if item.image_object_key else item.image_url,
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


@inspiration_router.get("/inspirations", response_model=InspirationFeedResponse)
def list_inspirations(
    db: Session = Depends(get_db),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, max_length=200),
    source: str | None = Query(None, max_length=128),
    category: str | None = Query(None, max_length=100),
    sort: str = Query("recent", pattern="^(recent|featured)$"),
    current_user: User | None = Depends(get_current_user_optional),
) -> InspirationFeedResponse:
    items: list[InspirationItemResponse] = []
    effective_limit = limit
    if current_user is None:
        effective_limit = min(limit, max(0, GUEST_INSPIRATION_PREVIEW_LIMIT - offset))

    stmt = select(Inspiration).where(Inspiration.deleted_at.is_(None), Inspiration.media_state == MediaState.AVAILABLE)

    if q:
        like_pattern = f"%{q}%"
        stmt = stmt.where(Inspiration.title.ilike(like_pattern) | Inspiration.prompt.ilike(like_pattern) | Inspiration.description.ilike(like_pattern))
    if source and source != "all":
        if source == "imported":
            stmt = stmt.where(Inspiration.source != "community-curated")
        else:
            stmt = stmt.where(Inspiration.source == source)

    if sort == "featured":
        stmt = stmt.order_by(desc(Inspiration.is_featured), desc(Inspiration.created_at))
    else:
        stmt = stmt.order_by(desc(Inspiration.created_at))

    if category:
        inspiration_rows = db.scalars(stmt.limit(5000)).all()
        inspiration_rows = [row for row in inspiration_rows if isinstance(row.categories, list) and category in row.categories]
        total = len(inspiration_rows)
        inspiration_rows = inspiration_rows[offset : offset + effective_limit]
    else:
        total = int(db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
        inspiration_rows = db.scalars(stmt.offset(offset).limit(effective_limit)).all() if effective_limit > 0 else []
    items.extend(_inspiration_to_response(row) for row in inspiration_rows)

    return InspirationFeedResponse(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
    )


@inspiration_router.get("/inspirations/categories", response_model=list[str])
def list_inspiration_categories(
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
) -> list[str]:
    category_lists = db.scalars(
        select(Inspiration.categories).where(
            Inspiration.deleted_at.is_(None),
            Inspiration.media_state == MediaState.AVAILABLE,
            Inspiration.categories.is_not(None),
        ).limit(5000)
    ).all()
    counts: Counter[str] = Counter()
    for categories in category_lists:
        if not isinstance(categories, list):
            continue
        counts.update(
            category.strip()
            for category in categories
            if isinstance(category, str) and category.strip()
        )
    return [category for category, _ in counts.most_common(limit)]


@inspiration_router.get("/inspirations/{inspiration_id}/file")
def stream_inspiration_file(inspiration_id: str, db: Session = Depends(get_db)):
    item = db.get(Inspiration, inspiration_id)
    if not item or item.deleted_at is not None or item.media_state != MediaState.AVAILABLE or not item.image_object_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片不存在。")
    storage = MinioStorageService()
    try:
        opened = storage.open_object(item.image_object_key)
    except StorageError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="图片读取失败。",
            headers={"Cache-Control": "no-store"},
        ) from None
    return StreamingResponse(
        storage.iter_response(opened),
        media_type=item.media_content_type or "image/jpeg",
        headers={"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )
