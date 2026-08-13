from sqlalchemy import select

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
    """Seed upstream_providers and model_configs from .env settings on first run.

    Only runs when the upstream_providers table is empty, so existing deployments
    are not affected after the initial migration.
    """
    settings = get_settings()
    db = SessionLocal()
    try:
        existing = db.scalar(select(UpstreamProvider).limit(1))
        if existing:
            return

        provider = UpstreamProvider(
            name="默认上游",
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

        for index, model_dict in enumerate(settings.public_models):
            model = ModelConfig(
                id=model_dict["id"],
                provider_id=provider.id,
                label=model_dict.get("label", model_dict["id"]),
                enabled=bool(model_dict.get("enabled", True)),
                supports_reference_image=bool(model_dict.get("supports_reference_image", True)),
                supported_sizes=list(model_dict.get("supported_sizes", [])),
                sort_order=index,
                credit_cost=max(1, int(model_dict.get("credit_cost", 2))),
            )
            db.add(model)

        db.commit()
    finally:
        db.close()
