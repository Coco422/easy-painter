"""Browser-owned grant management and OAuth public-client endpoints."""
from datetime import timedelta
import re
import secrets
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import require_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.agent import AgentAuthorization, AgentClient, AgentGrant
from app.models.user import User
from app.services import agent_auth as service
from app.services.auth_sessions import as_utc, check_session_request, password_digest, utcnow
from app.core.network import extract_client_ip, rate_limit_identity
from app.services.rate_limit import GenerationRateLimiter
from app.services.redis_client import get_redis

agent_router = APIRouter()
oauth_router = APIRouter()


class Limits(BaseModel):
    model_config = ConfigDict(extra='forbid')
    max_per_job: Annotated[int, Field(strict=True, ge=0, le=100000)] = 10
    daily_limit: Annotated[int, Field(strict=True, ge=0, le=1000000)] = 100


class Consent(Limits):
    allow: Annotated[bool, Field(strict=True)] = True
    days: Literal[7, 30, 90] = 30
    scopes: list[str] = Field(default_factory=list)


def no_store(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'


def rate(request: Request, redis_client, purpose: str, limit: int):
    result = GenerationRateLimiter(redis_client=redis_client, limit=limit, window_seconds=3600).check(
        f'agent:{purpose}:{rate_limit_identity(extract_client_ip(request))}')
    if not result.allowed:
        raise HTTPException(429, '请求过于频繁，请稍后再试。')


async def limited_json(request: Request) -> dict:
    body = b''
    async for chunk in request.stream():
        body += chunk
        if len(body) > 16384:
            raise HTTPException(413, '请求过大。')
    import json
    try:
        value = json.loads(body)
        if not isinstance(value, dict): raise ValueError()
        return value
    except (ValueError, TypeError):
        raise HTTPException(400, 'JSON 无效。') from None


@oauth_router.get('/.well-known/oauth-authorization-server')
def oauth_metadata():
    base = service.origin_url()
    return {'issuer': base, 'authorization_endpoint': base + '/api/oauth/authorize',
            'token_endpoint': base + '/api/oauth/token', 'registration_endpoint': base + '/api/oauth/register',
            'revocation_endpoint': base + '/api/oauth/revoke', 'response_types_supported': ['code'],
            'grant_types_supported': ['authorization_code', 'refresh_token'], 'code_challenge_methods_supported': ['S256'],
            'token_endpoint_auth_methods_supported': ['none'], 'scopes_supported': list(service.SCOPES),
            'authorization_response_iss_parameter_supported': True}


@oauth_router.get('/.well-known/oauth-protected-resource')
@oauth_router.get('/.well-known/oauth-protected-resource/api/mcp')
def resource_metadata():
    return {'resource': service.resource_url(), 'authorization_servers': [service.origin_url()],
            'scopes_supported': list(service.SCOPES), 'bearer_methods_supported': ['header']}


@agent_router.get('/config')
def config(response: Response):
    no_store(response)
    try:
        endpoint = service.resource_url()
        return {'enabled': True, 'endpoint': endpoint, 'scopes': service.SCOPES}
    except HTTPException:
        return {'enabled': False, 'endpoint': None, 'scopes': service.SCOPES}


@oauth_router.post('/api/oauth/register', status_code=201)
async def register(request: Request, response: Response, db: Session = Depends(get_db), redis_client=Depends(get_redis)):
    service.resource_url()
    rate(request, redis_client, 'register', 20)
    data = await limited_json(request)
    uris, name = data.get('redirect_uris'), data.get('client_name', 'MCP 客户端')
    if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 100 or not isinstance(uris, list)
            or not 1 <= len(uris) <= 5 or any(not isinstance(u, str) or not service.redirect_valid(u) for u in uris)
            or data.get('token_endpoint_auth_method', 'none') != 'none'
            or data.get('grant_types', ['authorization_code', 'refresh_token']) not in [['authorization_code'], ['authorization_code', 'refresh_token']]
            or data.get('response_types', ['code']) != ['code']):
        raise HTTPException(400, '仅支持 HTTPS 或回环回调、公开客户端与授权码流程。')
    row = AgentClient(name=name.strip(), redirect_uris=list(dict.fromkeys(uris)), created_at=utcnow())
    db.add(row); db.commit()
    no_store(response)
    return {'client_id': row.id, 'client_name': row.name, 'redirect_uris': row.redirect_uris,
            'token_endpoint_auth_method': 'none', 'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code']}


