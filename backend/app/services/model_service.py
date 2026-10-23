from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.model_config import ModelConfig
from app.models.upstream_provider import UpstreamProvider
from app.services.model_pricing import size_pricing_tier


OPENAI_GPT_IMAGE_STANDARD_SIZES = [
    "auto",
    "1024x1024",
    "1280x720",
    "720x1280",
    "1536x1024",
    "1024x1536",
    "1792x1024",
    "1024x1792",
    "2048x2048",
    "2048x1152",
    "1152x2048",
    "3840x2160",
    "2160x3840",
]


def _size_route_models(model_id: str, tier: str, settings=None) -> list[dict[str, Any]]:
    config = settings or get_settings()
    return [
        model
        for provider in config.additional_upstreams
        for model in provider["models"]
        if model.get("fallback_for") == model_id
        and model.get("enabled", True)
        and tier in {str(value).strip().lower() for value in model.get("route_for_sizes", [])}
    ]


def has_configured_size_route_for_model(
    model_id: str,
    tier: str,
    *,
    size: str | None = None,
    settings=None,
) -> bool:
    routes = _size_route_models(model_id, tier, settings)
    if size is None:
        return bool(routes)
    if not routes:
        return False
    return any(
        not isinstance(route.get("supported_sizes"), list)
        or not route.get("supported_sizes")
        or size in route["supported_sizes"]
        for route in routes
    )


def _public_model_sizes(model_id: str, configured_sizes: list[str] | None, settings=None) -> list[str]:
    sizes = list(configured_sizes or [])
    if not model_id.startswith("gpt-image-2"):
        return sizes

    if not sizes:
        sizes = list(OPENAI_GPT_IMAGE_STANDARD_SIZES)
    size_routes = _size_route_models(model_id, "4k", settings)
    if not size_routes:
        sizes = [size for size in sizes if size_pricing_tier(size) != "4k"]
    else:
        declared = [route.get("supported_sizes") for route in size_routes]
        route_sizes = [size for allowed in declared if isinstance(allowed, list) for size in allowed]
        if any(not isinstance(allowed, list) or not allowed for allowed in declared):
            route_sizes = ["3840x2160", "2160x3840"]
        sizes = list(dict.fromkeys(
            [size for size in sizes if size_pricing_tier(size) != "4k"]
            + [size for size in route_sizes if size_pricing_tier(size) == "4k"]
        ))
    return sizes or ["auto"]


def apply_public_model_size_capabilities(models: list[dict[str, Any]], settings=None) -> list[dict[str, Any]]:
    return [
        {
            **model,
            "supported_sizes": _public_model_sizes(
                str(model["id"]), model.get("supported_sizes"), settings,
            ),
        }
        for model in models
    ]


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


def load_models_from_db(db: Session) -> list[dict[str, Any]]:
    stmt = select(ModelConfig).order_by(ModelConfig.sort_order, ModelConfig.id)
    models = db.scalars(stmt).all()
    result = [
        {
            "id": m.id,
            "label": m.label,
            "enabled": m.enabled,
            "supports_reference_image": m.supports_reference_image,
            "max_reference_images": m.max_reference_images if m.max_reference_images is not None else 5,
            "supported_sizes": list(m.supported_sizes) if m.supported_sizes else [],
            "credit_cost": m.credit_cost if m.credit_cost is not None else 2,
            "credit_cost_by_size": dict(m.credit_cost_by_size) if isinstance(m.credit_cost_by_size, dict) else {},
        }
        for m in models
    ]
    return apply_public_model_size_capabilities(result)


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


def _load_additional_provider(db: Session, provider_config: dict[str, Any], settings) -> ProviderConfig | None:
    provider = db.scalar(
        select(UpstreamProvider)
        .where(
            UpstreamProvider.name == provider_config["name"],
            UpstreamProvider.base_url == provider_config["base_url"],
        )
        .order_by(UpstreamProvider.created_at)
        .limit(1)
    )
    if not provider:
        provider = db.scalar(
            select(UpstreamProvider)
            .where(
                UpstreamProvider.base_url == provider_config["base_url"],
                UpstreamProvider.api_key == provider_config["api_key"],
            )
            .order_by(UpstreamProvider.created_at)
            .limit(1)
        )
    if provider:
        return load_provider_by_id(db, provider.id)
    return ProviderConfig(
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


def _reference_limit(model_config: dict[str, Any]) -> int:
    return (
        max(1, int(model_config.get("max_reference_images", 1)))
        if model_config.get("supports_reference_image", False)
        else 0
    )


def load_size_route_providers_for_model(db: Session, model_id: str, size: str) -> list[FailoverProvider]:
    settings = get_settings()
    tier = size_pricing_tier(size)
    result: list[FailoverProvider] = []
    for provider_config in settings.additional_upstreams:
        for model_config in provider_config["models"]:
            route_for_sizes = {
                str(route_size).strip().lower()
                for route_size in model_config.get("route_for_sizes", [])
            }
            if (
                model_config.get("fallback_for") != model_id
                or not model_config.get("enabled", True)
                or tier not in route_for_sizes
                or (
                    isinstance(model_config.get("supported_sizes"), list)
                    and model_config.get("supported_sizes")
                    and size not in model_config["supported_sizes"]
                )
            ):
                continue
            config = _load_additional_provider(db, provider_config, settings)
            if config:
                result.append(FailoverProvider(
                    name=provider_config["name"],
                    config=config,
                    model_id=str(model_config.get("upstream_model_id", model_id)),
                    max_reference_images=_reference_limit(model_config),
                ))
    return result


def load_failover_providers_for_model(db: Session, model_id: str) -> list[FailoverProvider]:
    settings = get_settings()
    model_row = db.get(ModelConfig, model_id)
    primary_provider = db.get(UpstreamProvider, model_row.provider_id) if model_row else None
    primary_url = primary_provider.base_url.rstrip("/") if primary_provider else ""
    primary_key = primary_provider.api_key if primary_provider else ""
    result: list[FailoverProvider] = []

    for provider_config in settings.additional_upstreams:
        if primary_url and provider_config["base_url"].rstrip("/") == primary_url:
            continue
        for model_config in provider_config["models"]:
            if (
                model_config.get("fallback_for") != model_id
                or not model_config.get("enabled", True)
                or model_config.get("route_for_sizes")
            ):
                continue
            if (
                primary_url
                and provider_config["base_url"].rstrip("/") == primary_url
                and provider_config["api_key"] == primary_key
            ):
                continue

            config = _load_additional_provider(db, provider_config, settings)
            if config:
                result.append(FailoverProvider(
                    name=provider_config["name"],
                    config=config,
                    model_id=str(model_config.get("upstream_model_id", model_id)),
                    max_reference_images=_reference_limit(model_config),
                ))
    return result
