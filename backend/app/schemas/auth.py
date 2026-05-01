from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    username: str
    display_name: str
    is_public: bool
    created_at: datetime


class UpdateUserRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    is_public: bool | None = None


class AdminVerifyRequest(BaseModel):
    secret_key: str


class AdminCreateUserRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field(default="", max_length=128)


class AdminUpdateUserRequest(BaseModel):
    password: str | None = Field(default=None, min_length=6, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)
    is_public: bool | None = None
