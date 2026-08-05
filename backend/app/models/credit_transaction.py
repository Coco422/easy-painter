from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Enum as SqlEnum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CreditTransactionType(str, Enum):
    OPENING_BALANCE = "opening_balance"
    REDEEM = "redeem"
    JOB_RESERVE = "job_reserve"
    JOB_REFUND = "job_refund"
    ADMIN_ADJUST = "admin_adjust"
    RECONCILIATION = "reconciliation"


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(256))
    transaction_type: Mapped[CreditTransactionType] = mapped_column(
        SqlEnum(
            CreditTransactionType,
            native_enum=False,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=CreditTransactionType.RECONCILIATION,
        index=True,
    )
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    related_transaction_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True, unique=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
