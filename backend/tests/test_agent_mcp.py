import base64
import hashlib
import io
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import routes, agent_routes
from app.api.agent_content_routes import content_router
from app.core import auth as web_auth
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.models.agent import AgentCredential, AgentGrant, AgentUsage
from app.models.credit_transaction import CreditTransaction, CreditTransactionType
from app.models.generation_job import GenerationJob, JobStatus
from app.models.job_charge import JobCharge
from app.models.media import MediaState
from app.models.outbox_event import OutboxEvent
from app.models.user import User
from app.services import agent_auth, agent_tools, auth_sessions, mcp_server
from app.services.billing import refund_job_charge
from app.services.redis_client import get_redis

RESOURCE = 'https://testserver/api/mcp'
SCOPES = 'account:read jobs:read jobs:create'
VERIFIER = 'a' * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip('=')
MODELS = [{'id':'test-image','label':'Test Image','enabled':True,'supports_reference_image':True,'max_reference_images':5,'supported_sizes':[],'credit_cost':5}]


@pytest.fixture
def env(monkeypatch):
    settings = Settings(app_env='development', mcp_public_url=RESOURCE, jwt_secret_key='test-mcp-secret-with-at-least-32-bytes', prompt_max_length=4000)
    for module in [agent_auth, agent_tools, mcp_server, web_auth, auth_sessions]: monkeypatch.setattr(module, 'get_settings', lambda: settings)
    monkeypatch.setattr(routes, '_load_models', lambda *_: MODELS)
    limiter = lambda **_: SimpleNamespace(check=lambda _: SimpleNamespace(allowed=True, remaining=10))
    monkeypatch.setattr(agent_routes, 'GenerationRateLimiter', limiter)
    monkeypatch.setattr(routes, 'GenerationRateLimiter', limiter)
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(mcp_server, 'SessionLocal', factory)
    monkeypatch.setattr(mcp_server, 'get_redis', lambda: None)
    db = factory()
    user = User(username='mcp_user', password_hash=web_auth.hash_password('password'), credits=100)
    other = User(username='other_user', password_hash=web_auth.hash_password('password'), credits=100)
    db.add_all([user, other]); db.flush()
    for u in [user, other]:
        db.add(CreditTransaction(user_id=u.id, amount=100, balance_after=100, reason='test:opening', transaction_type=CreditTransactionType.OPENING_BALANCE, idempotency_key='opening:'+u.id))
    db.commit()
    server, mcp_app = mcp_server.build_mcp_server()
    @asynccontextmanager
    async def lifespan(_):
        async with server.session_manager.run(): yield
    app = FastAPI(lifespan=lifespan)
    app.include_router(agent_routes.agent_router, prefix='/api/v1/agent'); app.include_router(agent_routes.oauth_router); app.include_router(content_router)
    app.include_router(routes.router, prefix='/api/v1'); app.mount('/api', mcp_app)
    def database():
        with factory() as session: yield session
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_redis] = lambda: None
    with TestClient(app, base_url='https://testserver') as client:
        yield SimpleNamespace(client=client,db=db,factory=factory,user=user,other=other,access=web_auth.create_access_token({'sub':user.id}),other_access=web_auth.create_access_token({'sub':other.id}),settings=settings)
    db.close(); engine.dispose()


def headers(e, other=False):
    return {'Authorization':'Bearer '+(e.other_access if other else e.access),'X-Session-Request':'1','Origin':'https://testserver'}


def start(e, **overrides):
    c=e.client.post('/api/oauth/register',json={'client_name':'Test Client','redirect_uris':['http://127.0.0.1/callback'],'token_endpoint_auth_method':'none'})
    assert c.status_code==201,c.text
    params=dict(client_id=c.json()['client_id'],redirect_uri='http://127.0.0.1:31234/callback',response_type='code',code_challenge=CHALLENGE,code_challenge_method='S256',resource=RESOURCE,state='user-state',scope=SCOPES)
    params.update(overrides)
    return params,e.client.get('/api/oauth/authorize',params=params,follow_redirects=False)


def approve(e, scopes=None, single=10, daily=None):
    params,r=start(e);assert r.status_code==303,r.text
    request_id=parse_qs(urlsplit(r.headers['location']).query)['request'][0]
    r=e.client.post('/api/v1/agent/authorizations/'+request_id,headers=headers(e),json={'allow':True,'scopes':scopes or SCOPES.split(),'max_per_job':single,'days':30,**({'daily_limit':daily} if daily is not None else {})})
    assert r.status_code==200,r.text
    callback=parse_qs(urlsplit(r.json()['redirect_to']).query)
    assert callback['state']==['user-state'] and callback['iss']==['https://testserver']
    exchange=dict(grant_type='authorization_code',code=callback['code'][0],client_id=params['client_id'],redirect_uri=params['redirect_uri'],code_verifier=VERIFIER,resource=RESOURCE)
    return params,request_id,exchange


