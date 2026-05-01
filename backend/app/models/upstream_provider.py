from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UpstreamProvider(Base):
    __tablename__ = "upstream_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(128))
    base_url: Mapped[str] = mapped_column(String(512))
    api_key: Mapped[str] = mapped_column(String(512))
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=700)
    default_size: Mapped[str] = mapped_column(String(32), default="auto")
    default_quality: Mapped[str] = mapped_column(String(32), default="high")
    default_output_format: Mapped[str] = mapped_column(String(32), default="jpeg")
    default_output_compression: Mapped[int] = mapped_column(Integer, default=85)
    default_background: Mapped[str] = mapped_column(String(32), default="auto")
    default_moderation: Mapped[str] = mapped_column(String(32), default="auto")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
