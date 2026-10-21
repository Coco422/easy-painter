import logging

from sqlalchemy import or_, select

from app.core.auth import hash_password
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.announcement import Announcement
from app.models.credit_transaction import CreditTransaction
from app.models.gallery_like import GalleryLike
from app.models.generation_job import GenerationJob
from app.models.inspiration import Inspiration
from app.models.job_charge import JobCharge
from app.models.media import MediaDeletionTask
from app.models.model_config import ModelConfig
from app.models.outbox_event import OutboxEvent
from app.models.redemption_code import RedemptionCode
from app.models.reference_image import ReferenceImage
from app.models.upstream_provider import UpstreamProvider
from app.models.user import User
from app.models.user_group import UserGroup
from app.models.user_group import STANDARD_GROUP_CODE
from app.services.group_policy import get_default_group
from app.services.model_pricing import normalize_credit_cost_by_size


logger = logging.getLogger(__name__)


def init_db() -> None:
    _ = Announcement
    _ = CreditTransaction
    _ = GalleryLike
    _ = GenerationJob
    _ = RedemptionCode
    _ = ReferenceImage
    _ = User
    _ = UpstreamProvider
    _ = ModelConfig
    _ = Inspiration
    _ = JobCharge
    _ = MediaDeletionTask
    _ = OutboxEvent
    _ = UserGroup
    _ensure_default_user()
    _seed_providers_and_models()


def _ensure_default_user() -> None:
    settings = get_settings()
    if not settings.default_password:
        return
    db = SessionLocal()
    try:
        existing = db.scalar(select(User).limit(1))
        if existing:
            return
        default_group = get_default_group(db)
        user = User(
            username=settings.default_username,
            email=settings.default_email.strip().lower() or None,
            password_hash=hash_password(settings.default_password),
            display_name=settings.default_username,
            group_code=default_group.code if default_group else STANDARD_GROUP_CODE,
        )
        db.add(user)
        db.commit()
    finally:
        db.close()