def connect(e, **kwargs):
    params,_,exchange=approve(e,**kwargs)
    r=e.client.post('/api/oauth/token',data=exchange);assert r.status_code==200,r.text
    return SimpleNamespace(tokens=r.json(),grant=e.db.scalar(select(AgentGrant).where(AgentGrant.client_id==params['client_id'])),exchange=exchange)


def rpc(e,c,name,args=None):
    r=e.client.post('/api/mcp',headers={'Authorization':'Bearer '+c.tokens['access_token'],'Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-11-25'},json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args or {}}})
    assert r.status_code==200,r.text
    return r.json()['result']


def value(result):
    import json
    assert not result.get('isError'),result
    return result.get('structuredContent') or json.loads(next(item['text'] for item in result['content'] if item['type']=='text'))


def submit(e,c,key='job-1',**overrides):
    args=dict(prompt='A labeled workflow',model='test-image',size='auto',request_id=key,max_cost=5);args.update(overrides)
    return rpc(e,c,'generate_image',args)


def test_discovery_and_credential_separation(env):
    e=env
    assert e.client.get('/.well-known/oauth-protected-resource/api/mcp').json()['resource']==RESOURCE
    assert e.client.get('/.well-known/oauth-authorization-server').json()['code_challenge_methods_supported']==['S256']
    for h in [{},headers(e)]:
        r=e.client.post('/api/mcp',headers={**h,'Accept':'application/json, text/event-stream'},json={'jsonrpc':'2.0','id':1,'method':'tools/list'})
        assert r.status_code==401 and 'resource_metadata=' in r.headers['www-authenticate']
    c=connect(e)
    assert e.client.get('/api/v1/agent/connections',headers={'Authorization':'Bearer '+c.tokens['access_token']}).status_code==401
    assert value(rpc(e,c,'list_models'))['models'][0]['credit_cost']==5


@pytest.mark.parametrize('changes',[{'code_challenge_method':'plain'},{'code_challenge':'bad'},{'resource':'https://wrong.example/mcp'},{'scope':'admin:all'},{'redirect_uri':'https://evil.example/callback'},{'response_type':'token'}])
def test_authorize_rejects_invalid_parameters(env,changes):
    _,r=start(env,**changes);assert r.status_code==400 and 'location' not in r.headers


def test_registration_rejects_unsafe_redirects(env):
    for uri in ['http://remote.example/callback','javascript:alert(1)','https://user:password@example.com/callback','https://example.com/callback#fragment']:
        assert env.client.post('/api/oauth/register',json={'redirect_uris':[uri]}).status_code==400


def test_consent_csrf_denial_permission_expansion_and_code_use(env):
    e=env;_,r=start(e);id=parse_qs(urlsplit(r.headers['location']).query)['request'][0]
    body={'scopes':SCOPES.split(),'max_per_job':5}
    assert e.client.post('/api/v1/agent/authorizations/'+id,headers={**headers(e),'Origin':'https://evil.example'},json=body).status_code==403
    assert e.client.post('/api/v1/agent/authorizations/'+id,headers=headers(e),json={**body,'scopes':['admin:all']}).status_code==422
    denied=e.client.post('/api/v1/agent/authorizations/'+id,headers=headers(e),json={**body,'allow':False})
    assert 'error=access_denied' in denied.json()['redirect_to']
    assert e.client.get('/api/v1/agent/authorizations/'+id,headers=headers(e)).status_code==400
    _,_,data=approve(e)
    assert e.client.post('/api/oauth/token',data={**data,'code_verifier':'b'*64}).status_code==400
    assert e.client.post('/api/oauth/token',data=data).status_code==200
    assert e.client.post('/api/oauth/token',data=data).status_code==400
    assert all(len(r.token_hash)==64 for r in e.db.scalars(select(AgentCredential)))


