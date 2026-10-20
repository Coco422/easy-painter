from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class PaymentConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0, strict=True)
    enabled: bool = False
    gateway_url: str = Field(default="https://zpayz.cn", max_length=256)
    merchant_id: str = Field(min_length=1, max_length=64)
    merchant_key: SecretStr = Field(default=SecretStr(""), repr=False)
    public_base_url: str = Field(max_length=256)
    payment_methods: list[Literal["alipay", "wxpay"]] = Field(default=["alipay"], min_length=1, max_length=2)

    @field_validator("payment_methods")
    @classmethod
    def unique_methods(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class RechargePackageInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    price_fen: int = Field(ge=1, le=1_000_000, strict=True)
    paid_credits: int = Field(ge=1, le=10_000_000, strict=True)
    gift_credits: int = Field(default=0, ge=0, le=10_000_000, strict=True)
    is_enabled: bool = False
    sort_order: int = Field(default=0, ge=0, le=10000, strict=True)

    @field_validator("name")
    @classmethod
    def safe_product_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(c in value for c in "&=") or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("套餐名称不能为空或包含 &、=、换行等特殊字符。")
        return value


class RechargePackageResponse(RechargePackageInput):
    id: str
    revision: int


class CreateRechargeRequest(BaseModel):
    package_id: str = Field(min_length=1, max_length=36)
    package_revision: int = Field(ge=1, strict=True)
    payment_method: Literal["alipay", "wxpay"]


class RechargeOrderResponse(BaseModel):
    id: str
    package_name: str
    amount_fen: int
    paid_credits: int
    gift_credits: int
    payment_method: str
    status: Literal["pending", "paid"]
    expired: bool
    created_at: datetime
    expires_at: datetime
    paid_at: datetime | None


class RechargeCheckoutResponse(BaseModel):
    order: RechargeOrderResponse
    action: str | None = None
    fields: dict[str, str] | None = None
