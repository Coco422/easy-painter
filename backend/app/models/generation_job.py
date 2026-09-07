from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Enum as SqlEnum, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.media import MediaState


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class GenerationJob(Base):
    __tablename__ = "generation_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_generation_job_user_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    status: Mapped[JobStatus] = mapped_column(
        SqlEnum(JobStatus, native_enum=False),
        default=JobStatus.QUEUED,
        index=True,
    )
    prompt: Mapped[str] = mapped_column(Text)
    revised_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(128))
    model_label_snapshot: Mapped[str | None] = mapped_column(String(256), nullable=True)
    provider_id_snapshot: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider_name_snapshot: Mapped[str | None] = mapped_column(String(128), nullable=True)
    credit_cost_snapshot: Mapped[int] = mapped_column(Integer, default=0)
    group_code_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    group_name_snapshot: Mapped[str | None] = mapped_column(String(128), nullable=True)
    base_credit_cost_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    billing_multiplier_bps_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generated_retention_hours_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size: Mapped[str] = mapped_column(String(32), default="auto")
    aspect_ratio: Mapped[str] = mapped_column(String(16), default="auto")
    reference_images: Mapped[list[dict[str, str]] | None] = mapped_column(JSON, nullable=True)
    reference_image_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reference_image_content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reference_image_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    public_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    media_state: Mapped[MediaState] = mapped_column(
        SqlEnum(
            MediaState,
            native_enum=False,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=MediaState.NONE,
        index=True,
    )
    media_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    media_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    media_content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    media_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_job_meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_prompt_public: Mapped[bool] = mapped_column(Boolean, default=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)
