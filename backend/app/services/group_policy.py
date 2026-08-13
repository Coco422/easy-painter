from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.user_group import STANDARD_GROUP_CODE, UserGroup


@dataclass(frozen=True, slots=True)
class UserGroupPolicy:
    code: str
    name: str
    billing_multiplier_bps: int
    generated_retention_hours: int
    reference_retention_hours: int
    max_reference_images: int


STANDARD_POLICY = UserGroupPolicy(
    code=STANDARD_GROUP_CODE,
    name="普通用户",
    billing_multiplier_bps=10_000,
    generated_retention_hours=24,
    reference_retention_hours=24,
    max_reference_images=3,
)


def policy_from_group(group: UserGroup) -> UserGroupPolicy:
    return UserGroupPolicy(
        code=group.code,
        name=group.name,
        billing_multiplier_bps=group.billing_multiplier_bps,
        generated_retention_hours=group.generated_retention_hours,
        reference_retention_hours=group.reference_retention_hours,
        max_reference_images=group.max_reference_images,
    )


def calculate_effective_credit_cost(base_credit_cost: int, multiplier_bps: int) -> int:
    base = max(0, int(base_credit_cost))
    multiplier = max(0, int(multiplier_bps))
    if base == 0 or multiplier == 0:
        return 0
    return max(1, (base * multiplier + 9_999) // 10_000)


def get_default_group(db: Session, *, for_update: bool = False) -> UserGroup | None:
    stmt = select(UserGroup).where(UserGroup.is_default.is_(True), UserGroup.is_enabled.is_(True))
    if for_update:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def resolve_user_policy(
    db: Session,
    user: User,
    *,
    lock_user: bool = False,
) -> tuple[User, UserGroupPolicy]:
    resolved_user = user
    if lock_user:
        resolved_user = db.scalar(select(User).where(User.id == user.id).with_for_update()) or user
    group = db.get(UserGroup, resolved_user.group_code)
    if group:
        return resolved_user, policy_from_group(group)
    if resolved_user.group_code == STANDARD_GROUP_CODE:
        return resolved_user, STANDARD_POLICY
    raise RuntimeError(f"user group is missing: {resolved_user.group_code}")
