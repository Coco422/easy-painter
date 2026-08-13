from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


GROUP_CODE_PATTERN = r"^[a-z][a-z0-9_-]{1,63}$"


class UserGroupSummary(BaseModel):
    code: str
    name: str


class UserGroupPolicyResponse(UserGroupSummary):
    billing_multiplier_bps: int
    generated_retention_hours: int
    reference_retention_hours: int
    max_reference_images: int


class AdminUserGroupResponse(UserGroupPolicyResponse):
    description: str
    is_enabled: bool
    is_default: bool
    user_count: int = 0
    created_at: datetime
    updated_at: datetime


class CreateUserGroupRequest(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=GROUP_CODE_PATTERN)
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1000)
    billing_multiplier_bps: int = Field(default=10_000, ge=0, le=100_000)
    generated_retention_hours: int = Field(default=24, ge=1, le=87_600)
    reference_retention_hours: int = Field(default=24, ge=1, le=87_600)
    max_reference_images: int = Field(default=3, ge=0, le=10_000)
    is_enabled: bool = True
    is_default: bool = False


class UpdateUserGroupRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1000)
    billing_multiplier_bps: int | None = Field(default=None, ge=0, le=100_000)
    generated_retention_hours: int | None = Field(default=None, ge=1, le=87_600)
    reference_retention_hours: int | None = Field(default=None, ge=1, le=87_600)
    max_reference_images: int | None = Field(default=None, ge=0, le=10_000)
    is_enabled: bool | None = None
    is_default: bool | None = None
