from __future__ import annotations

import logging
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from redis import Redis
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import require_current_user
from app.core.config import Settings, get_settings
from app.core.network import extract_client_ip, rate_limit_identity
from app.db.session import get_db
from app.models.credit_transaction import CreditTransaction
from app.models.job_charge import JobCharge
from app.models.user import User
from app.schemas.auth import (
    BindEmailCodeRequest,
    BindEmailRequest,
    EmailCodePurpose,
    EmailCodeResponse,
    UpdateUserRequest,
    UserResponse,
)
from app.services.email_codes import (
    EmailCodeRateLimitExceeded,
    consume_email_code,
    enforce_email_code_send_limits,
    normalize_email,
    release_email_code_cooldown,
    store_email_code,
    verify_email_code,
)
from app.services.mailer import EmailDeliveryError, SmtpEmailSender
from app.services.billing import redeem_credits
from app.services.redis_client import get_redis
from app.services.group_policy import STANDARD_POLICY, resolve_user_policy

logger = logging.getLogger(__name__)
user_router = APIRouter()


def _user_response(u: User, db: Session | None = None) -> UserResponse:
    policy = STANDARD_POLICY
    if db is not None:
        _, policy = resolve_user_policy(db, u)
    return UserResponse(
        id=u.id,
        username=u.username,
        email=u.email,
        display_name=u.display_name,
        is_public=u.is_public,
        credits=u.credits,
        group={
            "code": policy.code,
            "name": policy.name,
            "billing_multiplier_bps": policy.billing_multiplier_bps,
            "generated_retention_hours": policy.generated_retention_hours,
            "reference_retention_hours": policy.reference_retention_hours,
            "max_reference_images": policy.max_reference_images,
        },
        created_at=u.created_at,
    )


@user_router.get("/users/me", response_model=UserResponse)
def get_me(
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    return _user_response(current_user, db)


@user_router.put("/users/me", response_model=UserResponse)
def update_me(
    body: UpdateUserRequest,
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    if body.display_name is not None:
        current_user.display_name = body.display_name
    if body.is_public is not None:
        current_user.is_public = body.is_public
    db.commit()
    db.refresh(current_user)
    return _user_response(current_user, db)


@user_router.post(
    "/users/me/email/code",
    response_model=EmailCodeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_email_binding_code(
    body: BindEmailCodeRequest,
    request: Request,
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> EmailCodeResponse:
    if current_user.email:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前账号已绑定邮箱。")
    if not settings.smtp_configured:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="邮件服务尚未配置。")

    email = normalize_email(str(body.email))
    try:
        enforce_email_code_send_limits(
            redis_client,
            settings,
            email=email,
            ip_identity=rate_limit_identity(extract_client_ip(request)),
            user_id=current_user.id,
        )
    except EmailCodeRateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="验证码发送过于频繁，请稍后再试。",
            headers={"Retry-After": str(exc.retry_after)},
        ) from None

    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已被其他账号使用。")

    code = f"{secrets.randbelow(1_000_000):06d}"
    store_email_code(
        redis_client,
        settings,
        email=email,
        purpose=EmailCodePurpose.BIND_EMAIL,
        code=code,
        subject=current_user.id,
    )
    try:
        SmtpEmailSender(settings).send_verification_code(
            recipient=email,
            code=code,
            purpose=EmailCodePurpose.BIND_EMAIL,
        )
    except EmailDeliveryError:
        consume_email_code(
            redis_client,
            email=email,
            purpose=EmailCodePurpose.BIND_EMAIL,
            subject=current_user.id,
        )
        release_email_code_cooldown(redis_client, email=email)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="验证码邮件发送失败，请稍后再试。",
        ) from None

    return EmailCodeResponse(
        message="验证码已发送，请检查邮箱。",
        expires_in=settings.email_code_expire_seconds,
        retry_after=settings.email_code_cooldown_seconds,
    )


@user_router.put("/users/me/email", response_model=UserResponse)
def bind_email(
    body: BindEmailRequest,
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    if current_user.email:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前账号已绑定邮箱。")

    email = normalize_email(str(body.email))
    if db.scalar(select(User).where(func.lower(User.email) == email, User.id != current_user.id)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已被其他账号使用。")
    if not verify_email_code(
        redis_client,
        settings,
        email=email,
        purpose=EmailCodePurpose.BIND_EMAIL,
        code=body.email_code,
        subject=current_user.id,
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码无效或已过期。")

    current_user.email = email
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        consume_email_code(
            redis_client,
            email=email,
            purpose=EmailCodePurpose.BIND_EMAIL,
            subject=current_user.id,
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已被其他账号使用。") from None

    consume_email_code(
        redis_client,
        email=email,
        purpose=EmailCodePurpose.BIND_EMAIL,
        subject=current_user.id,
    )
    db.refresh(current_user)
    return _user_response(current_user)


# ---- Billing endpoints ----


class RedeemRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class RedeemResponse(BaseModel):
    credits: int
    added: int


class CreditTransactionItem(BaseModel):
    id: str
    transaction_type: str
    job_id: str | None = None
    model_label: str | None = None
    billing_status: str | None = None
    related_transaction_id: str | None = None
    amount: int
    balance_after: int
    reason: str
    created_at: datetime


class CreditHistoryResponse(BaseModel):
    items: list[CreditTransactionItem]
    total: int


@user_router.post("/users/me/redeem", response_model=RedeemResponse)
def redeem_code(
    body: RedeemRequest,
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> RedeemResponse:
    code_str = body.code.strip().upper()
    try:
        added, balance = redeem_credits(db, user_id=current_user.id, code_text=code_str)
    except LookupError:
        raise HTTPException(status_code=404, detail="兑换码不存在。")
    except ValueError:
        raise HTTPException(status_code=409, detail="该兑换码已被使用。")
    db.commit()
    return RedeemResponse(credits=balance, added=added)


@user_router.get("/users/me/credits", response_model=CreditHistoryResponse)
def get_credit_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> CreditHistoryResponse:
    offset = (page - 1) * page_size
    total = db.scalar(
        select(func.count())
        .select_from(CreditTransaction)
        .where(CreditTransaction.user_id == current_user.id)
    ) or 0
    items = db.scalars(
        select(CreditTransaction)
        .where(CreditTransaction.user_id == current_user.id)
        .order_by(desc(CreditTransaction.created_at))
        .offset(offset)
        .limit(page_size)
    ).all()
    job_ids = [item.job_id for item in items if item.job_id]
    charge_map = {
        charge.job_id: charge
        for charge in db.scalars(select(JobCharge).where(JobCharge.job_id.in_(job_ids))).all()
    } if job_ids else {}
    return CreditHistoryResponse(
        items=[
            CreditTransactionItem(
                id=t.id,
                transaction_type=t.transaction_type.value,
                job_id=t.job_id,
                model_label=(charge_map[t.job_id].model_label if t.job_id in charge_map else (t.details or {}).get("model_label")),
                billing_status=charge_map[t.job_id].status.value if t.job_id in charge_map else None,
                related_transaction_id=t.related_transaction_id,
                amount=t.amount,
                balance_after=t.balance_after,
                reason=t.reason,
                created_at=t.created_at,
            )
            for t in items
        ],
        total=total,
    )
