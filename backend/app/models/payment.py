from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PaymentConfiguration(Base):
    """Immutable revisions keep in-flight orders bound to their original merchant."""
    __tablename__ = "payment_configurations"

    revision: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    gateway_url: Mapped[str] = mapped_column(String(256))
    merchant_id: Mapped[str] = mapped_column(String(64))
    key_ciphertext: Mapped[str] = mapped_column(Text)
    public_base_url: Mapped[str] = mapped_column(String(256))
    payment_methods: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RechargePackage(Base):
    __tablename__ = "recharge_packages"
    __table_args__ = (
        CheckConstraint("price_fen > 0 AND paid_credits > 0 AND gift_credits >= 0", name="ck_recharge_package_amounts"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(80))
    price_fen: Mapped[int] = mapped_column(Integer)
    paid_credits: Mapped[int] = mapped_column(Integer)
    gift_credits: Mapped[int] = mapped_column(Integer, default=0)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RechargeOrder(Base):
    __tablename__ = "recharge_orders"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_recharge_user_intent"),
        UniqueConstraint("gateway_url", "merchant_id", "provider_trade_no", name="uq_recharge_provider_trade"),
        CheckConstraint("amount_fen > 0 AND paid_credits > 0 AND gift_credits >= 0", name="ck_recharge_order_amounts"),
        CheckConstraint("status IN ('pending', 'paid')", name="ck_recharge_order_status"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    package_id: Mapped[str] = mapped_column(String(36), ForeignKey("recharge_packages.id"))
    package_revision: Mapped[int] = mapped_column(Integer)
    package_name: Mapped[str] = mapped_column(String(80))
    amount_fen: Mapped[int] = mapped_column(Integer)
    paid_credits: Mapped[int] = mapped_column(Integer)
    gift_credits: Mapped[int] = mapped_column(Integer)
    payment_method: Mapped[str] = mapped_column(String(16))
    gateway_url: Mapped[str] = mapped_column(String(256))
    merchant_id: Mapped[str] = mapped_column(String(64))
    config_revision: Mapped[int | None] = mapped_column(ForeignKey("payment_configurations.revision"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    provider_trade_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    credit_transaction_id: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_check_error: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CreditLot(Base):
    """Credit provenance. Only paid recharge lots carry a cash basis."""
    __tablename__ = "credit_lots"
    __table_args__ = (
        CheckConstraint("total_credits > 0 AND remaining_credits >= 0 AND remaining_credits <= total_credits", name="ck_credit_lot_balance"),
        CheckConstraint("amount_fen >= 0 AND (source_type = 'paid' OR amount_fen = 0)", name="ck_credit_lot_cash_basis"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(24))
    source_id: Mapped[str] = mapped_column(String(160), unique=True)
    recharge_order_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("recharge_orders.id"), nullable=True, index=True)
    total_credits: Mapped[int] = mapped_column(Integer)
    remaining_credits: Mapped[int] = mapped_column(Integer)
    amount_fen: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CreditAllocation(Base):
    """Exact cash basis = amount_fen_snapshot * credits / total_credits_snapshot.

    Do not round each small job to fen. Future commissions can accumulate the
    rational amount before payout. Refunded reservations retain these records.
    """
    __tablename__ = "credit_allocations"
    __table_args__ = (
        UniqueConstraint("transaction_id", "lot_id", name="uq_credit_allocation_transaction_lot"),
        CheckConstraint("credits > 0 AND amount_fen_snapshot >= 0 AND total_credits_snapshot > 0", name="ck_credit_allocation_amounts"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    lot_id: Mapped[str] = mapped_column(String(36), ForeignKey("credit_lots.id"), index=True)
    transaction_id: Mapped[str] = mapped_column(String(36), index=True)
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    credits: Mapped[int] = mapped_column(Integer)
    source_type_snapshot: Mapped[str] = mapped_column(String(24))
    amount_fen_snapshot: Mapped[int] = mapped_column(Integer)
    total_credits_snapshot: Mapped[int] = mapped_column(Integer)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
