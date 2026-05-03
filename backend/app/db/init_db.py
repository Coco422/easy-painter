from sqlalchemy import inspect, select, text

from app.core.auth import hash_password
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.gallery_like import GalleryLike
from app.models.generation_job import GenerationJob
from app.models.model_config import ModelConfig
from app.models.upstream_provider import UpstreamProvider
from app.models.user import User


def init_db() -> None:
    _ = GalleryLike
    _ = GenerationJob
    _ = User
    _ = UpstreamProvider
    _ = ModelConfig
    Base.metadata.create_all(bind=engine)
    _ensure_generation_job_columns()
    _ensure_default_user()
    _seed_providers_and_models()


def _ensure_generation_job_columns() -> None:
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("generation_jobs")}
    missing_columns = {
        "size": "ALTER TABLE generation_jobs ADD COLUMN size VARCHAR(32) DEFAULT 'auto'",
        "aspect_ratio": "ALTER TABLE generation_jobs ADD COLUMN aspect_ratio VARCHAR(16) DEFAULT 'auto'",
        "reference_image_key": "ALTER TABLE generation_jobs ADD COLUMN reference_image_key VARCHAR(512)",
        "reference_image_content_type": "ALTER TABLE generation_jobs ADD COLUMN reference_image_content_type VARCHAR(128)",
        "reference_image_filename": "ALTER TABLE generation_jobs ADD COLUMN reference_image_filename VARCHAR(255)",
        "user_id": "ALTER TABLE generation_jobs ADD COLUMN user_id VARCHAR(36)",
        "is_public": "ALTER TABLE generation_jobs ADD COLUMN is_public BOOLEAN DEFAULT FALSE",
        "is_favorite": "ALTER TABLE generation_jobs ADD COLUMN is_favorite BOOLEAN DEFAULT FALSE",
    }

    with engine.begin() as connection:
        for column, ddl in missing_columns.items():
            if column not in columns:
                connection.execute(text(ddl))
        connection.execute(
            text(
                """
                UPDATE generation_jobs
                SET size = CASE aspect_ratio
                    WHEN '1:1' THEN '1024x1024'
                    WHEN '3:4' THEN '1024x1536'
                    WHEN '9:16' THEN '1024x1792'
                    WHEN '4:3' THEN '1536x1024'
                    WHEN '16:9' THEN '1792x1024'
                    ELSE size
                END
                WHERE size = 'auto' AND aspect_ratio IS NOT NULL AND aspect_ratio != 'auto'
                """
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_generation_jobs_user_id ON generation_jobs (user_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_generation_jobs_is_public ON generation_jobs (is_public)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_generation_jobs_is_favorite ON generation_jobs (is_favorite)"))


def _ensure_default_user() -> None:
    settings = get_settings()
    if not settings.default_password:
        return
    db = SessionLocal()
    try:
        existing = db.scalar(select(User).limit(1))
        if existing:
            return
        user = User(
            username=settings.default_username,
            password_hash=hash_password(settings.default_password),
            display_name=settings.default_username,
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
            )
            db.add(model)

        db.commit()
    finally:
        db.close()
