from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.api import routes
from app.core.config import Settings
from app.db.base import Base
from app.models.credit_transaction import CreditTransaction, CreditTransactionType
from app.models.generation_job import GenerationJob, JobStatus
from app.models.job_charge import JobCharge, JobChargeStatus
from app.models.outbox_event import OutboxEvent, OutboxEventStatus
from app.models.redemption_code import RedemptionCode
from app.models.user import User
from app.services import dispatcher
from app.services.billing import (
    LedgerIntegrityError,
    adjust_user_credits,
    reconcile_user_balances,
    redeem_credits,
    reserve_job_credits,
)
from app.services.job_lifecycle import mark_generation_failed


def make_session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def add_opening_balance(db, user: User, amount: int) -> None:
    user.credits = amount
    db.add(
        CreditTransaction(
            user_id=user.id,
            amount=amount,
            balance_after=amount,
            reason="test:opening",
            transaction_type=CreditTransactionType.OPENING_BALANCE,
            idempotency_key=f"test-opening:{user.id}",
        )
    )


def make_request(prompt: str) -> Request:
    body = (
        '{"prompt":"%s","model":"model-1","size":"1024x1024"}' % prompt
    ).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/jobs",
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
    )


class CountingRateLimiter:
    calls = 0

    def __init__(self, **kwargs):
        pass

    def check(self, identity):
        type(self).calls += 1
        return type("Result", (), {"allowed": True, "remaining": 11})()


