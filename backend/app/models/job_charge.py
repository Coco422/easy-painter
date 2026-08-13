from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum as SqlEnum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobChargeStatus(str, Enum):
    RESERVED = "reserved"
    SETTLED = "settled"
    REFUNDED = "refunded"


class JobCharge(Base):
    __tablename__ = "job_charges"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_job_charges_amount_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    job_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[JobChargeStatus] = mapped_column(
        SqlEnum(
            JobChargeStatus,
            native_enum=False,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=JobChargeStatus.RESERVED,
        index=True,
    )
    reserve_transaction_id: Mapped[str] = mapped_column(String(36), unique=True)
    refund_transaction_id: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)
    model_label: Mapped[str] = mapped_column(String(256))
    provider_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    group_code_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    group_name_snapshot: Mapped[str | None] = mapped_column(String(128), nullable=True)
    base_credit_cost_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    billing_multiplier_bps_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
