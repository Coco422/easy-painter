from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class EmailCodePurpose(str, Enum):
    REGISTER = "register"
    RESET_PASSWORD = "reset_password"
    BIND_EMAIL = "bind_email"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class EmailCodeRequest(BaseModel):
    email: EmailStr
    purpose: Literal[EmailCodePurpose.REGISTER, EmailCodePurpose.RESET_PASSWORD]


class EmailCodeResponse(BaseModel):
    message: str
    expires_in: int
    retry_after: int


class BindEmailCodeRequest(BaseModel):
    email: EmailStr


class BindEmailRequest(BaseModel):
    email: EmailStr
    email_code: str = Field(pattern=r"^\d{6}$")


class RegisterRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_]+$")
    email: EmailStr
    email_code: str = Field(pattern=r"^\d{6}$")
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field(default="", max_length=128)


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    email_code: str = Field(pattern=r"^\d{6}$")
    new_password: str = Field(min_length=6, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    username: str
    email: str | None = None
    display_name: str
    is_public: bool
    credits: int = 0
    created_at: datetime


class UpdateUserRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    is_public: bool | None = None


class AdminVerifyRequest(BaseModel):
    secret_key: str


class AdminCreateUserRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_]+$")
    email: EmailStr | None = None
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field(default="", max_length=128)


class AdminUpdateUserRequest(BaseModel):
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=6, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)
    is_public: bool | None = None