@pytest.mark.anyio
async def test_create_job_idempotent_replay_does_not_charge_or_rate_limit_twice(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    user = User(id="user-1", username="ray", password_hash="hash")
    add_opening_balance(db, user, 20)
    db.add(user)
    db.commit()
    CountingRateLimiter.calls = 0
    monkeypatch.setattr(routes, "GenerationRateLimiter", CountingRateLimiter)
    monkeypatch.setattr(
        routes,
        "load_models_from_db",
        lambda db: [
            {
                "id": "model-1",
                "label": "模型一",
                "enabled": True,
                "supports_reference_image": True,
                "supported_sizes": [],
                "credit_cost": 3,
            }
        ],
    )

    first = await routes.create_job(
        make_request("画一朵花"),
        idempotency_key="intent-1",
        db=db,
        redis_client=object(),
        settings=Settings(),
        current_user=user,
    )
    monkeypatch.setattr(routes, "load_models_from_db", lambda db: [])
    replay = await routes.create_job(
        make_request("画一朵花"),
        idempotency_key="intent-1",
        db=db,
        redis_client=object(),
        settings=Settings(prompt_max_length=2),
        current_user=user,
    )

    assert replay.job_id == first.job_id
    assert replay.balance_after == 17
    assert CountingRateLimiter.calls == 1
    assert db.scalar(select(func.count()).select_from(JobCharge)) == 1
    assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 1
    assert db.scalar(select(User.credits).where(User.id == user.id)) == 17

    with pytest.raises(HTTPException) as exc_info:
        await routes.create_job(
            make_request("改成一棵树"),
            idempotency_key="intent-1",
            db=db,
            redis_client=object(),
            settings=Settings(prompt_max_length=2),
            current_user=user,
        )
    assert exc_info.value.status_code == 409
    db.close()


def test_failed_job_refund_is_full_and_idempotent():
    session_factory = make_session_factory()
    db = session_factory()
    user = User(id="user-1", username="ray", password_hash="hash")
    add_opening_balance(db, user, 10)
    job = GenerationJob(id="job-1", prompt="test", model="model-1", user_id=user.id)
    db.add_all([user, job])
    db.flush()
    reserve_job_credits(
        db,
        job=job,
        user_id=user.id,
        amount=4,
        model_label="模型一",
        provider_name="渠道一",
    )
    db.commit()

    assert mark_generation_failed(db, job_id=job.id, message="上游失败") is True
    assert mark_generation_failed(db, job_id=job.id, message="重复回调") is False

    charge = db.scalar(select(JobCharge).where(JobCharge.job_id == job.id))
    refunds = db.scalars(
        select(CreditTransaction).where(
            CreditTransaction.job_id == job.id,
            CreditTransaction.transaction_type == CreditTransactionType.JOB_REFUND,
        )
    ).all()
    assert charge.status == JobChargeStatus.REFUNDED
    assert charge.refunded_at is not None
    assert len(refunds) == 1
    assert refunds[0].amount == 4
    assert db.scalar(select(User.credits).where(User.id == user.id)) == 10
    db.close()


def test_admin_negative_adjustment_records_actual_applied_amount():
    session_factory = make_session_factory()
    db = session_factory()
    user = User(id="user-1", username="ray", password_hash="hash")
    add_opening_balance(db, user, 2)
    db.add(user)
    db.commit()

    applied, balance = adjust_user_credits(
        db,
        user_id=user.id,
        requested_amount=-5,
        reason="admin:test",
    )
    applied_again, balance_again = adjust_user_credits(
        db,
        user_id=user.id,
        requested_amount=-1,
        reason="admin:test-zero",
    )
    db.commit()

    transactions = db.scalars(
        select(CreditTransaction)
        .where(CreditTransaction.transaction_type == CreditTransactionType.ADMIN_ADJUST)
        .order_by(CreditTransaction.created_at)
    ).all()
    assert (applied, balance) == (-2, 0)
    assert (applied_again, balance_again) == (0, 0)
    assert [item.amount for item in transactions] == [-2, 0]
    assert transactions[0].details["requested_amount"] == -5
    assert transactions[0].details["applied_amount"] == -2
    db.close()


def test_redemption_code_can_only_be_redeemed_once():
    session_factory = make_session_factory()
    db = session_factory()
    creator = User(id="admin", username="admin", password_hash="hash")
    first_user = User(id="user-1", username="first", password_hash="hash")
    second_user = User(id="user-2", username="second", password_hash="hash")
    code = RedemptionCode(id="code-1", code="EP-ONCE", credits=8, created_by=creator.id)
    db.add_all([creator, first_user, second_user, code])
    db.commit()

    assert redeem_credits(db, user_id=first_user.id, code_text=code.code) == (8, 8)
    db.commit()
    with pytest.raises(ValueError):
        redeem_credits(db, user_id=second_user.id, code_text=code.code)
    db.rollback()
    assert db.scalar(select(User.credits).where(User.id == second_user.id)) == 0
    db.close()


def test_reconciliation_repairs_cache_and_rejects_negative_ledger():
    session_factory = make_session_factory()
    db = session_factory()
    user = User(id="user-1", username="ray", password_hash="hash", credits=1)
    db.add_all(
        [
            user,
            CreditTransaction(
                user_id=user.id,
                amount=5,
                balance_after=5,
                reason="test:opening",
                transaction_type=CreditTransactionType.OPENING_BALANCE,
            ),
        ]
    )
    db.commit()

    assert reconcile_user_balances(db) == 1
    db.commit()
    assert db.scalar(select(User.credits).where(User.id == user.id)) == 5
    repair = db.scalar(
        select(CreditTransaction).where(
            CreditTransaction.transaction_type == CreditTransactionType.RECONCILIATION
        )
    )
    assert repair.amount == 0
    assert repair.balance_after == 5

    db.add(
        CreditTransaction(
            user_id=user.id,
            amount=-10,
            balance_after=-5,
            reason="test:corruption",
            transaction_type=CreditTransactionType.RECONCILIATION,
        )
    )
    db.commit()
    with pytest.raises(LedgerIntegrityError):
        reconcile_user_balances(db)
    db.rollback()
    db.close()


def test_outbox_dispatch_retries_then_publishes(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    now = datetime(2026, 8, 5, 0, 0, tzinfo=timezone.utc)
    job = GenerationJob(id="job-1", prompt="test", model="model-1", status=JobStatus.QUEUED)
    event = OutboxEvent(
        id="event-1",
        event_type="generation.job.created",
        aggregate_id=job.id,
        payload={"job_id": job.id},
        available_at=now,
        created_at=now,
    )
    db.add_all([job, event])
    db.commit()
    db.close()

    class FakeTask:
        should_fail = True

        @classmethod
        def apply_async(cls, args):
            if cls.should_fail:
                raise RuntimeError("broker down")

    monkeypatch.setattr(dispatcher, "SessionLocal", session_factory)
    monkeypatch.setattr(dispatcher, "generate_image_task", FakeTask)
    monkeypatch.setattr(dispatcher, "settings", Settings(outbox_batch_size=10))

    first = dispatcher.dispatch_pending_events(now=now)
    assert first == {"published": 0, "failed": 1, "discarded": 0}
    db = session_factory()
    saved = db.get(OutboxEvent, event.id)
    assert saved.status == OutboxEventStatus.PENDING
    assert saved.attempts == 1
    retry_at = saved.available_at
    db.close()

    FakeTask.should_fail = False
    second = dispatcher.dispatch_pending_events(now=retry_at + timedelta(seconds=1))
    assert second == {"published": 1, "failed": 0, "discarded": 0}
    db = session_factory()
    assert db.get(OutboxEvent, event.id).status == OutboxEventStatus.PUBLISHED
    db.close()
