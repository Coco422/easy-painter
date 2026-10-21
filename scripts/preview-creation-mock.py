#!/usr/bin/env python3
"""Loopback-only creation preview. No upstream, production DB, or real credits.

Run: python3 scripts/preview-creation-mock.py
Then: cd frontend && VITE_API_PROXY_TARGET=http://127.0.0.1:18931 npm run dev -- --host 127.0.0.1 --port 5174
Requires Pillow for deterministic PNG fixtures. State lasts until this process exits.
"""
import argparse
import base64
import hashlib
import io
import json
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from PIL import Image, ImageDraw, ImageFont

PASSWORD = 'Painter123!'
ACCOUNTS = {'demo': '00000000-0000-4000-8000-000000000001', 'demo2': '00000000-0000-4000-8000-000000000002'}
MODELS = [dict(id='mock-image', label='Mock 绘图模型', enabled=True, supports_reference_image=True, max_reference_images=5, supported_sizes=['auto', '1280x720', '1024x1024'], base_credit_cost=5, credit_cost=5)]
JOBS, REFERENCES, TOKENS, IDEMPOTENCY = {}, {}, {}, {}
REQUESTS = []
CONTROL = {}
GENERATION_SECONDS = 1.7
LOCK = threading.RLock()


def now(): return datetime.now(timezone.utc).isoformat()
def expiry(): return (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()


def font(size):
    for name in ('/System/Library/Fonts/Supplemental/Arial.ttf', 'DejaVuSans.ttf'):
        try: return ImageFont.truetype(name, size)
        except OSError: pass
    return ImageFont.load_default()


def fake_image(prompt, number):
    """Draw a test fixture, not an AI-generated image."""
    accent = '#38739b' if any(word in prompt.lower() for word in ('蓝', 'blue')) else '#4c8765' if any(word in prompt.lower() for word in ('绿', 'green')) else '#b28b39'
    image = Image.new('RGB', (1200, 675), '#fbf9f3')
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((48, 36, 218, 68), radius=8, fill='#eee8d9')
    draw.text((63, 43), 'MOCK PREVIEW', fill='#78613a', font=font(16))
    draw.text((48, 95), 'RESEARCH WORKFLOW', fill='#29271e', font=font(38))
    draw.text((48, 150), 'A clear path from samples to insights', fill='#7c7565', font=font(20))
    labels = [('Collect', 'Gather samples'), ('Prepare', 'Process & organize'), ('Analyze', 'Interpret results')]
    for i, (title, subtitle) in enumerate(labels):
        x = 70 + i * 395
        draw.rounded_rectangle((x, 230, x + 270, 480), radius=20, fill='white', outline='#e5dece', width=2)
        draw.rounded_rectangle((x + 88, 265, x + 182, 355), radius=16, fill=accent)
        if i == 0:
            for offset in (0, 24, 48):
                draw.rounded_rectangle((x + 104 + offset, 282, x + 114 + offset, 338), radius=4, outline='white', width=3)
        elif i == 1:
            draw.line([(x + 121, 282), (x + 121, 306), (x + 104, 337), (x + 165, 337), (x + 147, 306), (x + 147, 282)], fill='white', width=4)
            draw.line((x + 116, 282, x + 152, 282), fill='white', width=4)
        else:
            for offset, height in ((0, 25), (21, 42), (42, 58)):
                draw.rectangle((x + 110 + offset, 338 - height, x + 121 + offset, 338), fill='white')
        draw.text((x + 28, 382), title, fill='#29271e', font=font(26))
        draw.text((x + 28, 425), subtitle, fill='#7c7565', font=font(18))
        if i < 2:
            draw.line((x + 292, 353, x + 361, 353), fill=accent, width=4)
            draw.polygon([(x + 361, 353), (x + 347, 344), (x + 347, 362)], fill=accent)
    draw.line((48, 550, 1152, 550), fill='#e5dece', width=2)
    draw.text((48, 580), 'Mock image - no real model or paid credits used', fill='#7c7565', font=font(18))
    draw.text((1050, 580), f'#{number:02d}', fill=accent, font=font(24))
    output = io.BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def public_job(job):
    result = {key: value for key, value in job.items() if not key.startswith('_')}
    age = time.monotonic() - job['_started']
    result['status'] = 'queued' if age < .5 else 'processing' if age < GENERATION_SECONDS else 'succeeded'
    if result['status'] == 'succeeded':
        result.update(image_url=f"/api/v1/mock-media/{job['job_id']}.png", thumbnail_url=f"/api/v1/mock-media/{job['job_id']}.png", billing_status='settled', finished_at=job['created_at'], media_state='available')
    return result


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def send(self, payload, status=200, content_type='application/json'):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def owner(self): return TOKENS.get(self.headers.get('Authorization', '').removeprefix('Bearer '))
    def json_body(self): return json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))) or b'{}')

    def do_GET(self):
        with LOCK:
            path = urlsplit(self.path).path
            owner = self.owner()
            if path == '/__mock/metrics': return self.send(dict(jobs=len(JOBS), uploads=len(REFERENCES), requests=REQUESTS))
            if path == '/api/v1/meta/public': return self.send(dict(site_name='一丝绘画站 · Mock 预览', registration_enabled=False, email_delivery_enabled=False, prompt_max_length=4000, polling_interval_ms=700, example_prompts=[], models=MODELS))
            if path == '/api/v1/stats/public': return self.send(dict(today_images=len(JOBS), total_images=len(JOBS)))
            if path == '/api/v1/announcements': return self.send([dict(id='mock-preview', title='本地 Mock 预览', content='账号 demo / Painter123!；只生成假图，不调用真实模型，不消耗真实积分。', level='info', audience='all', enabled=True)])
            if not owner: return self.send(dict(detail='请先使用 Mock 账号登录。'), 401)
            if path == '/api/v1/users/me': return self.send(dict(id=owner, username=next(name for name, value in ACCOUNTS.items() if value == owner), display_name='Mock 体验账号', email=None, is_public=False, credits=1000 - 5 * sum(job['_owner'] == owner for job in JOBS.values()), created_at=now()))
            if path == '/api/v1/canvas/capabilities': return self.send(dict(can_write=False, max_projects=0, max_bytes=0, used_bytes=0))
            if path == '/api/v1/canvas/projects': return self.send([])
            if path == '/api/v1/jobs/active': return self.send([public_job(job) for job in JOBS.values() if job['_owner'] == owner and public_job(job)['status'] in ('queued', 'processing')])
            if path == '/api/v1/reference-images': return self.send(dict(items=[{key: value for key, value in ref.items() if not key.startswith('_')} for ref in REFERENCES.values() if ref['_owner'] == owner], total=sum(ref['_owner'] == owner for ref in REFERENCES.values()), page=1, page_size=20))
            if path.startswith('/api/v1/reference-images/') and path.endswith('/file'):
                ref = REFERENCES.get(path.split('/')[-2])
                return self.send(ref['_bytes'], content_type=ref['content_type']) if ref and ref['_owner'] == owner else self.send(dict(detail='参考图不存在。'), 404)
            if path.startswith('/api/v1/mock-media/'):
                job = JOBS.get(path.rsplit('/', 1)[-1].removesuffix('.png'))
                return self.send(job['_png'], content_type='image/png') if job and job['_owner'] == owner else self.send(dict(detail='图片不存在。'), 404)
            if path.startswith('/api/v1/jobs/'):
                job = JOBS.get(path.rsplit('/', 1)[-1])
                return self.send(public_job(job)) if job and job['_owner'] == owner else self.send(dict(detail='任务不存在。'), 404)
            if path.startswith('/api/v1/artworks/job/'):
                job = JOBS.get(path.rsplit('/', 1)[-1])
                if not job or job['_owner'] != owner: return self.send(dict(detail='作品不存在。'), 404)
                j = public_job(job)
                return self.send(dict(kind='job', id=j['job_id'], job_id=j['job_id'], inspiration_id=None, favorite_id=None, title='Mock 实验工作流', prompt=j['prompt'], revised_prompt=None, is_prompt_public=False, can_view_prompt=True, username='demo', is_owner=True, is_in_gallery=False, gallery_visible=False, is_favorite=False, tags=[], status=j['status'], model=j['model'], size=j['size'], aspect_ratio='16:9', created_at=j['created_at'], finished_at=j['finished_at'], credit_cost=5, billing_status=j['billing_status'], error_message=None, media_state=j['media_state'], media_expires_at=j['media_expires_at'], original_expires_at=j['media_expires_at'], retention_kind='temporary', image_url=j['image_url'], thumbnail_url=j['thumbnail_url'], submission_status='none', review_reason=None))
            if 'inspiration' in path: return self.send(dict(items=[], page=1, page_size=20, total=0, tags=[]))
            return self.send(dict(detail='Mock 未实现此接口。'), 404)

    def do_POST(self):
        with LOCK:
            path = urlsplit(self.path).path
            if path == '/api/v1/reference-images':
                owner = self.owner()
                if not owner: return self.send(dict(detail='请先登录。'), 401)
                length = int(self.headers.get('Content-Length', '0'))
                if length > 13 * 1024 * 1024: return self.send(dict(detail='图片过大。'), 413)
                mime = BytesParser(policy=default).parsebytes(b'Content-Type: ' + self.headers.get('Content-Type', '').encode() + b'\r\nMIME-Version: 1.0\r\n\r\n' + self.rfile.read(length))
                part = next((part for part in mime.iter_parts() if part.get_filename()), None)
                if not part: return self.send(dict(detail='缺少图片。'), 422)
                data = part.get_payload(decode=True)
                rid = hashlib.sha256(owner.encode() + data).hexdigest()
                ref = REFERENCES.setdefault(rid, dict(id=rid, filename=part.get_filename(), content_type=part.get_content_type(), used_count=0, created_at=now(), last_used_at=None, media_state='available', media_expires_at=expiry(), thumbnail_url=f'/api/v1/reference-images/{rid}/file', _owner=owner, _bytes=data))
                return self.send({key: value for key, value in ref.items() if not key.startswith('_')})
            body = self.json_body()
            if path == '/__mock/control': CONTROL.update(body); return self.send(dict(ok=True))
            if path == '/api/v1/auth/login':
                owner = ACCOUNTS.get(body.get('username'))
                if not owner or body.get('password') != PASSWORD: return self.send(dict(detail='Mock 账号为 demo，密码 Painter123!。'), 401)
                payload = base64.urlsafe_b64encode(json.dumps(dict(sub=owner, sid=str(uuid.uuid4()), typ='access', exp=int(time.time()) + 86400)).encode()).decode().rstrip('=')
                token = 'eyJhbGciOiJub25lIn0.' + payload + '.mock-only'
                TOKENS[token] = owner
                return self.send(dict(access_token=token, token_type='bearer'))
            if path == '/api/v1/auth/logout': return self.send({})
            if not self.owner(): return self.send(dict(detail='请先登录。'), 401)
            if path == '/api/v1/jobs':
                owner, key = self.owner(), self.headers.get('Idempotency-Key')
                if not key: return self.send(dict(detail='缺少请求 ID。'), 400)
                previous = IDEMPOTENCY.get((owner, key))
                if previous:
                    if previous[0] != body: return self.send(dict(detail='相同请求 ID 的参数不一致。'), 409)
                    return self.send(previous[1])
                if not isinstance(body.get('prompt'), str) or not body['prompt'].strip() or len(body['prompt']) > 4000: return self.send(dict(detail='请填写不超过 4000 字的提示词。'), 422)
                if any(REFERENCES.get(rid, {}).get('_owner') != owner for rid in body.get('reference_image_ids', [])): return self.send(dict(detail='参考图不可访问。'), 404)
                jid = str(uuid.uuid4())
                JOBS[jid] = dict(job_id=jid, status='queued', image_url=None, thumbnail_url=None, prompt=body['prompt'], revised_prompt=None, model='mock-image', model_label='Mock 绘图模型', provider_name='本地 Mock', size=body.get('size', 'auto'), aspect_ratio='16:9', error_message=None, credit_cost=5, billing_status='reserved', refunded_at=None, created_at=now(), finished_at=None, media_state='none', media_expires_at=expiry(), _owner=owner, _started=time.monotonic(), _png=fake_image(body['prompt'], len(JOBS) + 1))
                response = dict(job_id=jid, status='queued', poll_url=f'/api/v1/jobs/{jid}', credit_cost=5, base_credit_cost=5, billing_multiplier_bps=10000, group_code='mock', group_name='Mock', balance_after=995, billing_status='reserved')
                IDEMPOTENCY[(owner, key)] = (body, response)
                REQUESTS.append(dict(job_id=jid, key=key, payload=body))
                if CONTROL.pop('unknown_next', False): return self.send(dict(detail='Mock 模拟响应丢失；任务已创建。'), 503)
                return self.send(response)
            return self.send(dict(detail='Mock 未实现此接口。'), 404)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=18931)
    parser.add_argument('--generation-seconds', type=float, default=1.7, help='Mock 生成等待秒数，可延长以观察趣话轮换')
    args = parser.parse_args()
    if not .5 < args.generation_seconds <= 300:
        parser.error('生成等待时间需大于 0.5 且不超过 300 秒。')
    GENERATION_SECONDS = args.generation_seconds
    print(f'Mock API: http://127.0.0.1:{args.port} | demo / {PASSWORD}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
