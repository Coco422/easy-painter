from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ReferenceImageItem(BaseModel):
    id: str
    filename: str
    content_type: str
    used_count: int
    created_at: datetime
    last_used_at: datetime | None = None
    media_expires_at: datetime | None = None
    evicted_image_ids: list[str] = Field(default_factory=list)
