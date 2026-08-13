from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import DateTime, Enum as SqlEnum, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MediaState(str, Enum):
    NONE = "none"
    AVAILABLE = "available"
    DELETE_PENDING = "delete_pending"
    DELETED = "deleted"


class MediaDeletionStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"


class MediaDeletionTask(Base):
    __tablename__ = "media_deletion_tasks"
    __table_args__ = (
        UniqueConstraint("bucket_type", "object_key", name="uq_media_deletion_object"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    bucket_type: Mapped[str] = mapped_column(String(24))
    object_key: Mapped[str] = mapped_column(String(512))
    resource_type: Mapped[str] = mapped_column(String(32))
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[MediaDeletionStatus] = mapped_column(
        SqlEnum(
            MediaDeletionStatus,
            native_enum=False,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=MediaDeletionStatus.PENDING,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
