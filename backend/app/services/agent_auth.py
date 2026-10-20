"""OAuth grants and agent budgets. Always lock owner -> grant -> authorization.

Credentials are random opaque values, persisted only as SHA-256 digests. They
cannot authenticate browser APIs. MCP resource identity comes from configuration.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.agent import AgentAuthorization, AgentClient, AgentCredential, AgentGrant
from app.models.user import User
from app.services.auth_sessions import as_utc, password_digest, utcnow

SCOPES = {'account:read': '查看积分余额', 'jobs:read': '读取自己的任务、提示词与图片', 'jobs:create': '生成和修改图片，使用积分'}
ACCESS_SECONDS = 900


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def resource_url() -> str:
    value = get_settings().mcp_public_url
    try:
        u = urlsplit(value)
        valid = (u.scheme == 'https' or (get_settings().app_env != 'production' and u.scheme == 'http' and u.hostname in {'127.0.0.1', 'localhost', '::1'}))
        if not valid or not u.hostname or u.username or u.password or u.query or u.fragment or u.path != '/api/mcp':
            raise ValueError()
        return value
    except ValueError:
        raise HTTPException(503, 'Agent 接入尚未配置，请联系站点管理员。') from None


def origin_url() -> str:
    u = urlsplit(resource_url())
    return f'{u.scheme}://{u.netloc}'


def redirect_valid(value: str) -> bool:
    try:
        u = urlsplit(value)
        return bool(len(value) <= 2048 and u.hostname and not u.username and not u.password and not u.fragment
                    and '\\' not in value and all(ord(c) >= 32 for c in value)
                    and (u.scheme == 'https' or (u.scheme == 'http' and u.hostname in {'127.0.0.1', '::1', 'localhost'})))
    except ValueError:
        return False


def registered_redirect(client: AgentClient, value: str) -> bool:
    if not redirect_valid(value):
        return False
    if value in client.redirect_uris:
        return True
    # RFC 8252 permits a variable port for IP loopback callbacks, never a
    # different host, path, scheme or query (and never arbitrary HTTPS ports).
    u = urlsplit(value)
    if u.scheme != 'http' or u.hostname not in {'127.0.0.1', '::1'}:
        return False
    return any((lambda r: r.scheme == u.scheme and r.hostname == u.hostname and r.path == u.path and r.query == u.query)(urlsplit(v)) for v in client.redirect_uris)


def callback(auth: AgentAuthorization, **params: str) -> str:
    u = urlsplit(auth.redirect_uri)
    query = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k not in {'code', 'state', 'error', 'iss'}]
    query += list(params.items()) + [('state', auth.state), ('iss', origin_url())]
    return urlunsplit((u.scheme, u.netloc, u.path, urlencode(query), ''))


def valid_grant(grant: AgentGrant | None, user: User | None) -> bool:
    return bool(grant and user and grant.user_id == user.id and not grant.revoked_at
                and as_utc(grant.expires_at) > utcnow() and grant.resource == resource_url()
                and hmac.compare_digest(grant.password_digest, password_digest(user)))


def grant_for_update(db: Session, grant_id: str, *, user_id: str | None = None) -> tuple[AgentGrant, User]:
    row = db.get(AgentGrant, grant_id)
    if not row or (user_id is not None and row.user_id != user_id):
        raise HTTPException(401, 'Agent 授权已失效。')
    user = db.scalar(select(User).where(User.id == row.user_id).with_for_update().execution_options(populate_existing=True))
    row = db.scalar(select(AgentGrant).where(AgentGrant.id == grant_id).with_for_update().execution_options(populate_existing=True))
    if not valid_grant(row, user):
        raise HTTPException(401, 'Agent 授权已失效，请重新连接。')
    return row, user


def verify_access(db: Session, token: str) -> AgentGrant:
    if len(token) > 256 or not token.startswith('ep_access_'):
        raise HTTPException(401, '无效的 Agent 凭证。')
    credential = db.get(AgentCredential, digest(token))
    grant = db.get(AgentGrant, credential.grant_id) if credential else None
    user = db.get(User, grant.user_id) if grant else None
    if not credential or credential.kind != 'access' or as_utc(credential.expires_at) <= utcnow() or not valid_grant(grant, user):
        raise HTTPException(401, 'Agent 授权已失效，请重新连接。')
    return grant


def issue_tokens(db: Session, grant: AgentGrant) -> dict:
    now = utcnow()
    access, refresh = 'ep_access_' + secrets.token_urlsafe(32), 'ep_refresh_' + secrets.token_urlsafe(32)
    expires = min(now + timedelta(seconds=ACCESS_SECONDS), as_utc(grant.expires_at))
    for value, kind, deadline in [(access, 'access', expires), (refresh, 'refresh', grant.expires_at)]:
        db.add(AgentCredential(token_hash=digest(value), grant_id=grant.id, kind=kind, expires_at=deadline))
    return dict(access_token=access, refresh_token=refresh, token_type='Bearer', expires_in=max(0, int((expires - now).total_seconds())), scope=' '.join(grant.scopes))


def exchange_code(db: Session, data: dict) -> dict:
    auth = db.scalar(select(AgentAuthorization).where(AgentAuthorization.code_hash == digest(data.get('code', ''))))
    if not auth or not auth.grant_id:
        raise HTTPException(400, '授权码无效。')
    grant, _ = grant_for_update(db, auth.grant_id)
    auth = db.scalar(select(AgentAuthorization).where(AgentAuthorization.id == auth.id).with_for_update().execution_options(populate_existing=True))
    verifier = data.get('code_verifier', '')
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    if (auth.consumed_at or as_utc(auth.expires_at) <= utcnow() or auth.client_id != data.get('client_id')
            or auth.redirect_uri != data.get('redirect_uri') or auth.resource != data.get('resource')
            or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier) or not hmac.compare_digest(auth.challenge, challenge)):
        raise HTTPException(400, '授权码、PKCE 或回调参数无效。')
    auth.consumed_at = utcnow()
    result = issue_tokens(db, grant)
    db.commit()
    return result


def refresh_tokens(db: Session, data: dict) -> dict:
    credential = db.get(AgentCredential, digest(data.get('refresh_token', '')))
    if not credential or credential.kind != 'refresh':
        raise HTTPException(400, '刷新凭证无效。')
    grant, _ = grant_for_update(db, credential.grant_id)
    credential = db.scalar(select(AgentCredential).where(AgentCredential.token_hash == credential.token_hash).with_for_update().execution_options(populate_existing=True))
    if grant.client_id != data.get('client_id') or data.get('resource') != resource_url():
        raise HTTPException(400, '客户端或目标服务不匹配。')
    if credential.used_at:
        grant.revoked_at = utcnow()
        db.commit()
        raise HTTPException(400, '检测到刷新凭证重放，请重新授权。')
    if as_utc(credential.expires_at) <= utcnow():
        raise HTTPException(400, '刷新凭证已过期。')
    requested = set(data.get('scope', ' '.join(grant.scopes)).split())
    if requested != set(grant.scopes):
        raise HTTPException(400, '刷新时不能修改权限，请重新授权。')
    credential.used_at = utcnow()
    result = issue_tokens(db, grant)
    db.commit()
    return result


def check_budget(db: Session, grant: AgentGrant, amount: int, max_cost: int) -> None:
    if 'jobs:create' not in grant.scopes:
        raise HTTPException(403, '此连接未获准生成或修改图片。')
    if amount > min(grant.max_per_job, max_cost):
        raise HTTPException(403, {'message': '超过单次消费上限。', 'required': amount, 'max_per_job': grant.max_per_job, 'max_cost': max_cost})
