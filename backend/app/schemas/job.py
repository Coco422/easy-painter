from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.user_group import UserGroupPolicyResponse


ImageAspectRatio = Literal["auto", "1:1", "3:4", "9:16", "4:3", "16:9"]
IMAGE_SIZE_PATTERN = re.compile(r"^(\d+)x(\d+)$")
ASPECT_RATIO_SIZE_MAP = {
    "auto": "auto",
    "1:1": "1024x1024",
    "3:4": "1024x1536",
    "9:16": "1024x1792",
    "4:3": "1536x1024",
    "16:9": "1792x1024",
}


class PublicModel(BaseModel):
    id: str
    label: str
    enabled: bool = True
    supports_reference_image: bool = True
    supported_sizes: list[str] = Field(default_factory=list)
    credit_cost: int = 2
    base_credit_cost: int = 2


class PublicMetaResponse(BaseModel):
    site_name: str
    registration_enabled: bool = True
    email_delivery_enabled: bool = False
    prompt_max_length: int
    polling_interval_ms: int
    example_prompts: list[str]
    models: list[PublicModel]
    viewer_group: UserGroupPolicyResponse | None = None


class CreateJobRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=32000)
    model: str = Field(min_length=1, max_length=128)
    size: str = "auto"
    aspect_ratio: ImageAspectRatio | None = None
    reference_image_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_aspect_ratio(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("size") and data.get("aspect_ratio"):
            migrated = dict(data)
            migrated["size"] = ASPECT_RATIO_SIZE_MAP.get(str(data["aspect_ratio"]), "auto")
            return migrated
        return data

    @field_validator("size")
    @classmethod
    def validate_size(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized == "auto":
            return normalized

        match = IMAGE_SIZE_PATTERN.match(normalized)
        if not match:
            raise ValueError("size 必须是 auto 或 WIDTHxHEIGHT 格式。")

        width = int(match.group(1))
        height = int(match.group(2))
        if width <= 0 or height <= 0:
            raise ValueError("size 的宽高必须大于 0。")

        long_edge = max(width, height)
        short_edge = min(width, height)
        total_pixels = width * height

        if width % 16 != 0 or height % 16 != 0:
            raise ValueError("size 的宽高都必须是 16 的倍数。")
        if long_edge > 3840:
            raise ValueError("size 的任一边不能超过 3840px。")
        if long_edge / short_edge > 3:
            raise ValueError("size 的长短边比例不能超过 3:1。")
        if not 655_360 <= total_pixels <= 8_294_400:
            raise ValueError("size 的总像素必须在 655,360 到 8,294,400 之间。")

        return f"{width}x{height}"


class CreateJobResponse(BaseModel):
    job_id: str
    status: str
    poll_url: str
    rate_limit_remaining: int
    credit_cost: int = 0
    base_credit_cost: int | None = None
    billing_multiplier_bps: int | None = None
    group_code: str | None = None
    group_name: str | None = None
    balance_after: int = 0
    billing_status: str = "not_charged"


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
    model_label: str | None = None
    provider_name: str | None = None
    size: str
    aspect_ratio: str | None = None
    error_message: str | None = None
    credit_cost: int = 0
    base_credit_cost: int | None = None
    billing_multiplier_bps: int | None = None
    group_code: str | None = None
    group_name: str | None = None
    billing_status: str = "not_charged"
    refunded_at: datetime | None = None
    created_at: datetime
    finished_at: datetime | None = None
    media_state: str = "none"
    media_expires_at: datetime | None = None


class TogglePublicRequest(BaseModel):
    tags: list[str] | None = None
    is_prompt_public: bool = True

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if len(v) > 5:
            raise ValueError("最多选择 5 个标签。")
        return [t.strip() for t in v if t.strip()]


class GalleryItem(BaseModel):
    job_id: str
    image_url: str
    prompt: str
    revised_prompt: str | None = None
    model: str
    size: str
    aspect_ratio: str | None = None
    finished_at: datetime
    username: str | None = None
    is_public: bool = False
    is_prompt_public: bool = True
    is_favorite: bool = False
    tags: list[str] | None = None
    like_count: int = 0
    liked_by_me: bool = False
    media_expires_at: datetime | None = None


class GalleryPageResponse(BaseModel):
    items: list[GalleryItem]
    total: int
    page: int
    page_size: int


class HealthResponse(BaseModel):
    status: str
    components: dict[str, dict[str, Any]] | None = None
