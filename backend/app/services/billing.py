from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.credit_transaction import CreditTransaction, CreditTransactionType
from app.models.generation_job import GenerationJob, JobStatus
from app.models.job_charge import JobCharge, JobChargeStatus
from app.models.redemption_code import RedemptionCode
from app.models.user import User


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InsufficientCreditsError(RuntimeError):
    def __init__(self, *, required: int, balance: int) -> None:
        super().__init__("insufficient credits")
        self.required = required
        self.balance = balance


class LedgerIntegrityError(RuntimeError):
    pass


def reserve_job_credits(
    db: Session,
    *,
    job: GenerationJob,
    user_id: str,
    amount: int,
    model_label: str,
    provider_name: str | None,
    group_code: str | None = None,
    group_name: str | None = None,
    base_credit_cost: int | None = None,
    billing_multiplier_bps: int | None = None,
) -> tuple[JobCharge | None, int]:
    if amount < 0:
        raise ValueError("charge amount cannot be negative")

    balance = db.scalar(
        update(User)
        .where(User.id == user_id, User.credits >= amount)
        .values(credits=User.credits - amount)
        .returning(User.credits)
    )
    if balance is None:
        current_balance = db.scalar(select(User.credits).where(User.id == user_id)) or 0
        raise InsufficientCreditsError(required=amount, balance=current_balance)

    transaction_id = str(uuid4())
    transaction = CreditTransaction(
        id=transaction_id,
        user_id=user_id,
        amount=-amount,
        balance_after=balance,
        reason=f"job:{job.id}",
        transaction_type=CreditTransactionType.JOB_RESERVE,
        job_id=job.id,
        idempotency_key=f"job-reserve:{job.id}",
        details={
            "model_label": model_label,
            "provider_name": provider_name,
            "credit_cost": amount,
            "group_code": group_code,
            "group_name": group_name,
            "base_credit_cost": base_credit_cost,
            "billing_multiplier_bps": billing_multiplier_bps,
        },
    )
    charge = JobCharge(
        job_id=job.id,
        user_id=user_id,
        amount=amount,
        status=JobChargeStatus.RESERVED,
        reserve_transaction_id=transaction_id,
        model_label=model_label,
        provider_name=provider_name,
        group_code_snapshot=group_code,
        group_name_snapshot=group_name,
        base_credit_cost_snapshot=base_credit_cost,
        billing_multiplier_bps_snapshot=billing_multiplier_bps,
    )
    db.add_all([transaction, charge])
    return charge, balance


def settle_job_charge(db: Session, *, job_id: str, now: datetime | None = None) -> JobCharge | None:
    charge = db.scalar(select(JobCharge).where(JobCharge.job_id == job_id).with_for_update())
    if not charge or charge.status != JobChargeStatus.RESERVED:
        return charge
    charge.status = JobChargeStatus.SETTLED
    charge.settled_at = now or utcnow()
    return charge


def refund_job_charge(
    db: Session,
    *,
    job_id: str,
    reason: str,
    now: datetime | None = None,
) -> JobCharge | None:
    charge = db.scalar(select(JobCharge).where(JobCharge.job_id == job_id).with_for_update())
    if not charge or charge.status != JobChargeStatus.RESERVED:
        return charge

    refunded_at = now or utcnow()
    balance = db.scalar(
        update(User)
        .where(User.id == charge.user_id)
        .values(credits=User.credits + charge.amount)
        .returning(User.credits)
    )
    if balance is None:
        raise RuntimeError("charge owner no longer exists")

    refund_id = str(uuid4())
    db.add(
        CreditTransaction(
            id=refund_id,
            user_id=charge.user_id,
            amount=charge.amount,
            balance_after=balance,
            reason=f"job-refund:{job_id}",
            transaction_type=CreditTransactionType.JOB_REFUND,
            job_id=job_id,
            related_transaction_id=charge.reserve_transaction_id,
            idempotency_key=f"job-refund:{job_id}",
            details={
                "model_label": charge.model_label,
                "provider_name": charge.provider_name,
                "refund_reason": reason,
                "group_code": charge.group_code_snapshot,
                "group_name": charge.group_name_snapshot,
                "base_credit_cost": charge.base_credit_cost_snapshot,
                "billing_multiplier_bps": charge.billing_multiplier_bps_snapshot,
                "credit_cost": charge.amount,
            },
            created_at=refunded_at,
        )
    )
    charge.status = JobChargeStatus.REFUNDED
    charge.refund_transaction_id = refund_id
    charge.refunded_at = refunded_at
    return charge


