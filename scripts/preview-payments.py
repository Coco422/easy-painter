#!/usr/bin/env python3
"""Local payment UI fixture, never a production server or real payment gateway.

Build frontend first. From backend:
  PYTHONPATH=. uv run python ../scripts/preview-payments.py
Open http://127.0.0.1:5178/__fixture__/start to sign into a disposable account.
Only /__fixture__/paid/<order> simulates payment; no real gateway is contacted.
"""
from datetime import timedelta
from pathlib import Path
import base64
import json
import tempfile

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import uvicorn

from app.api.payment_routes import payment_router, admin_payment_router
from app.core.auth import require_admin, require_current_user
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.models.payment import RechargePackage
from app.models.user import User
from app.services import payments
from app.services.zpay import ZpayConfig, ZpayGateway


def main():
    root = Path(__file__).resolve().parents[1]
    dist = root/'frontend/dist'
    if not (dist/'index.html').exists():
        raise SystemExit('Run cd frontend && npm run build first.')
    folder = Path(tempfile.mkdtemp(prefix='easy-painter-payment-preview-'))
    engine = create_engine('sqlite:///' + str(folder/'fixture.db'), connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, autoflush=False, expire_on_commit=False)
    settings = Settings(_env_file=None, app_env='development', zpay_enabled=True,
        zpay_gateway_url='https://gateway.example.test', zpay_merchant_id='fixture', zpay_key='fixture-only-no-real-key-1234',
        zpay_public_base_url='http://127.0.0.1:5178')
    from cryptography.fernet import Fernet
    from pydantic import SecretStr
    settings.payment_config_encryption_key = SecretStr(Fernet.generate_key().decode())
    with factory() as db:
        user = User(username='preview_user', display_name='本地预览账号', email='preview@example.test', password_hash='fixture', credits=20)
        db.add(user)
        db.add_all([
            RechargePackage(id='basic-100', name='灵感丝线 100 丝', price_fen=1000, paid_credits=100, gift_credits=0, is_enabled=True),
            RechargePackage(id='plus-500', name='灵感丝线 500 丝', price_fen=5000, paid_credits=500, gift_credits=30, is_enabled=True, sort_order=1),
            RechargePackage(id='studio-1000', name='灵感丝线 1000 丝', price_fen=10000, paid_credits=1000, gift_credits=100, is_enabled=True, sort_order=2),
        ])
        db.commit(); user_id = user.id
    paid = set()
    gateway = ZpayGateway(ZpayConfig.from_settings(settings))
    def query(oid):
        from app.models.payment import RechargeOrder
        from app.services.zpay import format_fen
        with factory() as db:
            order = db.get(RechargeOrder, oid)
            return {'code': 1, 'status': int(oid in paid), 'pid': 'fixture', 'out_trade_no': oid,
                    'trade_no': 'FIXTURE-' + oid, 'money': format_fen(order.amount_fen), 'type': order.payment_method}
    gateway.query_order = query
    payments.get_gateway = lambda _: gateway
    app = FastAPI(docs_url=None, redoc_url=None)
    app.include_router(payment_router, prefix='/api/v1')
    app.include_router(admin_payment_router, prefix='/api/v1')
    def dependency():
        with factory() as db: yield db
    def current():
        with factory() as db: return db.get(User, user_id)
    app.dependency_overrides.update({get_db: dependency, get_settings: lambda: settings,
        require_current_user: current, require_admin: lambda: {'role': 'admin'}})

    @app.get('/__fixture__/start', response_class=HTMLResponse)
    def start():
        claims = {'sub': user_id, 'sid': 'fixture-session', 'typ': 'access', 'exp': int((payments.utcnow()+timedelta(hours=3)).timestamp())}
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
        token = 'fixture.' + payload + '.fixture'
        return '<!doctype html><meta charset="utf-8"><title>本地充值预览</title><script>localStorage.setItem("easy-painter:token",'+json.dumps(token)+');localStorage.setItem("easy-painter:admin-token","fixture-admin");location.replace("/recharge");</script>'

    @app.get('/__fixture__/paid/{oid}')
    def simulate_paid(oid: str):
        from app.models.payment import RechargeOrder
        with factory() as db:
            order = db.get(RechargeOrder, oid)
            if not order or order.user_id != user_id: raise HTTPException(404)
            paid.add(oid)
            payments.confirm_payment(db, order_id=oid, gateway=gateway)
        return RedirectResponse('/recharge/return?out_trade_no=' + oid)

    @app.get('/__fixture__/responsive', response_class=HTMLResponse)
    def responsive(width: int = 390):
        width = min(1280, max(320, width))
        return ('<!doctype html><meta charset="utf-8"><title>本地响应式预览</title>'
                '<style>body{margin:0;background:#ddd}iframe{display:block;border:0;height:100vh}</style>'
                f'<iframe title="个人中心窄屏预览" src="/profile" style="width:{width}px"></iframe>')

    @app.get('/api/v1/users/me')
    def me():
        with factory() as db:
            user = db.get(User, user_id)
            return {'id': user.id, 'username': user.username, 'display_name': user.display_name, 'email': user.email,
                    'credits': user.credits, 'is_public': False, 'created_at': user.created_at,
                    'group': {'code': 'vip', 'name': 'VIP', 'billing_multiplier_bps': 9000,
                              'generated_retention_hours': 720, 'reference_retention_hours': 720,
                              'max_reference_images': 100}}

    @app.get('/api/v1/users/me/credits')
    def credit_history():
        return {'items': [], 'total': 0, 'page': 1, 'page_size': 20}

    @app.get('/api/v1/meta/public')
    def meta():
        return {'site_name': '涂涂 · 预览', 'registration_enabled': True, 'email_delivery_enabled': False,
                'prompt_max_length': 4000, 'polling_interval_ms': 2000, 'example_prompts': [], 'models': []}

    @app.get('/api/v1/stats/public')
    def stats(): return {'today_images': 0, 'total_images': 0}

    @app.get('/api/v1/announcements')
    def announcements(): return []

    @app.get('/api/v1/admin/overview')
    def overview(): return {}

    app.mount('/assets', StaticFiles(directory=dist/'assets'))
    @app.get('/{path:path}')
    def spa(path: str):
        if path.startswith('api/'): raise HTTPException(404)
        return FileResponse(dist/'index.html')
    print('Disposable fixture only; open http://127.0.0.1:5178/__fixture__/start', flush=True)
    uvicorn.run(app, host='127.0.0.1', port=5178, access_log=False)


if __name__ == '__main__':
    main()
