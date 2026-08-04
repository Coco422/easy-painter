from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user_optional, require_admin
from app.db.session import get_db
from app.models.announcement import Announcement
from app.models.user import User
from app.schemas.announcement import (
    AnnouncementAudience,
    AnnouncementCreateRequest,
    AnnouncementResponse,
    AnnouncementUpdateRequest,
)


announcement_router = APIRouter()


@announcement_router.get("/announcements", response_model=list[AnnouncementResponse])
def list_active_announcements(
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
) -> list[Announcement]:
    audiences = [AnnouncementAudience.ALL.value]
    if current_user:
        audiences.append(AnnouncementAudience.AUTHENTICATED.value)
        if not current_user.email:
            audiences.append(AnnouncementAudience.UNBOUND_EMAIL.value)

    return list(db.scalars(
        select(Announcement)
        .where(Announcement.enabled.is_(True))
        .where(Announcement.audience.in_(audiences))
        .order_by(desc(Announcement.created_at))
        .limit(20)
    ).all())


@announcement_router.get("/admin/announcements", response_model=list[AnnouncementResponse])
def admin_list_announcements(
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> list[Announcement]:
    return list(db.scalars(
        select(Announcement).order_by(desc(Announcement.created_at)).limit(500)
    ).all())


@announcement_router.post(
    "/admin/announcements",
    response_model=AnnouncementResponse,
    status_code=status.HTTP_201_CREATED,
)
def admin_create_announcement(
    body: AnnouncementCreateRequest,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> Announcement:
    announcement = Announcement(
        title=body.title,
        content=body.content,
        level=body.level.value,
        audience=body.audience.value,
        enabled=body.enabled,
    )
    db.add(announcement)
    db.commit()
    db.refresh(announcement)
    return announcement


@announcement_router.put("/admin/announcements/{announcement_id}", response_model=AnnouncementResponse)
def admin_update_announcement(
    announcement_id: str,
    body: AnnouncementUpdateRequest,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> Announcement:
    announcement = db.get(Announcement, announcement_id)
    if not announcement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="通知不存在。")

    if body.title is not None:
        announcement.title = body.title
    if body.content is not None:
        announcement.content = body.content
    if body.level is not None:
        announcement.level = body.level.value
    if body.audience is not None:
        announcement.audience = body.audience.value
    if body.enabled is not None:
        announcement.enabled = body.enabled

    db.commit()
    db.refresh(announcement)
    return announcement


@announcement_router.delete("/admin/announcements/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_announcement(
    announcement_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> None:
    announcement = db.get(Announcement, announcement_id)
    if not announcement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="通知不存在。")
    db.delete(announcement)
    db.commit()
