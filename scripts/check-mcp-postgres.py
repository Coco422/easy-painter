#!/usr/bin/env python3
"""Isolated PostgreSQL SQL/concurrency check; never uses a live application DB.
Run from backend: PYTHONPATH=. uv run --with pgserver==0.1.4 python ../scripts/check-mcp-postgres.py
Executes V1–V12 SQL, not the Flyway container. Embedded PG is a test-only dependency.
"""
from pathlib import Path
import tempfile,json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
import pgserver,psycopg
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
from app.api import routes
from app.core.auth import hash_password
from app.core.config import Settings
from app.models.user import User
from app.models.agent import AgentClient,AgentGrant,AgentUsage
from app.models.generation_job import GenerationJob
from app.models.job_charge import JobCharge
from app.models.outbox_event import OutboxEvent
from app.models.credit_transaction import CreditTransaction,CreditTransactionType
from app.services import agent_auth,agent_tools
from app.services.auth_sessions import utcnow,password_digest

root=Path(__file__).resolve().parents[1]/'backend';temp=Path(tempfile.mkdtemp(prefix='easy-painter-mcp-pg-'))
pg=pgserver.get_server(temp/'data',cleanup_mode='stop')
try:
    uri=pg.get_uri()
    with psycopg.connect(uri,autocommit=True) as conn:
        version=conn.execute('SHOW server_version').fetchone()[0]
        for sql in sorted((root/'db/migration').glob('V*__*.sql'),key=lambda p:int(p.name.split('__')[0][1:])):
            conn.execute(sql.read_text())
        tables=conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE 'agent_%'").fetchone()[0]
        assert tables==5
    engine=create_engine(uri.replace('postgresql://','postgresql+psycopg://',1),pool_size=10)
    factory=sessionmaker(engine,expire_on_commit=False,autoflush=False)
    settings=Settings(_env_file=None,app_env='development',mcp_public_url='http://127.0.0.1:5176/api/mcp')
    agent_auth.get_settings=lambda:settings;agent_tools.get_settings=lambda:settings
    routes._load_models=lambda *_:[{'id':'pg-test','label':'PG Test','enabled':True,'supports_reference_image':True,'max_reference_images':5,'supported_sizes':[],'credit_cost':5}]
    routes.GenerationRateLimiter=lambda **_:SimpleNamespace(check=lambda _:SimpleNamespace(allowed=True,remaining=10))
    with factory() as db:
        user=User(username='pg_mcp_test',password_hash=hash_password('fixture-password'),credits=100)
        client=AgentClient(name='Concurrent test',redirect_uris=['http://127.0.0.1/callback'],created_at=utcnow())
        db.add_all([user,client]);db.flush()
        db.add(CreditTransaction(user_id=user.id,amount=100,balance_after=100,reason='fixture',transaction_type=CreditTransactionType.OPENING_BALANCE,idempotency_key='opening:'+user.id))
        grant=AgentGrant(user_id=user.id,client_id=client.id,resource=settings.mcp_public_url,label='Test',scopes=list(agent_auth.SCOPES),password_digest=password_digest(user),max_per_job=5,daily_limit=10,created_at=utcnow(),expires_at=utcnow()+timedelta(days=1))
        db.add(grant);db.commit();grant_id=grant.id;user_id=user.id
    def submit(key):
        with factory() as db:
            try:return agent_tools.submit(db,None,grant_id,prompt='A flow diagram',model='pg-test',size='auto',request_id=key,max_cost=5)
            except HTTPException as e:return {'error':e.status_code}
    with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(submit,[f'parallel-{i}' for i in range(8)]))
    assert sum('job_id' in r for r in results)==2,results
    assert sum(r.get('error')==403 for r in results)==6,results
    successful_key=next(f'parallel-{i}' for i,r in enumerate(results) if 'job_id' in r)
    with ThreadPoolExecutor(max_workers=8) as pool:replays=list(pool.map(submit,[successful_key]*8))
    assert len({r['job_id'] for r in replays})==1
    with factory() as db:
        counts={cls.__name__:db.scalar(select(func.count()).select_from(cls)) for cls in [GenerationJob,JobCharge,AgentUsage,OutboxEvent]}
        assert set(counts.values())=={2},counts
        assert db.get(User,user_id).credits==90
        assert agent_auth.daily_usage(db,grant_id)==10
    engine.dispose()
    print(json.dumps({'postgres':version,'sql_migrations':'V1–V12 executed in isolated empty database','agent_tables':tables,'parallel_submissions':8,'accepted':2,'budget_rejections':6,'concurrent_replays':8,'replay_jobs':1,'records':counts,'balance':90},ensure_ascii=False))
finally:
    pg.cleanup()
