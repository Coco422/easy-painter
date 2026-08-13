from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


STANDARD_GROUP_CODE = "standard"
VIP_GROUP_CODE = "vip"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserGroup(Base):
    __tablename__ = "user_groups"
    __table_args__ = (
        CheckConstraint(
            "billing_multiplier_bps >= 0 AND billing_multiplier_bps <= 100000",
            name="ck_user_groups_multiplier",
        ),
        CheckConstraint(
            "generated_retention_hours >= 1 AND generated_retention_hours <= 87600",
            name="ck_user_groups_generated_retention",
        ),
        CheckConstraint(
            "reference_retention_hours >= 1 AND reference_retention_hours <= 87600",
            name="ck_user_groups_reference_retention",
        ),
        CheckConstraint(
            "max_reference_images >= 0 AND max_reference_images <= 10000",
            name="ck_user_groups_reference_limit",
        ),
    )

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    billing_multiplier_bps: Mapped[int] = mapped_column(Integer, default=10_000)
    generated_retention_hours: Mapped[int] = mapped_column(Integer, default=24)
    reference_retention_hours: Mapped[int] = mapped_column(Integer, default=24)
    max_reference_images: Mapped[int] = mapped_column(Integer, default=3)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