@oauth_router.get('/api/oauth/authorize')
def authorize(request: Request, client_id: str, redirect_uri: str, response_type: str,
              code_challenge: str, code_challenge_method: str, resource: str, state: str = '',
              scope: str = 'account:read jobs:read jobs:create', db: Session = Depends(get_db), redis_client=Depends(get_redis)):
    canonical = service.resource_url()
    rate(request, redis_client, 'authorize', 60)
    client = db.get(AgentClient, client_id)
    scopes = scope.split()
    if (not client or not service.registered_redirect(client, redirect_uri) or response_type != 'code'
            or code_challenge_method != 'S256' or not re.fullmatch(r'[A-Za-z0-9_-]{43}', code_challenge)
            or resource != canonical or not scopes or set(scopes) - service.SCOPES.keys() or len(state) > 1024):
        # Do not redirect errors to unvalidated client-supplied callback URLs.
        raise HTTPException(400, '客户端、回调、权限或 PKCE 参数无效。')
    row = AgentAuthorization(client_id=client.id, redirect_uri=redirect_uri, state=state, challenge=code_challenge,
                             scopes=sorted(set(scopes)), resource=canonical, expires_at=utcnow() + timedelta(minutes=10))
    db.add(row); db.commit()
    result = RedirectResponse(service.origin_url() + '/mcp/authorize?request=' + row.id, status_code=303)
    no_store(result)
    result.headers['Referrer-Policy'] = 'no-referrer'
    return result


def authorization(db: Session, request_id: str) -> AgentAuthorization:
    row = db.get(AgentAuthorization, request_id)
    if not row or row.consumed_at or row.grant_id or as_utc(row.expires_at) <= utcnow():
        raise HTTPException(400, '授权请求已使用或过期，请从 Agent 重新连接。')
    return row


@agent_router.get('/authorizations/{request_id}')
def consent_details(request_id: str, response: Response, db: Session = Depends(get_db), user: User = Depends(require_current_user)):
    row = authorization(db, request_id)
    client = db.get(AgentClient, row.client_id)
    no_store(response)
    return {'client_name': client.name, 'redirect_uri': row.redirect_uri, 'scopes': row.scopes, 'expires_at': row.expires_at}


@agent_router.post('/authorizations/{request_id}')
def consent(request_id: str, body: Consent, request: Request, response: Response,
            db: Session = Depends(get_db), user: User = Depends(require_current_user)):
    check_session_request(request)
    if body.daily_limit < body.max_per_job:
        raise HTTPException(422, '每日额度不能低于单次上限。')
    user = db.scalar(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))
    row = db.scalar(select(AgentAuthorization).where(AgentAuthorization.id == request_id).with_for_update().execution_options(populate_existing=True))
    authorization(db, request_id)
    no_store(response)
    if not body.allow:
        row.consumed_at = utcnow(); db.commit()
        return {'redirect_to': service.callback(row, error='access_denied')}
    scopes = sorted(set(body.scopes))
    if not scopes or set(scopes) - set(row.scopes):
        raise HTTPException(422, '只能授权客户端请求的权限。')
    from sqlalchemy import func
    active = db.scalar(select(func.count()).select_from(AgentGrant).where(AgentGrant.user_id == user.id, AgentGrant.revoked_at.is_(None), AgentGrant.expires_at > utcnow()))
    if active >= 50:
        raise HTTPException(409, '有效连接已达 50 个，请先断开不用的连接。')
    client = db.get(AgentClient, row.client_id)
    grant = AgentGrant(user_id=user.id, client_id=client.id, resource=row.resource, label=client.name, scopes=scopes,
                       password_digest=password_digest(user), max_per_job=body.max_per_job, daily_limit=body.daily_limit,
                       created_at=utcnow(), expires_at=utcnow() + timedelta(days=body.days))
    db.add(grant); db.flush()
    code = secrets.token_urlsafe(32)
    row.grant_id = grant.id; row.code_hash = service.digest(code); row.expires_at = utcnow() + timedelta(seconds=60)
    db.commit()
    return {'redirect_to': service.callback(row, code=code)}


@oauth_router.post('/api/oauth/token')
async def token(request: Request, db: Session = Depends(get_db), redis_client=Depends(get_redis)):
    service.resource_url()
    rate(request, redis_client, 'token', 180)
    raw = b''
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > 16384: raise HTTPException(413, '请求过大。')
    from urllib.parse import parse_qsl
    try:
        values = parse_qsl(raw.decode(), keep_blank_values=True, max_num_fields=15)
        data = dict(values)
        if len(data) != len(values): raise ValueError()
        if data.get('grant_type') == 'authorization_code': result = service.exchange_code(db, data)
        elif data.get('grant_type') == 'refresh_token': result = service.refresh_tokens(db, data)
        else: return JSONResponse({'error': 'unsupported_grant_type'}, status_code=400, headers={'Cache-Control': 'no-store'})
        return JSONResponse(result, headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})
    except (HTTPException, ValueError, UnicodeError) as error:
        db.rollback()
        return JSONResponse({'error': 'invalid_grant', 'error_description': str(getattr(error, 'detail', 'Invalid request'))}, status_code=400, headers={'Cache-Control': 'no-store'})


