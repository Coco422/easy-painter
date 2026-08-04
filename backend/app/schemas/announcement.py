from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AnnouncementLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AnnouncementAudience(str, Enum):
    ALL = "all"
    AUTHENTICATED = "authenticated"
    UNBOUND_EMAIL = "unbound_email"


class AnnouncementCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=2000)
    level: AnnouncementLevel = AnnouncementLevel.INFO
    audience: AnnouncementAudience = AnnouncementAudience.ALL
    enabled: bool = True

    @field_validator("title", "content")
    @classmethod
    def strip_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("内容不能为空。")
        return normalized


class AnnouncementUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=128)
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    level: AnnouncementLevel | None = None
    audience: AnnouncementAudience | None = None
    enabled: bool | None = None

    @field_validator("title", "content")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("内容不能为空。")
        return normalized


class AnnouncementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    content: str
    level: AnnouncementLevel
    audience: AnnouncementAudience
    enabled: bool
    created_at: datetime
    updated_at: datetime
