from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.db.session import get_db
from app.models.user import User
from app.models.user_group import STANDARD_GROUP_CODE, UserGroup
from app.schemas.user_group import (
    AdminUserGroupResponse,
    CreateUserGroupRequest,
    UpdateUserGroupRequest,
)


user_group_router = APIRouter()


def _response(db: Session, group: UserGroup) -> AdminUserGroupResponse:
    return AdminUserGroupResponse(
        code=group.code,
        name=group.name,
        description=group.description,
        billing_multiplier_bps=group.billing_multiplier_bps,
        generated_retention_hours=group.generated_retention_hours,
        reference_retention_hours=group.reference_retention_hours,
        max_reference_images=group.max_reference_images,
        is_enabled=group.is_enabled,
        is_default=group.is_default,
        user_count=int(db.scalar(select(func.count()).select_from(User).where(User.group_code == group.code)) or 0),
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


def get_assignable_group(db: Session, code: str) -> UserGroup | None:
    """Return an enabled group suitable for a new assignment.

    ``standard`` remains usable in isolated unit-test databases that have not run
    the Flyway seed yet; a production database always contains it after V4.
    """
    group = db.get(UserGroup, code)
    if group is None and code == STANDARD_GROUP_CODE:
        return None
    if group is None or not group.is_enabled:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="用户组不存在或已停用。")
    return group


def default_group_code(db: Session) -> str:
    group = db.scalar(
        select(UserGroup).where(UserGroup.is_default.is_(True), UserGroup.is_enabled.is_(True))
    )
    return group.code if group else STANDARD_GROUP_CODE


@user_group_router.get("/admin/user-groups", response_model=list[AdminUserGroupResponse])
def list_user_groups(
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> list[AdminUserGroupResponse]:
    groups = db.scalars(select(UserGroup).order_by(UserGroup.created_at, UserGroup.code)).all()
    return [_response(db, group) for group in groups]


@user_group_router.post("/admin/user-groups", response_model=AdminUserGroupResponse, status_code=status.HTTP_201_CREATED)
def create_user_group(
    body: CreateUserGroupRequest,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> AdminUserGroupResponse:
    if body.is_default and not body.is_enabled:
        raise HTTPException(status_code=422, detail="默认用户组必须启用。")
    group = UserGroup(**body.model_dump())
    try:
        if group.is_default:
            db.execute(
                update(UserGroup)
                .where(UserGroup.is_default.is_(True))
                .values(is_default=False)
                .execution_options(synchronize_session="fetch")
            )
        db.add(group)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="用户组代码或名称已存在。") from None
    db.refresh(group)
    return _response(db, group)


@user_group_router.put("/admin/user-groups/{code}", response_model=AdminUserGroupResponse)
def update_user_group(
    code: str,
    body: UpdateUserGroupRequest,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> AdminUserGroupResponse:
    group = db.scalar(select(UserGroup).where(UserGroup.code == code).with_for_update())
    if not group:
        raise HTTPException(status_code=404, detail="用户组不存在。")
    if group.is_default and body.is_enabled is False:
        raise HTTPException(status_code=409, detail="默认用户组不能停用。")
    if body.is_default is True and (body.is_enabled is False or (body.is_enabled is None and not group.is_enabled)):
        raise HTTPException(status_code=422, detail="默认用户组必须启用。")

    for field, value in body.model_dump(exclude_unset=True).items():
        if field != "is_default":
            setattr(group, field, value)
    try:
        if body.is_default is True:
            db.execute(
                update(UserGroup)
                .where(UserGroup.is_default.is_(True))
                .values(is_default=False)
                .execution_options(synchronize_session="fetch")
            )
            group.is_default = True
        elif body.is_default is False:
            if group.is_default:
                raise HTTPException(status_code=409, detail="请先指定新的默认用户组。")
            group.is_default = False
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="用户组名称已存在。") from None
    db.refresh(group)
    return _response(db, group)


@user_group_router.delete("/admin/user-groups/{code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user_group(
    code: str,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> None:
    group = db.scalar(select(UserGroup).where(UserGroup.code == code).with_for_update())
    if not group:
        raise HTTPException(status_code=404, detail="用户组不存在。")
    if group.code == STANDARD_GROUP_CODE:
        raise HTTPException(status_code=409, detail="standard 是兜底用户组，不能删除。")
    if group.is_default:
        raise HTTPException(status_code=409, detail="默认用户组不能删除。")
    if db.scalar(select(User.id).where(User.group_code == code).limit(1)):
        raise HTTPException(status_code=409, detail="该用户组仍有成员，不能删除。")
    db.delete(group)
    db.commit()
