#!/usr/bin/env python3
"""Wire-level SDK check against ONLY scripts/preview-mcp.py on localhost.
Run from backend: uv run python ../scripts/check-mcp-preview.py
Creates temporary fake-credit connections/jobs; never contacts a real upstream.
"""
import asyncio
import base64
import hashlib
import json
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
import httpx
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

BASE='http://127.0.0.1:5176'
RESOURCE=BASE+'/api/mcp'


def data(result):
    d=result.model_dump(mode='json',by_alias=True)
    assert not d.get('isError'),d
    return d.get('structuredContent') or json.loads(next(c['text'] for c in d['content'] if c['type']=='text'))


async def main():
    # A hardcoded loopback target and mock-only account make accidental production
    # use impossible. Abort unless the expected isolated model is present.
    with httpx.Client(base_url=BASE,headers={'X-Session-Request':'1'}) as web:
        meta=web.get('/api/v1/meta/public').json()
        assert meta['models'][0]['id']=='mock-image','Expected isolated MCP preview'
        login=web.post('/api/v1/auth/login',json={'username':'demo','password':'Painter123!'})
        login.raise_for_status();headers={'Authorization':'Bearer '+login.json()['access_token'],'X-Session-Request':'1'}
        client=web.post('/api/oauth/register',json={'client_name':'SDK wire smoke','redirect_uris':[BASE+'/mcp/callback']}).json()
        verifier=uuid4().hex+uuid4().hex
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        args=dict(client_id=client['client_id'],redirect_uri=BASE+'/mcp/callback',response_type='code',code_challenge=challenge,code_challenge_method='S256',resource=RESOURCE,state=uuid4().hex)
        requested=web.get('/api/oauth/authorize',params=args,follow_redirects=False)
        assert requested.status_code == 303
        id=parse_qs(urlsplit(requested.headers['location']).query)['request'][0]
        approved=web.post('/api/v1/agent/authorizations/'+id,headers=headers,json={'allow':True,'scopes':['account:read','jobs:read','jobs:create'],'max_per_job':5,'daily_limit':10,'days':7})
        approved.raise_for_status();query=parse_qs(urlsplit(approved.json()['redirect_to']).query)
        assert query['state']==[args['state']]
        tokens=web.post('/api/oauth/token',data=dict(grant_type='authorization_code',code=query['code'][0],client_id=client['client_id'],redirect_uri=args['redirect_uri'],code_verifier=verifier,resource=RESOURCE))
        tokens.raise_for_status();access=tokens.json()['access_token']
        async with httpx2.AsyncClient(headers={'Authorization':'Bearer '+access},timeout=30) as http:
            async with Client(streamable_http_client(RESOURCE,http_client=http)) as mcp:
                tools=await mcp.list_tools();assert len(tools.tools)==6
                assert data(await mcp.call_tool('list_models'))['models'][0]['id']=='mock-image'
                assert data(await mcp.call_tool('estimate_cost',{'model':'mock-image'}))['credit_cost']==5
                call=dict(prompt='Mock workflow in gold',model='mock-image',size='auto',request_id=uuid4().hex,max_cost=5)
                first=data(await mcp.call_tool('generate_image',call));replay=data(await mcp.call_tool('generate_image',call))
                assert first['job_id']==replay['job_id']
                job=None
                for _ in range(20):
                    job=data(await mcp.call_tool('get_job',{'job_id':first['job_id']}))
                    if job['status']=='succeeded':break
                    await asyncio.sleep(.5)
                assert job['status']=='succeeded',job
                assert web.get(job['image_url']).content.startswith(b'\x89PNG')
                edit=dict(prompt='Change to blue',source_job_id=job['job_id'],model='mock-image',size='auto',request_id=uuid4().hex,max_cost=5)
                edited=data(await mcp.call_tool('edit_image',edit))
                assert data(await mcp.call_tool('edit_image',edit))['job_id']==edited['job_id']
                rejected=await mcp.call_tool('generate_image',{**call,'request_id':uuid4().hex})
                assert rejected.model_dump(by_alias=True).get('isError')
                balance=data(await mcp.call_tool('get_balance'));assert balance['used_today']==10
                for _ in range(20):
                    final=data(await mcp.call_tool('get_job',{'job_id':edited['job_id']}))
                    if final['status']=='succeeded':break
                    await asyncio.sleep(.5)
                assert final['status']=='succeeded'
                grant=next(row for row in web.get('/api/v1/agent/connections',headers=headers).json() if row['label']=='SDK wire smoke' and row['active'])
                web.delete('/api/v1/agent/connections/'+grant['id'],headers=headers).raise_for_status()
                assert web.get(job['image_url']).status_code==404
        assert web.post('/api/mcp',headers={'Authorization':'Bearer '+access},json={}).status_code==401
    print(json.dumps({'sdk':'mcp 2.3.0','tools':6,'generate':'succeeded','edit':'succeeded','same_request_replay':'same job, no extra charge','daily_limit':'rejected third submission','revocation':'access and media denied'},ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