def _seed_providers_and_models() -> None:
    """Seed configured providers and models without destructive database changes.

    The optional sync mode is intended for deployments that explicitly make the
    environment authoritative for the public model list. In that mode, configured
    primary models are updated and unlisted models are disabled, never deleted.
    """
    settings = get_settings()
    db = SessionLocal()
    try:
        provider = db.scalar(
            select(UpstreamProvider).where(
                or_(
                    UpstreamProvider.name == settings.upstream_provider_name,
                    UpstreamProvider.base_url == settings.upstream_base_url,
                )
            )
        )
        if not provider:
            provider = UpstreamProvider(
                name=settings.upstream_provider_name,
                base_url=settings.upstream_base_url,
                api_key=settings.upstream_api_key,
                timeout_seconds=settings.upstream_timeout_seconds,
                default_size=settings.upstream_default_size,
                default_quality=settings.upstream_default_quality,
                default_output_format=settings.upstream_default_output_format,
                default_output_compression=settings.upstream_default_output_compression,
                default_background=settings.upstream_default_background,
                default_moderation=settings.upstream_default_moderation,
            )
            db.add(provider)
            db.flush()
        elif settings.sync_public_models_from_env:
            provider.name = settings.upstream_provider_name
            provider.base_url = settings.upstream_base_url
            provider.api_key = settings.upstream_api_key
            provider.timeout_seconds = settings.upstream_timeout_seconds
            provider.default_size = settings.upstream_default_size
            provider.default_quality = settings.upstream_default_quality
            provider.default_output_format = settings.upstream_default_output_format
            provider.default_output_compression = settings.upstream_default_output_compression
            provider.default_background = settings.upstream_default_background
            provider.default_moderation = settings.upstream_default_moderation

        configured_model_ids: set[str] = set()
        for index, model_dict in enumerate(settings.public_models):
            model_id = str(model_dict["id"])
            configured_model_ids.add(model_id)
            model = db.get(ModelConfig, model_id)
            if model and not settings.sync_public_models_from_env:
                continue
            if not model:
                model = ModelConfig(id=model_id, provider_id=provider.id)
                db.add(model)
            model.provider_id = provider.id
            model.label = model_dict.get("label", model_id)
            model.enabled = bool(model_dict.get("enabled", True))
            model.supports_reference_image = bool(model_dict.get("supports_reference_image", True))
            model.max_reference_images = max(1, int(model_dict.get("max_reference_images", 5)))
            model.supported_sizes = list(model_dict.get("supported_sizes", []))
            model.sort_order = int(model_dict.get("sort_order", index))
            model.credit_cost = max(1, int(model_dict.get("credit_cost", 2)))
            model.credit_cost_by_size = normalize_credit_cost_by_size(model_dict.get("credit_cost_by_size"))

        for provider_config in settings.additional_upstreams:
            provider = db.scalar(
                select(UpstreamProvider).where(
                    or_(
                        UpstreamProvider.name == provider_config["name"],
                        UpstreamProvider.base_url == provider_config["base_url"],
                    )
                )
            )
            if provider and (
                provider.name != provider_config["name"]
                or provider.base_url.rstrip("/") != provider_config["base_url"].rstrip("/")
            ):
                logger.warning(
                    "Skipping additional upstream %s because its name or base URL conflicts with an existing provider.",
                    provider_config["name"],
                )
                continue
            if not provider:
                provider = UpstreamProvider(
                    name=provider_config["name"],
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
                db.add(provider)
                db.flush()
            elif settings.sync_public_models_from_env:
                provider.api_key = provider_config["api_key"]
                provider.timeout_seconds = int(provider_config.get("timeout_seconds", settings.upstream_timeout_seconds))
                provider.default_size = provider_config.get("default_size", settings.upstream_default_size)
                provider.default_quality = provider_config.get("default_quality", settings.upstream_default_quality)
                provider.default_output_format = provider_config.get("default_output_format", settings.upstream_default_output_format)
                provider.default_output_compression = int(provider_config.get("default_output_compression", settings.upstream_default_output_compression))
                provider.default_background = provider_config.get("default_background", settings.upstream_default_background)
                provider.default_moderation = provider_config.get("default_moderation", settings.upstream_default_moderation)

            for index, model_config in enumerate(provider_config["models"]):
                # Fallback entries reuse a public model ID and are resolved from
                # the provider settings at runtime. They must not claim a second
                # public ModelConfig row (model IDs are globally unique).
                if model_config.get("fallback_for"):
                    continue
                model_id = model_config["id"]
                configured_model_ids.add(model_id)
                existing_model = db.get(ModelConfig, model_id)
                if existing_model:
                    if existing_model.provider_id != provider.id:
                        logger.warning(
                            "Skipping additional upstream model %s: that model ID is already assigned to another provider.",
                            model_id,
                        )
                    elif settings.sync_public_models_from_env:
                        existing_model.label = model_config.get("label", model_id)
                        existing_model.enabled = bool(model_config.get("enabled", True))
                        existing_model.supports_reference_image = bool(model_config.get("supports_reference_image", False))
                        existing_model.max_reference_images = max(1, int(model_config.get("max_reference_images", 1)))
                        existing_model.supported_sizes = list(model_config.get("supported_sizes", []))
                        existing_model.sort_order = int(model_config.get("sort_order", index))
                        existing_model.credit_cost = max(1, int(model_config.get("credit_cost", 2)))
                        existing_model.credit_cost_by_size = normalize_credit_cost_by_size(model_config.get("credit_cost_by_size"))
                    continue
                db.add(ModelConfig(
                    id=model_id,
                    provider_id=provider.id,
                    label=model_config.get("label", model_id),
                    enabled=bool(model_config.get("enabled", True)),
                    supports_reference_image=bool(model_config.get("supports_reference_image", False)),
                    max_reference_images=max(1, int(model_config.get("max_reference_images", 1))),
                    supported_sizes=list(model_config.get("supported_sizes", [])),
                    sort_order=int(model_config.get("sort_order", index)),
                    credit_cost=max(1, int(model_config.get("credit_cost", 2))),
                    credit_cost_by_size=normalize_credit_cost_by_size(model_config.get("credit_cost_by_size")),
                ))

        if settings.sync_public_models_from_env:
            for model in db.scalars(select(ModelConfig)).all():
                if model.id not in configured_model_ids:
                    model.enabled = False
        db.commit()
    finally:
        db.close()
