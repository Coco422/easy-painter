from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import admin_routes, auth_routes, inspiration_routes, routes, user_routes
from app.core.auth import hash_password, verify_password
from app.core.config import Settings
from app.db.base import Base
from app.models.generation_job import GenerationJob, JobStatus
from app.models.media import MediaState
from app.models.user import User
from app.schemas.auth import (
    AdminUpdateUserRequest,
    BindEmailCodeRequest,
    BindEmailRequest,
    EmailCodePurpose,
    EmailCodeRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
)
from app.services.email_codes import release_email_code_cooldown, store_email_code, verify_email_code
from app.services.mailer import EmailDeliveryError, SmtpEmailSender


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str | int] = {}
        self.expiry: dict[str, int] = {}

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.data[key] = value
        self.expiry[key] = ttl

    def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.data:
            return False
        self.data[key] = value
        if ex is not None:
            self.expiry[key] = ex
        return True

    def get(self, key: str):
        return self.data.get(key)

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.data.pop(key, None)
            self.expiry.pop(key, None)

    def incr(self, key: str) -> int:
        value = int(self.data.get(key, 0)) + 1
        self.data[key] = value
        return value

    def expire(self, key: str, ttl: int) -> None:
        self.expiry[key] = ttl


class DummyRequest:
    headers: dict[str, str] = {}
    client = SimpleNamespace(host="127.0.0.1")


def make_session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def smtp_settings() -> Settings:
    return Settings(
        jwt_secret_key="test-secret-key-that-is-at-least-32-bytes",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_from_email="no-reply@example.com",
        smtp_username="smtp-user",
        smtp_password="smtp-password",
        email_code_expire_seconds=600,
        email_code_rate_limit_count=3,
        email_code_rate_limit_window_seconds=600,
    )


