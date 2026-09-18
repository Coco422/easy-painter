from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class ArtworkItem(BaseModel):
    kind: Literal['job', 'inspiration']
    id: str
    job_id: str | None = None
    favorite_id: str | None = None
    inspiration_id: str | None = None
    title: str = ''
    prompt: str = ''
    revised_prompt: str | None = None
    is_prompt_public: bool = False
    can_view_prompt: bool = False
    username: str | None = None
    is_owner: bool = False
    is_in_gallery: bool = False
    gallery_visible: bool = False
    is_favorite: bool = False
    tags: list[str] = Field(default_factory=list)
    status: str | None = None
    model: str = ''
    size: str = 'auto'
    aspect_ratio: str = 'auto'
    created_at: datetime | None = None
    finished_at: datetime | None = None
    favorited_at: datetime | None = None
    credit_cost: int | None = None
    billing_status: str | None = None
    error_message: str | None = None
    media_state: str
    media_expires_at: datetime | None = None
    original_expires_at: datetime | None = None
    retention_kind: str
    image_url: str | None = None
    thumbnail_url: str | None = None
    submission_status: str = 'none'
    review_reason: str | None = None


class ArtworkPage(BaseModel):
    items: list[ArtworkItem]
    total: int
    page: int
    page_size: int
    server_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GalleryMembershipRequest(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=5)
    is_prompt_public: bool = True


class SubmissionRequest(BaseModel):
    consent_public_prompt: Literal[True]


class ReviewRequest(BaseModel):
    decision: Literal['approve', 'reject']
    reason: str = Field(default='', max_length=1000)
