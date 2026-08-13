from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import BigInteger, DateTime, Enum as SqlEnum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.media import MediaState


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReferenceImage(Base):
    __tablename__ = "reference_images"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    object_key: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(128))
    filename: Mapped[str] = mapped_column(String(255))
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    group_code_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    group_name_snapshot: Mapped[str | None] = mapped_column(String(128), nullable=True)
    retention_hours_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    media_state: Mapped[MediaState] = mapped_column(
        SqlEnum(
            MediaState,
            native_enum=False,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=MediaState.AVAILABLE,
        index=True,
    )
    media_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    media_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    media_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
