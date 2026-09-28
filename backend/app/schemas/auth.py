from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, ValidationError, ValidationInfo, ValidatorFunctionWrapHandler, field_validator
from pydantic_core import PydanticCustomError

from app.models.user_group import STANDARD_GROUP_CODE
from app.schemas.user_group import UserGroupPolicyResponse


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
    group: UserGroupPolicyResponse | None = None
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
    group_code: str | None = Field(default=None, min_length=2, max_length=64)

    @field_validator('username', 'email', 'password', 'display_name', 'group_code', mode='wrap')
    @classmethod
    def readable_validation(cls, value, handler: ValidatorFunctionWrapHandler, info: ValidationInfo):
        return _validate_admin_user_field(value, handler, info)


class AdminUpdateUserRequest(BaseModel):
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=6, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)
    is_public: bool | None = None
    group_code: str | None = Field(default=None, min_length=2, max_length=64)

    @field_validator('email', 'password', 'display_name', 'group_code', mode='wrap')
    @classmethod
    def readable_validation(cls, value, handler: ValidatorFunctionWrapHandler, info: ValidationInfo):
        return _validate_admin_user_field(value, handler, info)


def _validate_admin_user_field(value, handler: ValidatorFunctionWrapHandler, info: ValidationInfo):
    """Keep existing constraints and error codes, but make admin form errors readable."""
    try:
        return handler(value)
    except ValidationError as exc:
        error = exc.errors()[0]
        messages = {
            'username': '用户名须为 2–64 位字母、数字或下划线；邮箱请填写到邮箱栏。',
            'email': '请输入有效的邮箱地址。',
            'password': '密码须为 6–128 个字符。',
            'display_name': '显示名称须为不超过 128 个字符的文本。',
            'group_code': '用户组编码须为 2–64 个字符。',
        }
        raise PydanticCustomError(error['type'], messages[info.field_name]) from exc
