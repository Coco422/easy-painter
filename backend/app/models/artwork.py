from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (
        CheckConstraint("(job_id IS NOT NULL AND inspiration_id IS NULL) OR (job_id IS NULL AND inspiration_id IS NOT NULL)", name="ck_favorite_one_target"),
        UniqueConstraint("user_id", "job_id", name="uq_favorite_user_job"),
        UniqueConstraint("user_id", "inspiration_id", name="uq_favorite_user_inspiration"),
        Index("ix_favorites_user_created", "user_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"))
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    inspiration_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CommunitySubmission(Base):
    __tablename__ = "community_submissions"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected', 'withdrawn', 'expired')", name="ck_submission_status"),
        Index("ix_submissions_status_submitted", "status", "submitted_at", "job_id"),
    )

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    inspiration_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
