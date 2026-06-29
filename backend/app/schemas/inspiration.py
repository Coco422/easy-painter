from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class InspirationItemResponse(BaseModel):
    """Unified response item for the merged inspiration feed."""
    id: str
    title: str
    description: str | None = None
    prompt: str
    image_url: str
    source: str  # "awesome-gpt-image-2", "gallery", etc.
    source_url: str | None = None
    author_name: str | None = None
    author_url: str | None = None
    language: str = "zh"
    categories: list[str] | None = None
    is_featured: bool = False
    like_count: int = 0
    created_at: datetime


class InspirationFeedResponse(BaseModel):
    items: list[InspirationItemResponse]
    total: int
    offset: int
    limit: int


class CreateInspirationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    description: str | None = None
    prompt: str = Field(min_length=1)
    external_id: str | None = None
    source: str = Field(min_length=1, max_length=128)
    source_url: str | None = None
    author_name: str | None = None
    author_url: str | None = None
    language: str = "zh"
    categories: list[str] | None = None
    is_featured: bool = False


class CreateInspirationResponse(BaseModel):
    id: str
    image_url: str


class BatchInspirationItem(BaseModel):
    title: str
    description: str | None = None
    prompt: str
    image_url: str  # already a MinIO public URL
    external_id: str | None = None
    source: str
    source_url: str | None = None
    author_name: str | None = None
    author_url: str | None = None
    language: str = "zh"
    categories: list[str] | None = None
    is_featured: bool = False


class BatchCreateInspirationsRequest(BaseModel):
    items: list[BatchInspirationItem] = Field(max_length=500)


class BatchCreateInspirationsResponse(BaseModel):
    created: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


class AdminInspirationItem(BaseModel):
    """Admin view of an inspiration item with internal fields."""
    id: str
    title: str
    description: str | None = None
    prompt: str
    image_url: str
    image_object_key: str | None = None
    external_id: str | None = None
    source: str
    source_url: str | None = None
    author_name: str | None = None
    author_url: str | None = None
    language: str = "zh"
    categories: list[str] | None = None
    is_featured: bool = False
    like_count: int = 0
    created_at: datetime
    updated_at: datetime