def grant_view(db: Session, row: AgentGrant) -> dict:
    user = db.get(User, row.user_id)
    return {'id': row.id, 'label': row.label, 'scopes': row.scopes, 'max_per_job': row.max_per_job,
            'daily_limit': row.daily_limit, 'used_today': service.daily_usage(db, row.id), 'expires_at': row.expires_at,
            'created_at': row.created_at, 'active': service.valid_grant(row, user)}


@agent_router.get('/connections')
def connections(response: Response, db: Session = Depends(get_db), user: User = Depends(require_current_user)):
    no_store(response)
    rows = db.scalars(select(AgentGrant).where(AgentGrant.user_id == user.id).order_by(AgentGrant.created_at.desc()).limit(100))
    return [grant_view(db, row) for row in rows]


@agent_router.put('/connections/{grant_id}')
def update_limits(grant_id: str, body: Limits, request: Request, response: Response,
                  db: Session = Depends(get_db), user: User = Depends(require_current_user)):
    check_session_request(request)
    if body.daily_limit < body.max_per_job: raise HTTPException(422, '每日额度不能低于单次上限。')
    grant, _ = service.grant_for_update(db, grant_id, user_id=user.id)
    grant.max_per_job, grant.daily_limit = body.max_per_job, body.daily_limit
    db.commit(); no_store(response)
    return grant_view(db, grant)


@agent_router.delete('/connections/{grant_id}', status_code=204)
def revoke(grant_id: str, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(require_current_user)):
    check_session_request(request)
    row = db.get(AgentGrant, grant_id)
    if not row or row.user_id != user.id: raise HTTPException(404, '连接不存在。')
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    row = db.scalar(select(AgentGrant).where(AgentGrant.id == grant_id).with_for_update().execution_options(populate_existing=True))
    row.revoked_at = utcnow(); db.commit(); no_store(response)


@oauth_router.post('/api/oauth/revoke')
async def revoke_token(request: Request, db: Session = Depends(get_db), redis_client=Depends(get_redis)):
    rate(request, redis_client, 'revoke', 180)
    from urllib.parse import parse_qsl
    body = b''
    async for chunk in request.stream():
        body += chunk
        if len(body) > 16384: raise HTTPException(413, '请求过大。')
    try:
        pairs = parse_qsl(body.decode(), max_num_fields=10)
        form = dict(pairs)
        if len(form) != len(pairs): raise ValueError()
    except (ValueError, UnicodeError): raise HTTPException(400, '请求无效。') from None
    from app.models.agent import AgentCredential
    credential = db.get(AgentCredential, service.digest(str(form.get('token', ''))))
    if credential:
        grant = db.get(AgentGrant, credential.grant_id)
        if grant and grant.client_id == form.get('client_id'):
            try:
                grant, _ = service.grant_for_update(db, grant.id)
                grant.revoked_at = utcnow(); db.commit()
            except HTTPException: db.rollback()
    return Response(status_code=200, headers={'Cache-Control': 'no-store'})


@agent_router.api_route('/media/{job_id}', methods=['GET', 'HEAD'])
def media(job_id: str, request: Request, token: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    import jwt
    from fastapi.responses import StreamingResponse
    from app.services.agent_tools import owned_job
    from app.api.routes import _job_has_available_media
    from app.services.storage import MinioStorageService, StorageError
    try:
        claims = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm], audience='agent_media')
        if claims.get('typ') != 'agent_media' or claims.get('job') != job_id or claims.get('resource') != service.resource_url(): raise ValueError()
        grant = db.get(AgentGrant, claims.get('grant', ''))
        if not service.valid_grant(grant, db.get(User, grant.user_id) if grant else None) or 'jobs:read' not in grant.scopes: raise ValueError()
        job = owned_job(db, grant.user_id, job_id)
        if not _job_has_available_media(job): raise ValueError()
    except (jwt.PyJWTError, ValueError, HTTPException):
        raise HTTPException(404, '图片链接已失效。', headers={'Cache-Control': 'no-store'}) from None
    headers = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer'}
    if request.method == 'HEAD': return Response(media_type=job.media_content_type, headers=headers)
    try:
        storage = MinioStorageService()
        opened = storage.open_object(job.object_key)
        return StreamingResponse(storage.iter_response(opened), media_type=job.media_content_type, headers=headers)
    except StorageError:
        raise HTTPException(503, '图片暂时无法读取。', headers={'Cache-Control': 'no-store'}) from None
