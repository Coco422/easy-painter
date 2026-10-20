from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.payment import CreditAllocation, CreditLot


class CreditProvenanceError(RuntimeError):
    pass


def add_credit_lot(db: Session, *, user_id: str, amount: int, source_type: str, source_id: str,
                   amount_fen: int = 0, recharge_order_id: str | None = None) -> None:
    if amount <= 0:
        return
    db.add(CreditLot(user_id=user_id, source_type=source_type, source_id=source_id,
                     total_credits=amount, remaining_credits=amount, amount_fen=amount_fen,
                     recharge_order_id=recharge_order_id))


def ensure_credit_provenance(db: Session, *, user_id: str, balance: int) -> None:
    """Caller holds the user lock. Unclassified balances never become cash."""
    db.flush()
    covered = db.scalar(select(func.coalesce(func.sum(CreditLot.remaining_credits), 0)).where(CreditLot.user_id == user_id)) or 0
    if covered > balance:
        raise CreditProvenanceError("credit provenance exceeds account balance")
    if balance > covered:
        add_credit_lot(db, user_id=user_id, amount=balance-covered, source_type="legacy", source_id=f"legacy:{uuid4()}")
        db.flush()


def allocate_credits(db: Session, *, user_id: str, amount: int, transaction_id: str, job_id: str | None = None) -> None:
    """Noncash first, then FIFO paid lots; runs in the debit transaction."""
    if amount <= 0:
        return
    db.flush()
    lots = db.scalars(select(CreditLot).where(CreditLot.user_id == user_id, CreditLot.remaining_credits > 0)
        .order_by(case((CreditLot.source_type == "paid", 1), else_=0), CreditLot.created_at, CreditLot.id).with_for_update()).all()
    remaining = amount
    for lot in lots:
        used = min(lot.remaining_credits, remaining)
        lot.remaining_credits -= used
        db.add(CreditAllocation(user_id=user_id, lot_id=lot.id, transaction_id=transaction_id, job_id=job_id,
            credits=used, source_type_snapshot=lot.source_type, amount_fen_snapshot=lot.amount_fen,
            total_credits_snapshot=lot.total_credits))
        remaining -= used
        if remaining == 0:
            break
    if remaining:
        raise CreditProvenanceError("credit provenance cannot cover debit")


def reverse_job_allocations(db: Session, *, user_id: str, job_id: str, amount: int, now: datetime) -> None:
    db.flush()
    allocations = db.scalars(select(CreditAllocation).where(CreditAllocation.job_id == job_id, CreditAllocation.user_id == user_id)
        .order_by(CreditAllocation.lot_id).with_for_update()).all()
    if not allocations:
        # Reservations made before V13 have no allocation history.
        add_credit_lot(db, user_id=user_id, amount=amount, source_type="legacy", source_id=f"legacy-job-refund:{job_id}")
        return
    if sum(item.credits for item in allocations) != amount or any(item.reversed_at for item in allocations):
        raise CreditProvenanceError("invalid refund allocation")
    for item in allocations:
        lot = db.scalar(select(CreditLot).where(CreditLot.id == item.lot_id).with_for_update().execution_options(populate_existing=True))
        if lot is None or lot.remaining_credits + item.credits > lot.total_credits:
            raise CreditProvenanceError("invalid refund lot")
        lot.remaining_credits += item.credits
        item.reversed_at = now
