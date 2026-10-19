from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth_routes import auth_router
from app.core import auth
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.models.auth_session import AuthSession
from app.models.user import User
from app.services import auth_sessions as sessions
from app.services.redis_client import get_redis

HEADERS = {'X-Session-Request': '1', 'Origin': 'https://testserver'}


@pytest.fixture
def env(monkeypatch):
    settings = Settings(app_env='production', jwt_secret_key='test-session-secret-with-at-least-32-bytes')
    monkeypatch.setattr(auth, 'get_settings', lambda: settings)
    monkeypatch.setattr(sessions, 'get_settings', lambda: settings)
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    factory = sessionmaker(engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    db = factory()
    user = User(username='session_user', password_hash=auth.hash_password('password'))
    db.add(user)
    db.commit()
    app = FastAPI()
    app.include_router(auth_router, prefix='/api/v1')
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_redis] = lambda: SimpleNamespace(incr=lambda _: 1, expire=lambda *_: None)

    @app.get('/private')
    def private(current: User = Depends(auth.require_current_user)):
        return {'id': current.id}

    with TestClient(app, base_url='https://testserver', headers=HEADERS) as client:
        yield SimpleNamespace(db=db, user=user, client=client, settings=settings)
    db.close()
    engine.dispose()


def login(env):
    response = env.client.post('/api/v1/auth/login', json={'username': env.user.username, 'password': 'password'})
    assert response.status_code == 200, response.text
    return response


def bearer(token):
    return {'Authorization': f'Bearer {token}'}


def test_login_issues_short_access_and_private_refresh_cookie(env):
    response = login(env)
    payload = auth.decode_access_token(response.json()['access_token'])
    assert payload['typ'] == 'access'
    assert 898 <= payload['exp'] - sessions.utcnow().timestamp() <= 900
    cookie = response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=strict' in cookie
    assert 'Path=/api/v1/auth' in cookie and 'Domain=' not in cookie
    assert response.headers['cache-control'] == 'no-store'
    assert set(response.json()) == {'access_token', 'token_type'}
    row = env.db.get(AuthSession, payload['sid'])
    assert sessions.as_utc(row.expires_at) - sessions.as_utc(row.created_at) == timedelta(days=30)
    assert sessions.as_utc(row.absolute_expires_at) - sessions.as_utc(row.created_at) == timedelta(days=180)


def test_rotation_slides_idle_deadline_and_concurrent_retry_reuses_successor(env, monkeypatch):
    login(env)
    old_cookie = env.client.cookies.get(sessions.COOKIE_NAME)
    row = env.db.query(AuthSession).one()
    original_expiry = sessions.as_utc(row.expires_at)
    now = sessions.as_utc(row.created_at) + timedelta(days=10)
    monkeypatch.setattr(sessions, 'utcnow', lambda: now)
    first = env.client.post('/api/v1/auth/refresh')
    assert first.status_code == 200
    successor = env.client.cookies.get(sessions.COOKIE_NAME)
    assert successor != old_cookie
    env.db.refresh(row)
    assert sessions.as_utc(row.expires_at) == original_expiry + timedelta(days=10)
    retry = sessions.rotate_session(env.db, old_cookie)
    assert sessions.refresh_token(retry) == successor
    assert retry.generation == 1


def test_idle_and_absolute_expiry_cannot_be_extended(env, monkeypatch):
    login(env)
    row = env.db.query(AuthSession).one()
    now = sessions.utcnow()
    row.absolute_expires_at = now + timedelta(hours=1)
    env.db.commit()
    response = env.client.post('/api/v1/auth/refresh')
    assert response.status_code == 200
    env.db.refresh(row)
    assert sessions.as_utc(row.expires_at) == sessions.as_utc(row.absolute_expires_at)
    monkeypatch.setattr(sessions, 'utcnow', lambda: now + timedelta(hours=2))
    assert env.client.post('/api/v1/auth/refresh').status_code == 401
    assert sessions.COOKIE_NAME not in env.client.cookies


def test_inactive_session_expires_even_before_absolute_limit(env, monkeypatch):
    login(env)
    now = sessions.utcnow() + timedelta(days=31)
    monkeypatch.setattr(sessions, 'utcnow', lambda: now)
    assert env.client.post('/api/v1/auth/refresh').status_code == 401


