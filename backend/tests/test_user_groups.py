from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import admin_routes, auth_routes, user_group_routes, user_routes
from app.core.auth import hash_password
from app.core.config import Settings
from app.db.base import Base
from app.models.user import User
from app.models.user_group import STANDARD_GROUP_CODE, UserGroup
from app.schemas.auth import AdminCreateUserRequest, AdminUpdateUserRequest, RegisterRequest
from app.schemas.user_group import CreateUserGroupRequest, UpdateUserGroupRequest
from app.services.email_codes import store_email_code
from app.schemas.auth import EmailCodePurpose


def make_db():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def group(code: str, *, default: bool = False, enabled: bool = True) -> UserGroup:
    return UserGroup(
        code=code,
        name=code.upper(),
        is_default=default,
        is_enabled=enabled,
        billing_multiplier_bps=10_000,
        generated_retention_hours=24,
        reference_retention_hours=24,
        max_reference_images=3,
    )


def test_user_group_crud_default_protection_and_member_conflict():
    db = make_db()
    standard = group(STANDARD_GROUP_CODE, default=True)
    db.add(standard)
    db.commit()

    created = user_group_routes.create_user_group(
        CreateUserGroupRequest(code="vip", name="VIP", billing_multiplier_bps=5_000, is_default=True), db, {"role": "admin"}
    )
    assert created.is_default is True
    assert db.get(UserGroup, STANDARD_GROUP_CODE).is_default is False

    with pytest.raises(HTTPException, match="默认用户组不能停用"):
        user_group_routes.update_user_group("vip", UpdateUserGroupRequest(is_enabled=False), db, {"role": "admin"})
    with pytest.raises(HTTPException, match="默认用户组不能删除"):
        user_group_routes.delete_user_group("vip", db, {"role": "admin"})
    with pytest.raises(HTTPException, match="standard"):
        user_group_routes.delete_user_group(STANDARD_GROUP_CODE, db, {"role": "admin"})

    user_group_routes.update_user_group(
        STANDARD_GROUP_CODE, UpdateUserGroupRequest(is_default=True), db, {"role": "admin"}
    )

    member = User(username="vip-member", password_hash=hash_password("password"), group_code="vip")
    db.add(member)
    db.commit()
    with pytest.raises(HTTPException, match="仍有成员"):
        user_group_routes.delete_user_group("vip", db, {"role": "admin"})
    db.delete(member)
    db.commit()
    user_group_routes.delete_user_group("vip", db, {"role": "admin"})
    assert db.get(UserGroup, "vip") is None


def test_admin_user_assignment_validates_enabled_group_and_returns_policy():
    db = make_db()
    db.add_all([group(STANDARD_GROUP_CODE, default=True), group("disabled", enabled=False), group("vip")])
    db.commit()

    with pytest.raises(HTTPException, match="不存在或已停用"):
        admin_routes.admin_create_user(
            AdminCreateUserRequest(username="bad", password="password", group_code="disabled"), db, {"role": "admin"}
        )
    response = admin_routes.admin_create_user(
        AdminCreateUserRequest(username="good", password="password", group_code="vip"), db, {"role": "admin"}
    )
    assert response.group and response.group.code == "vip"
    user = db.get(User, response.id)
    admin_routes.admin_update_user(
        user.id, AdminUpdateUserRequest(group_code=STANDARD_GROUP_CODE), db, {"role": "admin"}
    )
    assert user.group_code == STANDARD_GROUP_CODE

    user.group_code = "disabled"
    db.commit()
    updated = admin_routes.admin_update_user(
        user.id,
        AdminUpdateUserRequest(group_code="disabled", display_name="Still disabled"),
        db,
        {"role": "admin"},
    )
    assert updated.group and updated.group.code == "disabled"
    assert updated.display_name == "Still disabled"


def test_registration_uses_current_default_and_standard_fallback():
    db = make_db()
    db.add_all([group(STANDARD_GROUP_CODE), group("vip", default=True)])
    db.commit()
    redis = _FakeRedis()
    settings = Settings(jwt_secret_key="x" * 32, registration_enabled=True)
    store_email_code(redis, settings, email="new@example.com", purpose=EmailCodePurpose.REGISTER, code="123456")
    auth_routes.register(
        RegisterRequest(username="newuser", email="new@example.com", email_code="123456", password="password"),
        db, redis, settings,
    )
    assert db.query(User).filter_by(username="newuser").one().group_code == "vip"

    fallback_db = make_db()
    fallback_redis = _FakeRedis()
    store_email_code(fallback_redis, settings, email="fallback@example.com", purpose=EmailCodePurpose.REGISTER, code="123456")
    auth_routes.register(
        RegisterRequest(username="fallback", email="fallback@example.com", email_code="123456", password="password"),
        fallback_db, fallback_redis, settings,
    )
    fallback_user = fallback_db.query(User).filter_by(username="fallback").one()
    assert fallback_user.group_code == STANDARD_GROUP_CODE
    assert user_routes._user_response(fallback_user, fallback_db).group.code == STANDARD_GROUP_CODE


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def setex(self, key: str, _ttl: int, value: str) -> None:
        self.data[key] = value

    def get(self, key: str):
        return self.data.get(key)

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.data.pop(key, None)
