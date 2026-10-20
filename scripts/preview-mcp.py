#!/usr/bin/env python3
"""Isolated loopback preview: real OAuth/MCP/billing, fake worker/storage.

Run from backend: uv run python ../scripts/preview-mcp.py
No production services, upstream requests, migrations or .env edits. SQLite fixture
schema is created ONLY by this development entrypoint, never API startup.
"""
import argparse
import asyncio
import io
import os
import sys
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port',type=int,default=18932)
parser.add_argument('--web-port',type=int,default=5176)
args=parser.parse_args()
fixture_dir=Path(tempfile.mkdtemp(prefix='easy-painter-mcp-preview-'))
backend=Path(__file__).resolve().parents[1]/'backend'
sys.path.insert(0,str(backend))
os.environ.update(APP_ENV='development',DATABASE_URL=f'sqlite:///{fixture_dir}/preview.db',
                  JWT_SECRET_KEY='local-mcp-preview-fixture-key-not-for-production',
                  MCP_PUBLIC_URL=f'http://127.0.0.1:{args.web_port}/api/mcp',
                  ALLOWED_ORIGINS_JSON=f'["http://127.0.0.1:{args.web_port}"]',
                  REGISTRATION_ENABLED='false', SITE_NAME='一丝绘画站 · MCP 本地预览')
from fastapi import FastAPI
from fastapi.responses import Response
from PIL import Image, ImageDraw
from sqlalchemy import select
from app.api import auth_router,user_router,announcement_router
from app.api import routes,agent_routes
from app.api.agent_content_routes import content_router
from app.core.auth import hash_password
from app.db.base import Base
from app.db.session import engine,SessionLocal
from app.models.credit_transaction import CreditTransaction,CreditTransactionType
from app.models.generation_job import GenerationJob,JobStatus
from app.models.announcement import Announcement
from app.services import mcp_server,agent_tools
from app.services.billing import settle_job_charge
from app.services.auth_sessions import utcnow
from app.services.redis_client import get_redis
from app.services.job_lifecycle import claim_generation_job,mark_generation_succeeded,mark_generation_failed
from app.services.upstream import GeneratedImageResult
from app.models.user import User
from datetime import timedelta

class MemoryRedis:
    def __init__(self): self.values={};self.deadlines={};self.lock=threading.Lock()
    def incr(self,key):
        with self.lock:
            if self.deadlines.get(key,1e100)<time.monotonic():self.values.pop(key,None)
            self.values[key]=self.values.get(key,0)+1
            return self.values[key]
    def expire(self,key,ttl):self.deadlines[key]=time.monotonic()+ttl
    def ping(self):return True
    def get(self,key):return self.values.get(key)
    def ttl(self,key):return 30
memory=MemoryRedis()
objects={}
class Storage:
    def open_object(self,key,**kwargs):
        stream=io.BytesIO(objects[key]);stream.release_conn=lambda:None
        return stream
    def iter_response(self,response):
        try:yield response.read()
        finally:response.close()
    def iter_object(self,key,**kwargs):yield objects[key]
    def upload_reference_image(self,**kwargs):
        key='reference/'+str(uuid4());objects[key]=kwargs['image_bytes'];return key
    def delete_reference_image(self,key):objects.pop(key,None)
routes.MinioStorageService=Storage;agent_tools.MinioStorageService=Storage
import app.services.storage as storage_module
storage_module.MinioStorageService=Storage
mcp_server.get_redis=lambda:memory
routes._load_models=lambda *_:[{'id':'mock-image','label':'Mock 绘图模型','enabled':True,'supports_reference_image':True,'max_reference_images':5,'supported_sizes':[],'credit_cost':5}]
Base.metadata.create_all(engine)
with SessionLocal() as db:
    for name in ['demo','demo2']:
        user=User(username=name,email=f'{name}@example.test',display_name='MCP 体验账号',password_hash=hash_password('Painter123!'),credits=100)
        db.add(user);db.flush()
        db.add(CreditTransaction(user_id=user.id,amount=100,balance_after=100,reason='preview opening',transaction_type=CreditTransactionType.OPENING_BALANCE,idempotency_key='opening:'+user.id))
    db.add(Announcement(title='MCP 本地预览',content='账号 demo / Painter123!；真实授权、限额与计费流程，假图工作器，不调用上游。',audience='all',level='info',enabled=True))
    db.commit()


def image(prompt):
    output=io.BytesIO();pic=Image.new('RGB',(1200,675),'#faf7ed');draw=ImageDraw.Draw(pic)
    draw.text((60,45),'EASY PAINTER / MCP PREVIEW',fill='#756134',font_size=32)
    draw.text((60,110),'A real tool call. A mock image.',fill='#28251e',font_size=40)
    accent='#4978a4' if ('blue' in prompt.lower() or '蓝' in prompt) else '#a88943'
    for index,label in enumerate(['COLLECT','PREPARE','ANALYZE']):
        x=70+index*390;draw.rounded_rectangle((x,240,x+280,460),radius=12,outline=accent,width=3)
        draw.text((x+30,315),label,fill=accent,font_size=30)
        if index<2:draw.line((x+300,350,x+365,350),fill=accent,width=4)
    draw.text((60,565),'MOCK PREVIEW - NO REAL MODEL OR PRODUCTION CREDITS',fill='#756134',font_size=24)
    pic.save(output,format='PNG');return output.getvalue()


async def worker():
    while True:
        await asyncio.sleep(.8)
        with SessionLocal() as db:
            ids=list(db.scalars(select(GenerationJob.id).where(GenerationJob.status==JobStatus.QUEUED)))
        for id in ids:
            with SessionLocal() as db:
                token=str(uuid4());job=claim_generation_job(db,job_id=id,execution_token=token,is_retry=False,lease_seconds=30)
                if not job:continue
                prompt=job.prompt
            await asyncio.sleep(1)
            with SessionLocal() as db:
                if '[fail]' in prompt:
                    mark_generation_failed(db,job_id=id,message='Mock 测试失败，已退款。',execution_token=token)
                else:
                    data=image(prompt);key='mock/'+id;objects[key]=data
                    mark_generation_succeeded(db,job_id=id,execution_token=token,result=GeneratedImageResult(data,'image/png',None,{'mock':True}),object_key=key,public_url='')

server,mcp_app=mcp_server.build_mcp_server()
@asynccontextmanager
async def lifespan(_):
    async with server.session_manager.run():
        task=asyncio.create_task(worker())
        try:yield
        finally:
            task.cancel()
            try:await task
            except asyncio.CancelledError:pass
app=FastAPI(lifespan=lifespan)
app.include_router(auth_router,prefix='/api/v1');app.include_router(user_router,prefix='/api/v1')
app.include_router(announcement_router,prefix='/api/v1');app.include_router(routes.router,prefix='/api/v1')
from app.api.artwork_routes import artwork_router
from app.api.artwork_media_routes import artwork_media_router
app.include_router(artwork_router,prefix='/api/v1');app.include_router(artwork_media_router,prefix='/api/v1')
app.include_router(agent_routes.agent_router,prefix='/api/v1/agent');app.include_router(agent_routes.oauth_router);app.include_router(content_router)
app.dependency_overrides[get_redis]=lambda:memory
app.mount('/api',mcp_app)
if __name__=='__main__':
    import uvicorn
    print(f'Isolated MCP preview: API :{args.port}, frontend :{args.web_port}; demo / Painter123!')
    uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False)
