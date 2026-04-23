from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PublicModel(BaseModel):
    id: str
    label: str
    enabled: bool = True


class PublicMetaResponse(BaseModel):
    site_name: str
    prompt_max_length: int
    polling_interval_ms: int
    example_prompts: list[str]
    models: list[PublicModel]


class CreateJobRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=32000)
    model: str = Field(min_length=1, max_length=128)


class CreateJobResponse(BaseModel):
    job_id: str
    status: str
    poll_url: str
    rate_limit_remaining: int


class JobStatusResponse(BaseModel):
    job_id: str
    status: str


class JobDetailResponse(BaseModel):
    job_id: str
    status: str
    image_url: str | None = None
    prompt: str
    revised_prompt: str | None = None
    model: str
    error_message: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class GalleryItem(BaseModel):
    job_id: str
    image_url: str
    prompt: str
    revised_prompt: str | None = None
    model: str
    finished_at: datetime


class HealthResponse(BaseModel):
    status: str
