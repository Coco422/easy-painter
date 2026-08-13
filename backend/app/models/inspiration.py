from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Enum as SqlEnum, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.media import MediaState


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Inspiration(Base):
    __tablename__ = "inspirations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt: Mapped[str] = mapped_column(Text)
    image_url: Mapped[str] = mapped_column(String(512))
    image_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    media_state: Mapped[MediaState] = mapped_column(
        SqlEnum(
            MediaState,
            native_enum=False,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=MediaState.AVAILABLE,
        index=True,
    )
    media_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    media_content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(128), index=True)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    author_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    author_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="zh")
    categories: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    source_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    source_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    curated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_inspiration_source_ext_id"),
    )
