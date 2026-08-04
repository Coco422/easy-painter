from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ReferenceImageItem(BaseModel):
    id: str
    filename: str
    content_type: str
    used_count: int
    created_at: datetime
    last_used_at: datetime | None = None