def redeem_credits(db: Session, *, user_id: str, code_text: str) -> tuple[int, int]:
    code = db.scalar(
        select(RedemptionCode)
        .where(RedemptionCode.code == code_text)
        .with_for_update()
    )
    if not code:
        raise LookupError("missing")
    if code.used_by is not None:
        raise ValueError("used")

    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if not user:
        raise RuntimeError("user missing")

    code.used_by = user.id
    code.used_at = utcnow()
    user.credits += code.credits
    db.add(
        CreditTransaction(
            user_id=user.id,
            amount=code.credits,
            balance_after=user.credits,
            reason=f"redeem:{code_text}",
            transaction_type=CreditTransactionType.REDEEM,
            idempotency_key=f"redeem:{code.id}",
            details={"code_id": code.id},
        )
    )
    return code.credits, user.credits


def adjust_user_credits(
    db: Session,
    *,
    user_id: str,
    requested_amount: int,
    reason: str,
) -> tuple[int, int]:
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if not user:
        raise LookupError("missing")

    balance_before = user.credits
    applied_amount = max(requested_amount, -balance_before)
    user.credits += applied_amount
    db.add(
        CreditTransaction(
            user_id=user.id,
            amount=applied_amount,
            balance_after=user.credits,
            reason=reason or "admin:adjust",
            transaction_type=CreditTransactionType.ADMIN_ADJUST,
            idempotency_key=f"admin-adjust:{uuid4()}",
            details={
                "requested_amount": requested_amount,
                "applied_amount": applied_amount,
                "balance_before": balance_before,
            },
        )
    )
    return applied_amount, user.credits


def reconcile_job_billing(db: Session, *, now: datetime | None = None) -> dict[str, int]:
    reconciled_at = now or utcnow()
    counts = {"settled": 0, "refunded": 0}
    charges = db.scalars(
        select(JobCharge).where(JobCharge.status == JobChargeStatus.RESERVED).with_for_update(skip_locked=True)
    ).all()
    if not charges:
        return counts

    jobs = {
        job.id: job
        for job in db.scalars(select(GenerationJob).where(GenerationJob.id.in_([charge.job_id for charge in charges]))).all()
    }
    for charge in charges:
        job = jobs.get(charge.job_id)
        if not job:
            continue
        if job.status == JobStatus.SUCCEEDED:
            settle_job_charge(db, job_id=job.id, now=reconciled_at)
            counts["settled"] += 1
        elif job.status == JobStatus.FAILED:
            refund_job_charge(db, job_id=job.id, reason=job.error_message or "任务失败", now=reconciled_at)
            counts["refunded"] += 1
    return counts


def reconcile_user_balances(db: Session) -> int:
    users = db.scalars(select(User).with_for_update(skip_locked=True)).all()
    if not users:
        return 0

    user_ids = [user.id for user in users]
    ledger_totals = dict(
        db.execute(
            select(CreditTransaction.user_id, func.coalesce(func.sum(CreditTransaction.amount), 0))
            .where(CreditTransaction.user_id.in_(user_ids))
            .group_by(CreditTransaction.user_id)
        ).all()
    )
    changed = 0
    for user in users:
        expected = int(ledger_totals.get(user.id, 0))
        if expected < 0:
            raise LedgerIntegrityError(
                f"credit ledger is negative for user {user.id[:8]}"
            )
        if user.credits != expected:
            previous = user.credits
            user.credits = expected
            db.add(
                CreditTransaction(
                    user_id=user.id,
                    amount=0,
                    balance_after=expected,
                    reason="reconciliation:balance-repair",
                    transaction_type=CreditTransactionType.RECONCILIATION,
                    idempotency_key=f"reconciliation:{uuid4()}",
                    details={
                        "cached_balance_before": previous,
                        "ledger_balance": expected,
                    },
                )
            )
            changed += 1
    return changed
