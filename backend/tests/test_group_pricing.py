from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.api import routes
from app.core.config import Settings
from app.db.base import Base
from app.models.credit_transaction import CreditTransaction, CreditTransactionType
from app.models.generation_job import GenerationJob
from app.models.job_charge import JobCharge, JobChargeStatus
from app.models.user import User
from app.models.user_group import UserGroup
from app.services.group_policy import calculate_effective_credit_cost
from app.services.billing import refund_job_charge
from app.services.model_pricing import base_credit_cost_for_size, size_pricing_tier


def make_session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def make_request(size: str = "1024x1024") -> Request:
    body = f'{{"prompt":"hello","model":"model-1","size":"{size}"}}'.encode()

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


class AllowRateLimiter:
    def __init__(self, **_: object) -> None:
        pass

    def check(self, _: str):
        return type("Result", (), {"allowed": True, "remaining": 10})()


@pytest.mark.parametrize(
    ("base", "bps", "expected"),
    [(2, 10_000, 2), (2, 5_000, 1), (3, 3_334, 2), (1, 1, 1), (9, 0, 0)],
)
def test_effective_credit_cost_uses_integer_ceiling(base: int, bps: int, expected: int):
    assert calculate_effective_credit_cost(base, bps) == expected


@pytest.mark.parametrize(
    ("size", "tier", "cost"),
    [
        ("auto", "1k", 5),
        ("1024x1792", "1k", 5),
        ("2048x1152", "2k", 8),
        ("3840x2160", "4k", 12),
    ],
)
def test_resolution_maps_to_configured_price_tier(size: str, tier: str, cost: int):
    model = {"credit_cost": 4, "credit_cost_by_size": {"1k": 5, "2k": 8, "4k": 12}}
    assert size_pricing_tier(size) == tier
    assert base_credit_cost_for_size(model, size) == cost


def test_public_model_policy_exposes_size_prices():
    result = routes._models_for_policy(
        [{"id": "model-1", "credit_cost": 5, "credit_cost_by_size": {"1k": 5, "2k": 8, "4k": 12}}],
        type("Policy", (), {"billing_multiplier_bps": 10_000})(),
    )
    assert result[0]["credit_cost"] == 5
    assert result[0]["base_credit_cost_by_size"] == {"1k": 5, "2k": 8, "4k": 12}
    assert result[0]["credit_cost_by_size"] == {"1k": 5, "2k": 8, "4k": 12}


@pytest.mark.anyio
@pytest.mark.parametrize(("group_code", "bps", "expected"), [("vip", 5_000, 2), ("free", 0, 0)])
async def test_create_job_snapshots_group_policy_and_effective_price(
    monkeypatch,
    group_code: str,
    bps: int,
    expected: int,
):
    db = make_session()
    db.add(
        UserGroup(
            code=group_code,
            name=group_code.upper(),
            billing_multiplier_bps=bps,
            generated_retention_hours=720,
            reference_retention_hours=720,
            max_reference_images=50,
        )
    )
    user = User(id=f"user-{group_code}", username=group_code, password_hash="hash", group_code=group_code, credits=10)
    db.add(user)
    db.add(
        CreditTransaction(
            user_id=user.id,
            amount=10,
            balance_after=10,
            reason="test:opening",
            transaction_type=CreditTransactionType.OPENING_BALANCE,
            idempotency_key=f"opening:{user.id}",
        )
    )
    db.commit()
    monkeypatch.setattr(routes, "GenerationRateLimiter", AllowRateLimiter)
    monkeypatch.setattr(
        routes,
        "load_models_from_db",
        lambda _: [{
            "id": "model-1",
            "label": "Model One",
            "enabled": True,
            "supports_reference_image": True,
            "supported_sizes": [],
            "credit_cost": 3,
        }],
    )

    response = await routes.create_job(
        make_request(),
        idempotency_key=f"pricing-{group_code}",
        db=db,
        redis_client=object(),
        settings=Settings(),
        current_user=user,
    )

    job = db.get(GenerationJob, response.job_id)
    charge = db.scalar(select(JobCharge).where(JobCharge.job_id == job.id))
    reserve = db.scalar(
        select(CreditTransaction).where(
            CreditTransaction.job_id == job.id,
            CreditTransaction.transaction_type == CreditTransactionType.JOB_RESERVE,
        )
    )
    assert response.credit_cost == expected
    assert job.base_credit_cost_snapshot == 3
    assert job.billing_multiplier_bps_snapshot == bps
    assert job.group_code_snapshot == group_code
    assert job.credit_cost_snapshot == expected
    assert charge.amount == expected
    assert charge.group_code_snapshot == group_code
    assert reserve.amount == -expected
    assert reserve.details["base_credit_cost"] == 3
    assert reserve.details["billing_multiplier_bps"] == bps
    assert response.balance_after == 10 - expected
    if expected == 0:
        refund_job_charge(db, job_id=job.id, reason="free job failed")
        db.commit()
        assert charge.status == JobChargeStatus.REFUNDED
        refund = db.scalar(
            select(CreditTransaction).where(
                CreditTransaction.job_id == job.id,
                CreditTransaction.transaction_type == CreditTransactionType.JOB_REFUND,
            )
        )
        assert refund.amount == 0
        assert db.get(User, user.id).credits == 10
    db.close()


@pytest.mark.anyio
async def test_create_job_charges_price_for_requested_size(monkeypatch):
    db = make_session()
    db.add(UserGroup(code="standard", name="普通用户", billing_multiplier_bps=10_000,
                     generated_retention_hours=48, reference_retention_hours=48, max_reference_images=3,
                     is_default=True))
    user = User(id="user-size", username="size", password_hash="hash", group_code="standard", credits=20)
    db.add(user)
    db.add(CreditTransaction(user_id=user.id, amount=20, balance_after=20, reason="test:opening",
                             transaction_type=CreditTransactionType.OPENING_BALANCE, idempotency_key="opening:size"))
    db.commit()
    monkeypatch.setattr(routes, "GenerationRateLimiter", AllowRateLimiter)
    monkeypatch.setattr(routes, "load_models_from_db", lambda _: [{
        "id": "model-1", "label": "Model One", "enabled": True, "supports_reference_image": True,
        "supported_sizes": [], "credit_cost": 5, "credit_cost_by_size": {"1k": 5, "2k": 8, "4k": 12},
    }])
    response = await routes.create_job(make_request("2048x2048"), idempotency_key="pricing-size", db=db,
                                       redis_client=object(), settings=Settings(), current_user=user)
    job = db.get(GenerationJob, response.job_id)
    assert response.credit_cost == 8
    assert job.base_credit_cost_snapshot == 8
    assert job.credit_cost_snapshot == 8
    assert db.get(User, user.id).credits == 12
    db.close()
