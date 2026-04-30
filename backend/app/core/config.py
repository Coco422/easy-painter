from __future__ import annotations

import json
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_EXAMPLE_PROMPTS = [
    "春天清晨的湖边小镇，薄雾、樱花和温暖阳光，治愈系插画风格",
    "一只坐在月球咖啡馆里的橘猫，窗外是星云与地球，梦幻绘本风",
    "海边黄昏的小火车站，远处灯塔亮起，柔和水彩质感",
    "雨后古城的小巷，青石路反射暖色灯光，电影感场景设计",
]

MODEL_REFERENCE_IMAGE_SUPPORT = {
    "gpt-image-2-b": True,
    "gpt-image-2-c": False,
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
        "id": "gpt-image-2-c",
        "label": "GPT-Image-2 C（文字生成）",
        "enabled": True,
        "supports_reference_image": False,
        "supported_sizes": [],
    },
    {
        "id": "gpt-image-2-b",
        "label": "GPT-Image-2 B（支持参考图）",
        "enabled": True,
        "supports_reference_image": True,
        "supported_sizes": [],
    },
    {
        "id": "grok-4.1-image",
        "label": "Grok 4.1 Image",
        "enabled": True,
        "supports_reference_image": True,
        "supported_sizes": GROK_SUPPORTED_SIZES,
    },
    {
        "id": "grok-imagine-image",
        "label": "Grok Imagine",
        "enabled": True,
        "supports_reference_image": True,
        "supported_sizes": GROK_SUPPORTED_SIZES,
    },
    {
        "id": "doubao-seedream-5-0-260128",
        "label": "豆包 Seedream 5.0",
        "enabled": True,
        "supports_reference_image": True,
        "supported_sizes": [],
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
    site_name: str = "安落滢绘画站"
    app_env: str = "production"
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+psycopg://easy_painter:easy_painter@postgres:5432/easy_painter"
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "easy-painter-media"
    minio_reference_bucket: str = "easy-painter-references"
    minio_secure: bool = False

    upstream_base_url: str = ""
    upstream_api_key: str = ""
    upstream_timeout_seconds: int = 700

    default_model: str = "gpt-image-2"
    upstream_default_size: str = "auto"
    upstream_default_quality: str = "high"
    upstream_default_output_format: str = "jpeg"
    upstream_default_output_compression: int = 85
    upstream_default_background: str = "auto"
    upstream_default_moderation: str = "auto"

    prompt_max_length: int = 500
    gallery_limit: int = 24
    generate_rate_limit_count: int = 12
    generate_rate_limit_window_seconds: int = 60
    polling_interval_ms: int = 2000

    public_models_json: str | None = None
    example_prompts_json: str | None = None
    allowed_origins_json: str | None = None

    @property
    def public_models(self) -> list[dict[str, str | bool | list[str]]]:
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
                }
                for item in data
            ]
        return DEFAULT_PUBLIC_MODELS

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
