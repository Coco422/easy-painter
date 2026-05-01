from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import require_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import UpdateUserRequest, UserResponse

user_router = APIRouter()


@user_router.get("/users/me", response_model=UserResponse)
def get_me(current_user: User = Depends(require_current_user)) -> UserResponse:
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        display_name=current_user.display_name,
        is_public=current_user.is_public,
        created_at=current_user.created_at,
    )


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
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        display_name=current_user.display_name,
        is_public=current_user.is_public,
        created_at=current_user.created_at,
    )