def test_refresh_rotation_and_replay_revokes_grant(env):
    c=connect(env);data=dict(grant_type='refresh_token',client_id=c.exchange['client_id'],refresh_token=c.tokens['refresh_token'],resource=RESOURCE)
    r=env.client.post('/api/oauth/token',data=data);assert r.status_code==200 and r.json()['refresh_token']!=data['refresh_token']
    assert env.client.post('/api/oauth/token',data=data).status_code==400
    assert env.client.post('/api/mcp',headers={'Authorization':'Bearer '+r.json()['access_token']},json={}).status_code==401


def test_atomic_billing_idempotency_budgets_and_refunds(env):
    e=env;c=connect(e)
    first=value(submit(e,c));assert value(submit(e,c))['job_id']==first['job_id']
    for cls in [GenerationJob,AgentUsage,OutboxEvent,JobCharge]:assert e.db.scalar(select(func.count()).select_from(cls))==1
    assert submit(e,c,prompt='different')['isError']
    assert submit(e,c,'max-cost',max_cost=4)['isError']
    value(submit(e,c,'job-2'));value(submit(e,c,'job-3'))
    assert value(rpc(e,c,'get_balance'))=={'credits':85,'max_per_job':10}
    refund_job_charge(e.db,job_id=first['job_id'],reason='test');e.db.commit()
    assert value(rpc(e,c,'get_balance'))=={'credits':90,'max_per_job':10}
    for cls in [GenerationJob,AgentUsage,OutboxEvent,JobCharge]:assert e.db.scalar(select(func.count()).select_from(cls))==3


def test_scopes_and_price_caps_do_not_create_jobs(env):
    e=env;c=connect(e,scopes=['jobs:read'])
    assert value(rpc(e,c,'estimate_cost',{'model':'test-image'}))['credit_cost']==5
    assert submit(e,c)['isError'] and rpc(e,c,'get_balance')['isError']
    c=connect(e,single=4);assert submit(e,c)['isError']
    assert e.db.scalar(select(func.count()).select_from(GenerationJob))==0


def test_owner_isolation_limit_updates_revocation_and_password_reset(env):
    e=env;c=connect(e);id=c.grant.id;path='/api/v1/agent/connections/'+id
    assert e.client.get('/api/v1/agent/connections',headers=headers(e,True)).json()==[]
    assert e.client.put(path,headers=headers(e,True),json={'max_per_job':1}).status_code==401
    assert e.client.put(path,headers=headers(e),json={'max_per_job':-1}).status_code==422
    # Old clients can send the retired field; it must not constrain new caps.
    updated=e.client.put(path,headers=headers(e),json={'max_per_job':20,'daily_limit':0})
    assert updated.status_code==200 and updated.json()['max_per_job']==20
    assert 'daily_limit' not in updated.json() and 'used_today' not in updated.json()
    assert e.client.put(path,headers=headers(e),json={'max_per_job':0}).status_code==200
    assert submit(e,c)['isError']
    assert e.client.delete(path,headers=headers(e)).status_code==204
    assert e.client.post('/api/mcp',headers={'Authorization':'Bearer '+c.tokens['access_token']},json={}).status_code==401
    c=connect(e);e.user.password_hash=web_auth.hash_password('changed');e.db.commit()
    assert e.client.post('/api/mcp',headers={'Authorization':'Bearer '+c.tokens['access_token']},json={}).status_code==401


def test_edit_and_download_owner_expiry_and_revocation(env,monkeypatch):
    e=env;c=connect(e);id=value(submit(e,c))['job_id']
    row=e.db.get(GenerationJob,id);row.status=JobStatus.SUCCEEDED;row.media_state=MediaState.AVAILABLE;row.object_key='mock-result';row.media_content_type='image/png';row.media_expires_at=auth_sessions.utcnow()+timedelta(hours=1);e.db.commit()
    output=io.BytesIO();Image.new('RGB',(100,100),'white').save(output,format='PNG');image=output.getvalue();calls=[]
    class Storage:
        def iter_object(self,*_,**__):yield image
        def upload_reference_image(self,**kwargs):calls.append(kwargs);return 'reference-copy'
    monkeypatch.setattr(agent_tools,'MinioStorageService',Storage);monkeypatch.setattr(routes,'MinioStorageService',Storage)
    detail=value(rpc(e,c,'get_job',{'job_id':id}));url=detail['image_url']
    assert 'ep_access_' not in url and e.client.head(url).status_code==200
    edit=dict(source_job_id=id,prompt='Change blue',model='test-image',request_id='edit-1',max_cost=5)
    edited=value(rpc(e,c,'edit_image',edit));assert value(rpc(e,c,'edit_image',edit))['job_id']==edited['job_id'] and len(calls)==1
    row.user_id=e.other.id;e.db.commit();assert e.client.head(url).status_code==404
    assert rpc(e,c,'edit_image',{**edit,'request_id':'foreign'})['isError']
    row.user_id=e.user.id;row.media_expires_at=auth_sessions.utcnow()-timedelta(seconds=1);e.db.commit()
    assert e.client.head(url).status_code==404 and rpc(e,c,'edit_image',{**edit,'request_id':'expired'})['isError']
    assert value(rpc(e,c,'edit_image',edit))['job_id']==edited['job_id']
    row.media_expires_at=auth_sessions.utcnow()+timedelta(hours=1);e.db.commit()
    e.client.delete('/api/v1/agent/connections/'+c.grant.id,headers=headers(e));assert e.client.head(url).status_code==404


