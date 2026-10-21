from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr


DEFAULT_EXAMPLE_PROMPTS = [
    "春天清晨的湖边小镇，薄雾、樱花和温暖阳光，治愈系插画风格",
    "一只坐在月球咖啡馆里的橘猫，窗外是星云与地球，梦幻绘本风",
    "海边黄昏的小火车站，远处灯塔亮起，柔和水彩质感",
    "雨后古城的小巷，青石路反射暖色灯光，电影感场景设计",
]

MODEL_REFERENCE_IMAGE_SUPPORT = {
    "gpt-image-2": True,
    "gpt-image-2-b": True,
    "gpt-image-2-c": True,
    "grok-4.1-image": True,
    "grok-imagine-image": True,
    "doubao-seedream-5-0-260128": True,
}

GROK_SUPPORTED_SIZES = ["1024x1024", "1280x720", "1792x1024", "720x1280", "1024x1792"]
MODEL_SUPPORTED_SIZES = {
    "grok-4.1-image": GROK_SUPPORTED_SIZES,
    "grok-imagine-image": GROK_SUPPORTED_SIZES,
}

DEFAULT_PUBLIC_MODELS = [
    {
        "id": "gpt-image-2",
        "label": "GPT-Image-2（支持参考图）",
        "enabled": True,
        "supports_reference_image": True,
        "max_reference_images": 5,
        "supported_sizes": [],
        "credit_cost": 2,
    },
    {
        "id": "gpt-image-2-c",
        "label": "GPT-Image-2 C（支持参考图）",
        "enabled": True,
        "supports_reference_image": True,
        "max_reference_images": 5,
        "supported_sizes": [],
        "credit_cost": 2,
    },
    {
        "id": "gpt-image-2-b",
        "label": "GPT-Image-2 B（支持参考图）",
        "enabled": True,
        "supports_reference_image": True,
        "max_reference_images": 5,
        "supported_sizes": [],
        "credit_cost": 2,
    },
    {
        "id": "grok-4.1-image",
        "label": "Grok 4.1 Image",
        "enabled": True,
        "supports_reference_image": True,
        "max_reference_images": 5,
        "supported_sizes": GROK_SUPPORTED_SIZES,
        "credit_cost": 2,
    },
    {
        "id": "grok-imagine-image",
        "label": "Grok Imagine",
        "enabled": True,
        "supports_reference_image": True,
        "max_reference_images": 5,
        "supported_sizes": GROK_SUPPORTED_SIZES,
        "credit_cost": 2,
    },
    {
        "id": "doubao-seedream-5-0-260128",
        "label": "豆包 Seedream 5.0",
        "enabled": True,
        "supports_reference_image": True,
        "max_reference_images": 5,
        "supported_sizes": [],
        "credit_cost": 2,
    },
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "easy-painter-api"
    site_name: str = "一丝绘画站"
    app_env: str = "production"
    api_v1_prefix: str = "/api/v1"
    # Empty disables agent endpoints until the canonical external HTTPS URL is configured.
    mcp_public_url: str = ""

    database_url: str = "postgresql+psycopg://easy_painter:easy_painter@postgres:5432/easy_painter"
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # Legacy MINIO_* names remain compatible; the server is now RustFS.
    minio_endpoint: str = "rustfs:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "easy-painter-media"
    minio_reference_bucket: str = "easy-painter-references"
    minio_secure: bool = False

    jwt_secret_key: str = "change-me-jwt-secret-at-least-32-bytes"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440
    admin_secret_key: str = ""
    default_username: str = "admin"
    default_password: str = ""
    default_email: str = ""
    registration_enabled: bool = True

    # Keep checkout disabled until the operator configures and enables ZPAY.
    zpay_enabled: bool = False
    zpay_gateway_url: str = ""
    zpay_merchant_id: str = ""
    zpay_key: SecretStr = SecretStr("")
    payment_config_encryption_key: SecretStr = SecretStr("")
    zpay_payment_methods: list[Literal["alipay", "wxpay"]] = ["alipay", "wxpay"]
    zpay_public_base_url: str = ""
    zpay_order_ttl_minutes: int = 30

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_timeout_seconds: int = 15
    email_code_expire_seconds: int = 600
    email_code_cooldown_seconds: int = 60
    email_code_rate_limit_count: int = 3
    email_code_rate_limit_window_seconds: int = 600
    email_code_daily_limit_count: int = 10
    email_code_daily_limit_window_seconds: int = 86400
    email_code_ip_rate_limit_count: int = 15
    email_code_ip_daily_limit_count: int = 50

    upstream_base_url: str = ""
    upstream_api_key: str = ""
    upstream_timeout_seconds: int = 700
    upstream_provider_name: str = "chatgpt2api（自建）"
    additional_upstreams_json: str | None = None
    sync_public_models_from_env: bool = False
    github_api_token: str = ""

    default_model: str = "gpt-image-2"
    upstream_default_size: str = "auto"
    upstream_default_quality: str = "high"
    upstream_default_output_format: str = "jpeg"
    upstream_default_output_compression: int = 85
    upstream_default_background: str = "auto"
    upstream_default_moderation: str = "auto"

    prompt_max_length: int = 4000
    gallery_limit: int = 24
    # Short burst protection only; no per-minute generation quota.
    generation_abuse_burst_limit: int = Field(default=60, ge=1)
    polling_interval_ms: int = 2000
    generation_job_stale_seconds: int = 2700
    generation_queue_stale_seconds: int = 900
    outbox_poll_seconds: float = 2.0
    outbox_batch_size: int = 100
    reconciliation_interval_seconds: int = 300
    watchdog_interval_seconds: int = 30
    dispatcher_heartbeat_ttl_seconds: int = 30
    media_token_ttl_seconds: int = 3600
    media_cleanup_enabled: bool = False
    media_cleanup_interval_seconds: int = 60
    media_cleanup_batch_size: int = 100

    public_models_json: str | None = None
    example_prompts_json: str | None = None
    allowed_origins_json: str | None = None

    @property
    def public_models(self) -> list[dict[str, str | bool | int | list[str]]]:
        if self.public_models_json:
            data = json.loads(self.public_models_json)
            return [
                {
                    "id": item["id"],
                    "label": item.get("label", item["id"]),
                    "enabled": bool(item.get("enabled", True)),
                    "supports_reference_image": bool(
                        item.get(
                            "supports_reference_image",
                            MODEL_REFERENCE_IMAGE_SUPPORT.get(item["id"], True),
                        )
                    ),
                    "supported_sizes": [
                        str(size)
                        for size in item.get("supported_sizes", MODEL_SUPPORTED_SIZES.get(item["id"], []))
                    ],
                    "upstream_model_id": str(item.get("upstream_model_id", item["id"])),
                    "max_reference_images": max(1, int(item.get("max_reference_images", 5))),
                    "credit_cost": max(1, int(item.get("credit_cost", 2))),
                }
                for item in data
            ]
        return DEFAULT_PUBLIC_MODELS

    @property
    def additional_upstreams(self) -> list[dict[str, Any]]:
        if not self.additional_upstreams_json:
            return []

        data = json.loads(self.additional_upstreams_json)
        if not isinstance(data, list):
            raise ValueError("ADDITIONAL_UPSTREAMS_JSON must be a JSON array.")
        for provider in data:
            if not isinstance(provider, dict):
                raise ValueError("Each additional upstream must be an object.")
            for field in ("name", "base_url", "api_key", "models"):
                if field not in provider:
                    raise ValueError(f"Each additional upstream must include {field}.")
            if not all(str(provider[field]).strip() for field in ("name", "base_url", "api_key")):
                raise ValueError("Additional upstream name, base_url and api_key must not be empty.")
            if not isinstance(provider["models"], list):
                raise ValueError("Additional upstream models must be a JSON array.")
            for model in provider["models"]:
                if not isinstance(model, dict) or not str(model.get("id", "")).strip():
                    raise ValueError("Each additional upstream model must include an id.")
                if model.get("fallback_for") and not model.get("enabled", True):
                    raise ValueError("A fallback upstream model must be enabled.")
                if "upstream_model_id" in model and not str(model["upstream_model_id"]).strip():
                    raise ValueError("Additional upstream model upstream_model_id must not be empty.")
        primary_model_ids = {str(model["id"]) for model in self.public_models}
        for provider in data:
            for model in provider["models"]:
                fallback_for = model.get("fallback_for")
                if fallback_for and fallback_for not in primary_model_ids:
                    raise ValueError("Each fallback upstream model must target a configured public model id.")
        return data

    @property
    def example_prompts(self) -> list[str]:
        if self.example_prompts_json:
            return [str(item) for item in json.loads(self.example_prompts_json)]
        return DEFAULT_EXAMPLE_PROMPTS

    @property
    def allowed_origins(self) -> list[str]:
        if self.allowed_origins_json:
            return [str(item) for item in json.loads(self.allowed_origins_json)]
        return ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host.strip() and self.smtp_from_email.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
