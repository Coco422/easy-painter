from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import announcement_routes
from app.db.base import Base
from app.models.announcement import Announcement
from app.models.user import User
from app.schemas.announcement import (
    AnnouncementAudience,
    AnnouncementCreateRequest,
    AnnouncementLevel,
    AnnouncementUpdateRequest,
)


def make_session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def test_active_announcements_are_filtered_by_audience_and_email_state():
    db = make_session_factory()()
    db.add_all([
        Announcement(title="all", content="all", audience="all", enabled=True),
        Announcement(title="auth", content="auth", audience="authenticated", enabled=True),
        Announcement(title="unbound", content="unbound", audience="unbound_email", enabled=True),
        Announcement(title="disabled", content="disabled", audience="all", enabled=False),
    ])
    bound_user = User(
        username="bound",
        email="bound@example.com",
        password_hash="hash",
    )
    unbound_user = User(username="unbound", password_hash="hash")
    db.add_all([bound_user, unbound_user])
    db.commit()

    guest_titles = {item.title for item in announcement_routes.list_active_announcements(db=db, current_user=None)}
    bound_titles = {item.title for item in announcement_routes.list_active_announcements(db=db, current_user=bound_user)}
    unbound_titles = {item.title for item in announcement_routes.list_active_announcements(db=db, current_user=unbound_user)}

    assert guest_titles == {"all"}
    assert bound_titles == {"all", "auth"}
    assert unbound_titles == {"all", "auth", "unbound"}


def test_admin_can_create_update_disable_and_delete_announcement():
    db = make_session_factory()()
    admin_claims = {"role": "admin"}
    created = announcement_routes.admin_create_announcement(
        body=AnnouncementCreateRequest(
            title="邮箱绑定提醒",
            content="未绑定邮箱的使用者请尽快绑定邮箱。",
            level=AnnouncementLevel.WARNING,
            audience=AnnouncementAudience.UNBOUND_EMAIL,
            enabled=True,
        ),
        db=db,
        _=admin_claims,
    )

    updated = announcement_routes.admin_update_announcement(
        announcement_id=created.id,
        body=AnnouncementUpdateRequest(content="请尽快完成邮箱验证。", enabled=False),
        db=db,
        _=admin_claims,
    )
    assert updated.content == "请尽快完成邮箱验证。"
    assert updated.enabled is False
    assert [item.id for item in announcement_routes.admin_list_announcements(db=db, _=admin_claims)] == [created.id]

    announcement_routes.admin_delete_announcement(
        announcement_id=created.id,
        db=db,
        _=admin_claims,
    )
    assert announcement_routes.admin_list_announcements(db=db, _=admin_claims) == []