def test_document_links_and_skill_archive(env):
    r=env.client.get('/mcp/install.md');assert r.status_code==200 and RESOURCE in r.text and '{{' not in r.text
    source=env.client.get('/mcp/skill/SKILL.md').content
    with ZipFile(io.BytesIO(env.client.get('/mcp/easy-painter-skill.zip').content)) as z:
        assert z.namelist()==['easy-painter/SKILL.md'] and z.read('easy-painter/SKILL.md')==source
    assert 'get_job' in env.client.get('/llms-full.txt').text


def test_transport_origin_validation_and_missing_scope(env):
    c=connect(env)
    r=env.client.post('/api/mcp',headers={'Authorization':'Bearer '+c.tokens['access_token'],'Origin':'https://evil.example','Accept':'application/json, text/event-stream'},json={'jsonrpc':'2.0','id':1,'method':'tools/list'})
    assert r.status_code==403
    assert rpc(env,c,'generate_image',{'prompt':'test','model':'test-image','request_id':'negative','max_cost':-1})['isError']


def test_quote_change_balance_and_rollback_leave_no_usage(env,monkeypatch):
    e=env;c=connect(e)
    assert value(rpc(e,c,'estimate_cost',{'model':'test-image'}))['credit_cost']==5
    expensive=[{**MODELS[0],'credit_cost':6}]
    monkeypatch.setattr(routes,'_load_models',lambda *_:expensive)
    assert submit(e,c)['isError']
    assert e.db.scalar(select(func.count()).select_from(GenerationJob))==0
    monkeypatch.setattr(routes,'_load_models',lambda *_:MODELS)
    e.user.credits=0;e.db.commit()
    assert submit(e,c)['isError']
    for cls in [AgentUsage,GenerationJob,JobCharge,OutboxEvent]:assert e.db.scalar(select(func.count()).select_from(cls))==0


def test_expired_authorization_grant_and_changed_resource_fail_closed(env,monkeypatch):
    e=env;_,r=start(e);id=parse_qs(urlsplit(r.headers['location']).query)['request'][0]
    from app.models.agent import AgentAuthorization
    row=e.db.get(AgentAuthorization,id);row.expires_at=auth_sessions.utcnow()-timedelta(seconds=1);e.db.commit()
    assert e.client.get('/api/v1/agent/authorizations/'+id,headers=headers(e)).status_code==400
    c=connect(e)
    c.grant.expires_at=auth_sessions.utcnow()-timedelta(seconds=1);e.db.commit()
    assert e.client.post('/api/mcp',headers={'Authorization':'Bearer '+c.tokens['access_token']},json={}).status_code==401
    c=connect(e)
    e.settings.mcp_public_url='https://different.example/api/mcp'
    assert e.client.post('/api/mcp',headers={'Authorization':'Bearer '+c.tokens['access_token']},json={}).status_code==401
    e.settings.mcp_public_url=''
    assert e.client.get('/api/v1/agent/config').json()['enabled'] is False
    assert e.client.get('/.well-known/oauth-authorization-server').status_code==503


def test_request_keys_are_namespaced_per_connection_and_refresh_cannot_expand(env):
    e=env;a=connect(e);b=connect(e)
    assert value(submit(e,a))['job_id']!=value(submit(e,b))['job_id']
    bad=dict(grant_type='refresh_token',client_id=a.exchange['client_id'],refresh_token=a.tokens['refresh_token'],resource=RESOURCE,scope='admin:all')
    assert e.client.post('/api/oauth/token',data=bad).status_code==400
    assert e.client.post('/api/oauth/token',data={**bad,'scope':SCOPES}).status_code==200


