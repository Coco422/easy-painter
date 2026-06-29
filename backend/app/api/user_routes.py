from __future__ import annotations

import logging
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.auth import hash_password, require_current_user, verify_password
from app.db.session import get_db
from app.models.credit_transaction import CreditTransaction
from app.models.redemption_code import RedemptionCode
from app.models.user import User
from app.schemas.auth import ChangePasswordRequest, UpdateUserRequest, UserResponse

logger = logging.getLogger(__name__)
user_router = APIRouter()


def _user_response(u: User) -> UserResponse:
    return UserResponse(
        id=u.id,
        username=u.username,
        display_name=u.display_name,
        is_public=u.is_public,
        credits=u.credits,
        created_at=u.created_at,
    )


@user_router.get("/users/me", response_model=UserResponse)
def get_me(current_user: User = Depends(require_current_user)) -> UserResponse:
    return _user_response(current_user)


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
    return _user_response(current_user)


@user_router.put("/users/me/password", status_code=204)
def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> None:
    if not verify_password(body.old_password, current_user.password_hash):
        raise HTTPException(status_code=403, detail="原密码不正确。")
    current_user.password_hash = hash_password(body.new_password)
    db.commit()


# ---- Billing endpoints ----


class RedeemRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class RedeemResponse(BaseModel):
    credits: int
    added: int


class CreditTransactionItem(BaseModel):
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
    code = db.scalar(
        select(RedemptionCode).where(RedemptionCode.code == code_str)
    )
    if not code:
        raise HTTPException(status_code=404, detail="兑换码不存在。")
    if code.used_by is not None:
        raise HTTPException(status_code=409, detail="该兑换码已被使用。")

    added = code.credits
    code.used_by = current_user.id
    code.used_at = datetime.utcnow()
    current_user.credits = (current_user.credits or 0) + added

    txn = CreditTransaction(
        user_id=current_user.id,
        amount=added,
        balance_after=current_user.credits,
        reason=f"redeem:{code_str}",
    )
    db.add(txn)
    db.commit()
    db.refresh(current_user)
    return RedeemResponse(credits=current_user.credits, added=added)


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
    return CreditHistoryResponse(
        items=[
            CreditTransactionItem(
                amount=t.amount,
                balance_after=t.balance_after,
                reason=t.reason,
                created_at=t.created_at,
            )
            for t in items
        ],
        total=total,
    )