def test_email_code_registration_and_email_login(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    redis_client = FakeRedis()
    settings = smtp_settings()
    sent: dict[str, str] = {}

    class FakeSender:
        def __init__(self, _settings):
            pass

        def send_verification_code(self, *, recipient, code, purpose):
            sent.update(recipient=recipient, code=code, purpose=purpose.value)

    monkeypatch.setattr(auth_routes, "SmtpEmailSender", FakeSender)
    monkeypatch.setattr(auth_routes, "create_access_token", lambda data: f"token:{data['sub']}")

    response = auth_routes.request_email_code(
        body=EmailCodeRequest(email="NewUser@Example.com", purpose=EmailCodePurpose.REGISTER),
        request=DummyRequest(),
        db=db,
        redis_client=redis_client,
        settings=settings,
    )

    assert response.expires_in == 600
    assert sent["recipient"] == "newuser@example.com"
    assert sent["purpose"] == "register"
    assert sent["code"] not in {str(value) for value in redis_client.data.values()}

    token = auth_routes.register(
        body=RegisterRequest(
            username="new_user",
            email="NewUser@Example.com",
            email_code=sent["code"],
            password="new-password",
            display_name="新用户",
        ),
        db=db,
        redis_client=redis_client,
        settings=settings,
    )

    user = db.scalar(select(User).where(User.username == "new_user"))
    assert token.access_token == f"token:{user.id}"
    assert user.email == "newuser@example.com"
    assert user.display_name == "新用户"
    assert all("email-code:register" not in key for key in redis_client.data)

    login_result = auth_routes.login(
        body=LoginRequest(username="NEWUSER@example.com", password="new-password"),
        db=db,
        redis_client=redis_client,
        request=DummyRequest(),
    )
    assert login_result.access_token == f"token:{user.id}"


def test_reset_password_uses_email_code_without_old_password(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    redis_client = FakeRedis()
    settings = smtp_settings()
    user = User(
        username="ray",
        email="ray@example.com",
        password_hash=hash_password("old-password"),
        display_name="Ray",
    )
    db.add(user)
    db.commit()
    store_email_code(
        redis_client,
        settings,
        email=user.email,
        purpose=EmailCodePurpose.RESET_PASSWORD,
        code="123456",
    )

    auth_routes.reset_password(
        body=ResetPasswordRequest(
            email="RAY@example.com",
            email_code="123456",
            new_password="new-password",
        ),
        db=db,
        redis_client=redis_client,
        settings=settings,
    )

    db.refresh(user)
    assert verify_password("new-password", user.password_hash)
    assert not verify_password("old-password", user.password_hash)
    assert all("email-code:reset_password" not in key for key in redis_client.data)


def test_reset_password_rejects_wrong_code():
    session_factory = make_session_factory()
    db = session_factory()
    redis_client = FakeRedis()
    settings = smtp_settings()
    user = User(
        username="ray",
        email="ray@example.com",
        password_hash=hash_password("old-password"),
    )
    db.add(user)
    db.commit()
    store_email_code(
        redis_client,
        settings,
        email=user.email,
        purpose=EmailCodePurpose.RESET_PASSWORD,
        code="123456",
    )

    with pytest.raises(HTTPException) as exc_info:
        auth_routes.reset_password(
            body=ResetPasswordRequest(
                email=user.email,
                email_code="000000",
                new_password="new-password",
            ),
            db=db,
            redis_client=redis_client,
            settings=settings,
        )

    assert exc_info.value.status_code == 400
    db.refresh(user)
    assert verify_password("old-password", user.password_hash)


def test_unknown_reset_email_does_not_send_or_reveal_account(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    redis_client = FakeRedis()

    class FailIfCalled:
        def __init__(self, _settings):
            pass

        def send_verification_code(self, **kwargs):
            raise AssertionError("unknown reset email must not trigger SMTP")

    monkeypatch.setattr(auth_routes, "SmtpEmailSender", FailIfCalled)
    response = auth_routes.request_email_code(
        body=EmailCodeRequest(email="missing@example.com", purpose=EmailCodePurpose.RESET_PASSWORD),
        request=DummyRequest(),
        db=db,
        redis_client=redis_client,
        settings=smtp_settings(),
    )

    assert "如果该邮箱已注册" in response.message


def test_failed_email_delivery_discards_stored_code(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    redis_client = FakeRedis()

    class FailingSender:
        def __init__(self, _settings):
            pass

        def send_verification_code(self, **kwargs):
            raise EmailDeliveryError("delivery failed")

    monkeypatch.setattr(auth_routes, "SmtpEmailSender", FailingSender)
    with pytest.raises(HTTPException) as exc_info:
        auth_routes.request_email_code(
            body=EmailCodeRequest(email="new@example.com", purpose=EmailCodePurpose.REGISTER),
            request=DummyRequest(),
            db=db,
            redis_client=redis_client,
            settings=smtp_settings(),
        )

    assert exc_info.value.status_code == 503
    assert all(not key.startswith("auth:email-code:") for key in redis_client.data)
    assert all(not key.startswith("auth:email-code-cooldown:") for key in redis_client.data)


def test_email_code_cooldown_rejects_immediate_resend(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    redis_client = FakeRedis()

    class FakeSender:
        def __init__(self, _settings):
            pass

        def send_verification_code(self, **kwargs):
            pass

    monkeypatch.setattr(auth_routes, "SmtpEmailSender", FakeSender)
    request = EmailCodeRequest(email="new@example.com", purpose=EmailCodePurpose.REGISTER)
    auth_routes.request_email_code(
        body=request,
        request=DummyRequest(),
        db=db,
        redis_client=redis_client,
        settings=smtp_settings(),
    )

    with pytest.raises(HTTPException) as exc_info:
        auth_routes.request_email_code(
            body=request,
            request=DummyRequest(),
            db=db,
            redis_client=redis_client,
            settings=smtp_settings(),
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers == {"Retry-After": "60"}


def test_email_code_short_window_limit_applies_after_cooldown(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    redis_client = FakeRedis()
    settings = smtp_settings()

    class FakeSender:
        def __init__(self, _settings):
            pass

        def send_verification_code(self, **kwargs):
            pass

    monkeypatch.setattr(auth_routes, "SmtpEmailSender", FakeSender)
    request = EmailCodeRequest(email="new@example.com", purpose=EmailCodePurpose.REGISTER)
    for _ in range(settings.email_code_rate_limit_count):
        auth_routes.request_email_code(
            body=request,
            request=DummyRequest(),
            db=db,
            redis_client=redis_client,
            settings=settings,
        )
        release_email_code_cooldown(redis_client, email="new@example.com")

    with pytest.raises(HTTPException) as exc_info:
        auth_routes.request_email_code(
            body=request,
            request=DummyRequest(),
            db=db,
            redis_client=redis_client,
            settings=settings,
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers == {"Retry-After": "600"}


def test_unbound_user_can_verify_and_bind_email(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    redis_client = FakeRedis()
    settings = smtp_settings()
    user = User(username="unbound", password_hash=hash_password("password"))
    db.add(user)
    db.commit()
    sent: dict[str, str] = {}

    class FakeSender:
        def __init__(self, _settings):
            pass

        def send_verification_code(self, *, recipient, code, purpose):
            sent.update(recipient=recipient, code=code, purpose=purpose.value)

    monkeypatch.setattr(user_routes, "SmtpEmailSender", FakeSender)
    response = user_routes.request_email_binding_code(
        body=BindEmailCodeRequest(email="Bind@Example.com"),
        request=DummyRequest(),
        current_user=user,
        db=db,
        redis_client=redis_client,
        settings=settings,
    )

    assert response.retry_after == 60
    assert sent["recipient"] == "bind@example.com"
    assert sent["purpose"] == "bind_email"
    assert len(sent["code"]) == 6 and sent["code"].isdigit()
    bound = user_routes.bind_email(
        body=BindEmailRequest(email="BIND@example.com", email_code=sent["code"]),
        current_user=user,
        db=db,
        redis_client=redis_client,
        settings=settings,
    )

    assert bound.email == "bind@example.com"
    assert all("email-code:bind_email" not in key for key in redis_client.data)


def test_bind_email_code_is_scoped_to_current_user():
    session_factory = make_session_factory()
    db = session_factory()
    redis_client = FakeRedis()
    settings = smtp_settings()
    first = User(username="first", password_hash=hash_password("password"))
    second = User(username="second", password_hash=hash_password("password"))
    db.add_all([first, second])
    db.commit()
    store_email_code(
        redis_client,
        settings,
        email="shared@example.com",
        purpose=EmailCodePurpose.BIND_EMAIL,
        code="123456",
        subject=first.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        user_routes.bind_email(
            body=BindEmailRequest(email="shared@example.com", email_code="123456"),
            current_user=second,
            db=db,
            redis_client=redis_client,
            settings=settings,
        )

    assert exc_info.value.status_code == 400
    assert second.email is None


def test_bind_email_rejects_occupied_and_already_bound_accounts():
    session_factory = make_session_factory()
    db = session_factory()
    redis_client = FakeRedis()
    settings = smtp_settings()
    owner = User(username="owner", email="owner@example.com", password_hash=hash_password("password"))
    unbound = User(username="unbound", password_hash=hash_password("password"))
    db.add_all([owner, unbound])
    db.commit()

    with pytest.raises(HTTPException) as occupied_exc:
        user_routes.bind_email(
            body=BindEmailRequest(email="OWNER@example.com", email_code="123456"),
            current_user=unbound,
            db=db,
            redis_client=redis_client,
            settings=settings,
        )
    assert occupied_exc.value.status_code == 409

    with pytest.raises(HTTPException) as bound_exc:
        user_routes.request_email_binding_code(
            body=BindEmailCodeRequest(email="new@example.com"),
            request=DummyRequest(),
            current_user=owner,
            db=db,
            redis_client=redis_client,
            settings=settings,
        )
    assert bound_exc.value.status_code == 409


def test_bind_email_delivery_failure_releases_code_and_cooldown(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    redis_client = FakeRedis()
    user = User(username="unbound", password_hash=hash_password("password"))
    db.add(user)
    db.commit()

    class FailingSender:
        def __init__(self, _settings):
            pass

        def send_verification_code(self, **kwargs):
            raise EmailDeliveryError("delivery failed")

    monkeypatch.setattr(user_routes, "SmtpEmailSender", FailingSender)
    with pytest.raises(HTTPException) as exc_info:
        user_routes.request_email_binding_code(
            body=BindEmailCodeRequest(email="new@example.com"),
            request=DummyRequest(),
            current_user=user,
            db=db,
            redis_client=redis_client,
            settings=smtp_settings(),
        )

    assert exc_info.value.status_code == 503
    assert all(not key.startswith("auth:email-code:") for key in redis_client.data)
    assert all(not key.startswith("auth:email-code-cooldown:") for key in redis_client.data)


def test_five_wrong_codes_invalidate_email_code():
    redis_client = FakeRedis()
    settings = smtp_settings()
    store_email_code(
        redis_client,
        settings,
        email="ray@example.com",
        purpose=EmailCodePurpose.RESET_PASSWORD,
        code="123456",
    )

    for _ in range(5):
        assert not verify_email_code(
            redis_client,
            settings,
            email="ray@example.com",
            purpose=EmailCodePurpose.RESET_PASSWORD,
            code="000000",
        )

    assert not verify_email_code(
        redis_client,
        settings,
        email="ray@example.com",
        purpose=EmailCodePurpose.RESET_PASSWORD,
        code="123456",
    )


def test_admin_can_set_email_and_reset_password_without_old_password():
    session_factory = make_session_factory()
    db = session_factory()
    user = User(username="managed", password_hash=hash_password("old-password"))
    db.add(user)
    db.commit()

    response = admin_routes.admin_update_user(
        user_id=user.id,
        body=AdminUpdateUserRequest(email="Managed@Example.com", password="admin-reset"),
        db=db,
        _={"role": "admin"},
    )

    db.refresh(user)
    assert response.email == "managed@example.com"
    assert verify_password("admin-reset", user.password_hash)


def test_profile_password_change_route_is_removed():
    paths = {route.path for route in user_routes.user_router.routes}
    assert "/users/me/password" not in paths


def test_smtp_sender_uses_starttls_and_authentication(monkeypatch):
    calls: list[object] = []

    class FakeSmtp:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def ehlo(self):
            calls.append("ehlo")

        def starttls(self, context):
            calls.append("starttls")

        def login(self, username, password):
            calls.append(("login", username, password))

        def send_message(self, message):
            calls.append(("send", message["To"], message["Subject"]))

    monkeypatch.setattr("app.services.mailer.smtplib.SMTP", FakeSmtp)
    SmtpEmailSender(smtp_settings()).send_verification_code(
        recipient="user@example.com",
        code="654321",
        purpose=EmailCodePurpose.REGISTER,
    )
    SmtpEmailSender(smtp_settings()).send_verification_code(
        recipient="bind@example.com",
        code="123456",
        purpose=EmailCodePurpose.BIND_EMAIL,
    )

    assert ("connect", "smtp.example.com", 587, 15) in calls
    assert "starttls" in calls
    assert ("login", "smtp-user", "smtp-password") in calls
    assert any(call[0] == "send" and call[1] == "user@example.com" for call in calls if isinstance(call, tuple))
    assert any(
        call[0] == "send" and call[1] == "bind@example.com" and "绑定邮箱验证码" in call[2]
        for call in calls
        if isinstance(call, tuple)
    )


def test_public_gallery_requires_user_master_switch_and_published_job():
    session_factory = make_session_factory()
    db = session_factory()
    visible_user = User(username="visible", password_hash="hash", is_public=True)
    hidden_user = User(username="hidden", password_hash="hash", is_public=False)
    db.add_all([visible_user, hidden_user])
    db.flush()
    now = datetime.now(timezone.utc)
    visible_job = GenerationJob(
        prompt="visible prompt",
        model="gpt-image-2-c",
        status=JobStatus.SUCCEEDED,
        user_id=visible_user.id,
        is_public=True,
        object_key="generated/visible.jpg",
        media_state=MediaState.AVAILABLE,
        finished_at=now,
    )
    hidden_job = GenerationJob(
        prompt="hidden prompt",
        model="gpt-image-2-c",
        status=JobStatus.SUCCEEDED,
        user_id=hidden_user.id,
        is_public=True,
        object_key="generated/hidden.jpg",
        media_state=MediaState.AVAILABLE,
        finished_at=now,
    )
    legacy_anonymous_job = GenerationJob(
        prompt="legacy anonymous prompt",
        model="gpt-image-2-c",
        status=JobStatus.SUCCEEDED,
        user_id=None,
        is_public=True,
        object_key="generated/legacy-anonymous.jpg",
        media_state=MediaState.AVAILABLE,
        finished_at=now,
    )
    db.add_all([visible_job, hidden_job, legacy_anonymous_job])
    db.commit()

    public_items = routes.get_public_gallery(
        db=db,
        current_user=None,
        sort="recent",
        offset=0,
        limit=20,
    )
    assert {item.job_id for item in public_items} == {visible_job.id, legacy_anonymous_job.id}

    inspiration_items = inspiration_routes.list_inspirations(
        db=db,
        offset=0,
        limit=20,
        q=None,
        source="gallery",
        category=None,
        sort="recent",
    )
    # The community feed is now a permanent curated/imported collection;
    # ordinary public-gallery jobs remain available only in the gallery.
    assert inspiration_items.items == []

    with pytest.raises(HTTPException) as exc_info:
        routes.get_user_gallery(username="hidden", db=db, offset=0, limit=20)
    assert exc_info.value.status_code == 404

    hidden_user.is_public = True
    db.commit()
    hidden_items = routes.get_user_gallery(username="hidden", db=db, offset=0, limit=20)
    assert [item.job_id for item in hidden_items] == [hidden_job.id]