def test_existing_connections_ignore_retired_daily_limit(env):
    e=env;c=connect(e,single=5)
    # Simulate an existing V12 connection, whose old daily limit was one image.
    c.grant.daily_limit=5;e.db.commit()
    for i in range(3):value(submit(e,c,f'legacy-{i}'))
    assert value(rpc(e,c,'get_balance'))=={'credits':85,'max_per_job':5}
    quote=value(rpc(e,c,'estimate_cost',{'model':'test-image'}))
    assert 'daily_remaining' not in quote
    row=e.client.get('/api/v1/agent/connections',headers=headers(e)).json()[0]
    assert 'daily_limit' not in row and 'used_today' not in row


def test_legacy_consent_field_is_ignored_and_not_exposed_in_schema(env):
    e=env;c=connect(e,single=5,daily=0)
    value(submit(e,c))
    assert 'daily_limit' not in agent_routes.Consent.model_json_schema()['properties']
    assert 'daily_limit' not in agent_routes.Limits.model_json_schema()['properties']


def test_web_api_and_mcp_share_balance_without_daily_spending_cap(env):
    e=env;c=connect(e,single=5)
    # Spend across both entrypoints beyond the old connection daily limit.
    for i in range(10):
        response=e.client.post('/api/v1/jobs',headers={**headers(e),'Idempotency-Key':f'web-{i}'},
                               json={'prompt':'A workflow','model':'test-image','size':'auto'})
        assert response.status_code==202,response.text
        value(submit(e,c,f'agent-{i}'))
    assert value(rpc(e,c,'get_balance'))['credits']==0
    rejected=e.client.post('/api/v1/jobs',headers=headers(e),json={'prompt':'A workflow','model':'test-image','size':'auto'})
    assert rejected.status_code==402,rejected.text
    assert '402' in str(submit(e,c,'empty-balance'))
    assert value(submit(e,c,'agent-9'))['job_id']
    for cls in [GenerationJob,JobCharge,OutboxEvent]:assert e.db.scalar(select(func.count()).select_from(cls))==20
    assert e.db.scalar(select(func.count()).select_from(AgentUsage))==10


class BurstRedis:
    """Deterministic expiring counters for the real generation flood guard."""
    def __init__(self):
        self.now=0;self.values={};self.deadlines={}

    def incr(self,key):
        if self.deadlines.get(key,float('inf')) <= self.now:self.values.pop(key,None)
        self.values[key]=self.values.get(key,0)+1
        return self.values[key]

    def expire(self,key,seconds):self.deadlines[key]=self.now+seconds


def test_generation_accepts_more_than_twelve_requests_in_a_minute(env,monkeypatch):
    from app.services.rate_limit import GenerationRateLimiter
    e=env;redis=BurstRedis();c=connect(e,single=5)
    monkeypatch.setattr(routes,'GenerationRateLimiter',GenerationRateLimiter)
    monkeypatch.setattr(mcp_server,'get_redis',lambda:redis)
    for i in range(13):value(submit(e,c,f'normal-batch-{i}'))
    assert value(rpc(e,c,'get_balance'))['credits']==35
    assert e.db.scalar(select(func.count()).select_from(GenerationJob))==13


def test_generation_flood_refusal_is_shared_by_web_mcp_and_recovers_in_one_second(env,monkeypatch):
    from app.services.rate_limit import GenerationRateLimiter
    e=env;redis=BurstRedis();c=connect(e,single=5)
    e.settings.generation_abuse_burst_limit=2
    monkeypatch.setattr(routes,'GenerationRateLimiter',GenerationRateLimiter)
    monkeypatch.setattr(mcp_server,'get_redis',lambda:redis)
    e.client.app.dependency_overrides[get_redis]=lambda:redis
    payload={'prompt':'A workflow','model':'test-image','size':'auto'}
    assert e.client.post('/api/v1/jobs',headers=headers(e),json=payload).status_code==202
    original=value(submit(e,c,'second'))
    refused=e.client.post('/api/v1/jobs',headers=headers(e),json=payload)
    assert refused.status_code==429 and refused.headers['retry-after']=='1'
    assert '429' in str(submit(e,c,'flood'))
    assert value(submit(e,c,'second'))['job_id']==original['job_id']
    assert value(rpc(e,c,'get_balance'))['credits']==90
    for cls in [GenerationJob,JobCharge,OutboxEvent]:assert e.db.scalar(select(func.count()).select_from(cls))==2
    redis.now=1.01
    assert e.client.post('/api/v1/jobs',headers=headers(e),json=payload).status_code==202
    assert value(rpc(e,c,'get_balance'))['credits']==85
