from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("upstream_providers.id"), index=True)
    label: Mapped[str] = mapped_column(String(256))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_reference_image: Mapped[bool] = mapped_column(Boolean, default=True)
    supported_sizes: Mapped[list] = mapped_column(JSON, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