def test_replayed_refresh_revokes_entire_session_and_access(env, monkeypatch):
    access = login(env).json()['access_token']
    old = env.client.cookies.get(sessions.COOKIE_NAME)
    assert env.client.post('/api/v1/auth/refresh').status_code == 200
    now = sessions.utcnow() + timedelta(seconds=31)
    monkeypatch.setattr(sessions, 'utcnow', lambda: now)
    with pytest.raises(HTTPException) as failure:
        sessions.rotate_session(env.db, old)
    assert failure.value.status_code == 401
    assert env.client.get('/private', headers=bearer(access)).status_code == 401
    assert env.client.post('/api/v1/auth/refresh').status_code == 401


def test_logout_revokes_refresh_and_access_and_clears_cookie(env):
    access = login(env).json()['access_token']
    assert env.client.get('/private', headers=bearer(access)).status_code == 200
    response = env.client.post('/api/v1/auth/logout')
    assert response.status_code == 204
    assert sessions.COOKIE_NAME not in env.client.cookies
    assert env.client.get('/private', headers=bearer(access)).status_code == 401


def test_password_change_invalidates_all_sessions(env):
    access = login(env).json()['access_token']
    env.user.password_hash = auth.hash_password('new-password')
    env.db.commit()
    assert env.client.get('/private', headers=bearer(access)).status_code == 401
    assert env.client.post('/api/v1/auth/refresh').status_code == 401


@pytest.mark.parametrize('path', ['refresh', 'logout', 'session', 'login', 'register'])
def test_cross_origin_and_missing_csrf_header_rejected(env, path):
    access = login(env).json()['access_token']
    body = {'username': 'session_user', 'password': 'password'} if path == 'login' else {
        'username': 'new_user', 'password': 'password', 'email': 'user@example.com', 'email_code': '123456',
    } if path == 'register' else None
    response = env.client.post(f'/api/v1/auth/{path}', json=body,
                               headers={**bearer(access), 'Origin': 'https://attacker.test'})
    assert response.status_code == 403
    response = env.client.post(f'/api/v1/auth/{path}', json=body,
                               headers={**bearer(access), 'X-Session-Request': ''})
    assert response.status_code == 403


def test_legacy_exchange_requires_valid_old_user_token_and_cannot_reset_absolute_lifetime(env):
    old_access = auth.create_access_token({'sub': env.user.id})
    response = env.client.post('/api/v1/auth/session', headers=bearer(old_access))
    assert response.status_code == 200
    access = response.json()['access_token']
    assert auth.decode_access_token(access)['sid']
    assert env.client.post('/api/v1/auth/session', headers=bearer(access)).status_code == 401
    admin = auth.create_access_token({'sub': 'admin', 'role': 'admin'})
    assert env.client.post('/api/v1/auth/session', headers=bearer(admin)).status_code == 401
    refresh_jwt = auth.create_access_token({'sub': env.user.id, 'typ': 'refresh'})
    assert env.client.get('/private', headers=bearer(refresh_jwt)).status_code == 401


def test_forged_cookie_does_not_revoke_legitimate_session(env):
    access = login(env).json()['access_token']
    cookie = env.client.cookies.get(sessions.COOKIE_NAME)
    env.client.cookies.clear()
    env.client.cookies.set(sessions.COOKIE_NAME, cookie[:-1] + ('0' if cookie[-1] != '0' else '1'))
    assert env.client.post('/api/v1/auth/refresh').status_code == 401
    assert env.client.get('/private', headers=bearer(access)).status_code == 200


def test_dev_proxy_origin_and_malformed_origin(env, monkeypatch):
    settings = env.settings.model_copy(update={'app_env': 'development'})
    monkeypatch.setattr(sessions, 'get_settings', lambda: settings)
    response = env.client.post('/api/v1/auth/login',
        headers={'Origin': 'http://localhost:5173'},
        json={'username': env.user.username, 'password': 'password'})
    assert response.status_code == 200
    response = env.client.post('/api/v1/auth/refresh', headers={'Origin': 'http://['})
    assert response.status_code == 403
