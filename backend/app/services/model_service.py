from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.model_config import ModelConfig
from app.models.upstream_provider import UpstreamProvider


@dataclass(slots=True)
class ProviderConfig:
    base_url: str
    api_key: str
    timeout_seconds: int
    default_size: str
    default_quality: str
    default_output_format: str
    default_output_compression: int
    default_background: str
    default_moderation: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "api_key": self.api_key,
            "timeout_seconds": self.timeout_seconds,
            "default_size": self.default_size,
            "default_quality": self.default_quality,
            "default_output_format": self.default_output_format,
            "default_output_compression": self.default_output_compression,
            "default_background": self.default_background,
            "default_moderation": self.default_moderation,
        }


def load_models_from_db(db: Session) -> list[dict[str, str | bool | list[str]]]:
    stmt = select(ModelConfig).order_by(ModelConfig.sort_order, ModelConfig.id)
    models = db.scalars(stmt).all()
    return [
        {
            "id": m.id,
            "label": m.label,
            "enabled": m.enabled,
            "supports_reference_image": m.supports_reference_image,
            "supported_sizes": list(m.supported_sizes) if m.supported_sizes else [],
        }
        for m in models
    ]


def load_provider_for_model(db: Session, model_id: str) -> ProviderConfig | None:
    model = db.get(ModelConfig, model_id)
    if not model:
        return None
    provider = db.get(UpstreamProvider, model.provider_id)
    if not provider:
        return None
    return ProviderConfig(
        base_url=provider.base_url,
        api_key=provider.api_key,
        timeout_seconds=provider.timeout_seconds,
        default_size=provider.default_size,
        default_quality=provider.default_quality,
        default_output_format=provider.default_output_format,
        default_output_compression=provider.default_output_compression,
        default_background=provider.default_background,
        default_moderation=provider.default_moderation,
    )
