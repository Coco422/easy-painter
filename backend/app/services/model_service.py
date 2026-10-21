from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
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


@dataclass(slots=True)
class FailoverProvider:
    name: str
    config: ProviderConfig
    model_id: str
    max_reference_images: int = 1


def load_models_from_db(db: Session) -> list[dict[str, str | bool | list[str] | int]]:
    stmt = select(ModelConfig).order_by(ModelConfig.sort_order, ModelConfig.id)
    models = db.scalars(stmt).all()
    return [
        {
            "id": m.id,
            "label": m.label,
            "enabled": m.enabled,
            "supports_reference_image": m.supports_reference_image,
            "max_reference_images": m.max_reference_images if m.max_reference_images is not None else 5,
            "supported_sizes": list(m.supported_sizes) if m.supported_sizes else [],
            "credit_cost": m.credit_cost if m.credit_cost is not None else 2,
        }
        for m in models
    ]


def load_provider_for_model(db: Session, model_id: str) -> ProviderConfig | None:
    model = db.get(ModelConfig, model_id)
    if not model:
        return None
    return load_provider_by_id(db, model.provider_id)


def load_provider_by_id(db: Session, provider_id: str) -> ProviderConfig | None:
    provider = db.get(UpstreamProvider, provider_id)
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


def load_primary_upstream_model_id(model_id: str) -> str:
    for model in get_settings().public_models:
        if model["id"] == model_id:
            return str(model.get("upstream_model_id", model_id))
    return model_id


def load_failover_providers_for_model(db: Session, model_id: str) -> list[FailoverProvider]:
    settings = get_settings()
    model_row = db.get(ModelConfig, model_id)
    primary_provider = db.get(UpstreamProvider, model_row.provider_id) if model_row else None
    primary_url = primary_provider.base_url.rstrip("/") if primary_provider else ""
    result: list[FailoverProvider] = []

    for provider_config in settings.additional_upstreams:
        if primary_url and provider_config["base_url"].rstrip("/") == primary_url:
            continue
        for model_config in provider_config["models"]:
            if (
                model_config.get("fallback_for") != model_id
                or not model_config.get("enabled", True)
            ):
                continue

            provider = db.scalar(
                select(UpstreamProvider).where(UpstreamProvider.base_url == provider_config["base_url"])
            )
            if provider:
                config = load_provider_by_id(db, provider.id)
            else:
                config = ProviderConfig(
                    base_url=provider_config["base_url"],
                    api_key=provider_config["api_key"],
                    timeout_seconds=int(provider_config.get("timeout_seconds", settings.upstream_timeout_seconds)),
                    default_size=provider_config.get("default_size", settings.upstream_default_size),
                    default_quality=provider_config.get("default_quality", settings.upstream_default_quality),
                    default_output_format=provider_config.get("default_output_format", settings.upstream_default_output_format),
                    default_output_compression=int(provider_config.get("default_output_compression", settings.upstream_default_output_compression)),
                    default_background=provider_config.get("default_background", settings.upstream_default_background),
                    default_moderation=provider_config.get("default_moderation", settings.upstream_default_moderation),
                )
            if config:
                result.append(FailoverProvider(
                    name=provider_config["name"],
                    config=config,
                    model_id=str(model_config.get("upstream_model_id", model_id)),
                    max_reference_images=(
                        max(1, int(model_config.get("max_reference_images", 1)))
                        if model_config.get("supports_reference_image", False)
                        else 0
                    ),
                ))
    return result
