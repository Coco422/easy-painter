from datetime import timedelta
from decimal import Decimal
from fractions import Fraction
from types import SimpleNamespace
from urllib.parse import urlencode

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.payment_routes import payment_router, admin_payment_router
from app.core.auth import require_current_user, require_admin
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.models.credit_transaction import CreditTransaction, CreditTransactionType
from app.models.payment import CreditAllocation, CreditLot, RechargeOrder, RechargePackage
from app.models.user import User
from app.schemas.payment import CreateRechargeRequest
from app.services import payments, zpay
from app.services.billing import reserve_job_credits, refund_job_charge, settle_job_charge, adjust_user_credits, redeem_credits
from app.models.redemption_code import RedemptionCode
from app.services.zpay import ZpayConfig, ZpayGateway, ZpayError, money_to_fen, sign_parameters, verify_notification
from cryptography.fernet import Fernet
from pydantic import SecretStr
from app.models.payment import PaymentConfiguration
from app.services import payment_config


@pytest.fixture
def env(monkeypatch):
    engine = create_engine('sqlite+pysqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, autoflush=False, expire_on_commit=False)
    settings = Settings(_env_file=None, zpay_enabled=True, zpay_merchant_id='10001', zpay_key='fixture-secret-key-1234567890',
                        zpay_gateway_url='https://gateway.example.test', zpay_public_base_url='https://app.example.test')
    with factory() as db:
        user = User(username='payer', password_hash='hash', credits=10)
        other = User(username='other', password_hash='hash')
        pack = RechargePackage(name='灵感丝线 100 丝', price_fen=1000, paid_credits=100, gift_credits=20, is_enabled=True)
        db.add_all([user, other, pack]); db.commit()
        uid, oid, pid = user.id, other.id, pack.id
    gateway = ZpayGateway(ZpayConfig.from_settings(settings))
    calls = []
    def query(order_id):
        calls.append(order_id)
        return {'code': 1, 'pid': '10001', 'out_trade_no': order_id, 'trade_no': 'platform-' + order_id,
                'type': 'alipay', 'money': '10.00', 'status': 1}
    monkeypatch.setattr(gateway, 'query_order', query)
    monkeypatch.setattr(payments, 'get_gateway', lambda _: gateway)
    app = FastAPI()
    app.include_router(payment_router, prefix='/api/v1'); app.include_router(admin_payment_router, prefix='/api/v1')
    def dependency():
        with factory() as db: yield db
    def current():
        with factory() as db: return db.get(User, uid)
    app.dependency_overrides.update({get_db: dependency, get_settings: lambda: settings, require_current_user: current, require_admin: lambda: {'role': 'admin'}})
    with TestClient(app) as client:
        yield SimpleNamespace(factory=factory, settings=settings, gateway=gateway, user_id=uid, other_id=oid,
                              package_id=pid, client=client, calls=calls)
    engine.dispose()


def create(env, key='intent-12345678'):
    response = env.client.post('/api/v1/recharge/orders', headers={'Idempotency-Key': key}, json={
        'package_id': env.package_id, 'package_revision': 1, 'payment_method': 'alipay'})
    assert response.status_code == 200, response.text
    return response.json()


def notification(env, order_id, **changes):
    params = {'pid': '10001', 'out_trade_no': order_id, 'trade_no': 'platform-' + order_id, 'type': 'alipay',
              'name': '灵感丝线 100 丝', 'money': '10.00', 'trade_status': 'TRADE_SUCCESS', 'sign_type': 'MD5'}
    params.update(changes)
    params['sign'] = sign_parameters(params, env.gateway.config.key)
    return params


def assert_not_paid(env, order_id):
    with env.factory() as db:
        assert db.get(User, env.user_id).credits == 10
        assert db.get(RechargeOrder, order_id).status == 'pending'
        assert db.scalar(select(func.count()).select_from(CreditTransaction).where(CreditTransaction.transaction_type == CreditTransactionType.RECHARGE)) == 0


@pytest.mark.parametrize('amount', ['0', '-1', 'NaN', 'Infinity', '1.001', '1e2', ' 1', '1 ', '01.00', '', 0, True, 1.1])
def test_money_rejects_noncanonical_or_nonpositive_amounts(amount):
    with pytest.raises(ZpayError): money_to_fen(amount)


@pytest.mark.parametrize(('value', 'fen'), [('0.01', 1), ('10', 1000), ('10.00', 1000), (Decimal('1.20'), 120), (2, 200)])
def test_money_uses_exact_decimal_fen(value, fen):
    assert money_to_fen(value) == fen


def test_ambiguous_canonicalization_is_rejected():
    # These two maps produce an identical raw MD5 input in the third-party SDK.
    with pytest.raises(ZpayError, match='ambiguous'):
        sign_parameters({'a': '1&b=2', 'c': '3'}, 'test-key')
    assert sign_parameters({'name': '中文 + %26', 'money': '1.00'}, 'key')


def test_verify_requires_supported_signature_and_constant_time_comparison(monkeypatch):
    params = {'money': '1.00', 'sign_type': 'MD5'}
    params['sign'] = sign_parameters(params, 'key')
    calls = []
    monkeypatch.setattr(zpay.hmac, 'compare_digest', lambda a,b: calls.append((a,b)) or a == b)
    verify_notification(params, 'key')
    assert len(calls) == 1
    with pytest.raises(ZpayError): verify_notification({**params, 'sign_type': 'RSA'}, 'key')


@pytest.mark.parametrize('url', ['http://gateway.example.test', 'https://user:pass@example.test', 'https://example.test/mapi.php', 'https://example.test?key=x', 'https://example.test:444'])
def test_gateway_configuration_is_https_root_only(env, url):
    settings = env.settings.model_copy(update={'zpay_gateway_url': url})
    with pytest.raises(ZpayError): ZpayConfig.from_settings(settings)
    assert env.gateway.config.key not in repr(env.gateway.config)


def test_disabled_checkout_and_packages_do_not_create_orders(env):
    env.settings.zpay_enabled = False
    response = env.client.post('/api/v1/recharge/orders', headers={'Idempotency-Key': 'intent-disabled'}, json={
        'package_id': env.package_id, 'package_revision': 1, 'payment_method': 'alipay'})
    assert response.status_code == 503
    with env.factory() as db: assert db.scalar(select(func.count()).select_from(RechargeOrder)) == 0


def test_order_idempotency_and_price_snapshot(env):
    first = create(env); again = create(env)
    assert first == again
    fields = first['fields']
    assert first['action'] == 'https://gateway.example.test/submit.php'
    assert fields['money'] == '10.00' and fields['out_trade_no'].isdigit() and len(fields['out_trade_no']) == 30
    assert env.gateway.config.key not in str(first)
    verify_notification(fields, env.gateway.config.key)
    with env.factory() as db:
        package = db.get(RechargePackage, env.package_id); package.price_fen = 3000; package.revision += 1; db.commit()
    assert create(env)['order']['amount_fen'] == 1000
    response = env.client.post('/api/v1/recharge/orders', headers={'Idempotency-Key': 'new-intent-12345'}, json={
        'package_id': env.package_id, 'package_revision': 1, 'payment_method': 'alipay'})
    assert response.status_code == 409
    with env.factory() as db: assert db.scalar(select(func.count()).select_from(RechargeOrder)) == 1


def test_successful_notification_credits_once_and_keeps_cash_provenance(env):
    order_id = create(env)['order']['id']; params = notification(env, order_id)
    for _ in range(3):
        response = env.client.get('/api/v1/payments/zpay/notify', params=params)
        assert response.status_code == 200 and response.text == 'success'
        assert response.headers['cache-control'] == 'no-store'
    assert env.calls == [order_id]
    with env.factory() as db:
        assert db.get(User, env.user_id).credits == 130
        order = db.get(RechargeOrder, order_id); assert order.status == 'paid'
        lots = db.scalars(select(CreditLot).where(CreditLot.recharge_order_id == order_id)).all()
        assert {(lot.source_type, lot.amount_fen, lot.total_credits) for lot in lots} == {('paid', 1000, 100), ('gift', 0, 20)}
        assert db.scalar(select(func.count()).select_from(CreditTransaction)) == 1


@pytest.mark.parametrize('changes', [{'pid': '999'}, {'money': '0.01'}, {'type': 'wxpay'}, {'trade_status': 'WAIT_BUYER_PAY'}, {'trade_no': ''}])
def test_even_validly_signed_wrong_payment_fields_are_rejected(env, changes):
    order_id = create(env)['order']['id']
    response = env.client.get('/api/v1/payments/zpay/notify', params=notification(env, order_id, **changes))
    assert response.status_code == 400
    assert_not_paid(env, order_id)


@pytest.mark.parametrize('changes', [{'pid': '999'}, {'money': '100.00'}, {'out_trade_no': 'another-order'}, {'type': 'wxpay'}, {'trade_no': 'other-trade'}, {'status': 0}, {'status': True}])
def test_active_query_is_authoritative_and_must_match_all_fields(env, monkeypatch, changes):
    order_id = create(env)['order']['id']; original = env.gateway.query_order(order_id)
    monkeypatch.setattr(env.gateway, 'query_order', lambda _: {**original, **changes})
    response = env.client.get('/api/v1/payments/zpay/notify', params=notification(env, order_id))
    assert response.status_code == 400
    assert_not_paid(env, order_id)


def test_duplicate_notify_parameters_and_bad_signature_are_rejected(env):
    order_id = create(env)['order']['id']; params = notification(env, order_id)
    assert env.client.get('/api/v1/payments/zpay/notify?' + urlencode(params) + '&money=0.01').status_code == 400
    assert env.client.post('/api/v1/payments/zpay/notify', content=urlencode(params) + '&pid=999', headers={'Content-Type': 'application/x-www-form-urlencoded'}).status_code == 400
    assert env.client.get('/api/v1/payments/zpay/notify', params={**params, 'sign': '0'*32}).status_code == 400
    assert env.client.post('/api/v1/payments/zpay/notify', json=params).status_code == 400
    assert env.client.get('/api/v1/payments/zpay/notify?junk=' + 'x'*17000).status_code == 400
    assert_not_paid(env, order_id)


def test_query_failure_never_grants_credits_and_is_retryable(env, monkeypatch):
    order_id = create(env)['order']['id']
    query = env.gateway.query_order
    monkeypatch.setattr(env.gateway, 'query_order', lambda _: (_ for _ in ()).throw(ZpayError('query_failed')))
    assert env.client.get('/api/v1/payments/zpay/notify', params=notification(env, order_id)).status_code == 400
    assert_not_paid(env, order_id)
    monkeypatch.setattr(env.gateway, 'query_order', query)
    assert env.client.get('/api/v1/payments/zpay/notify', params=notification(env, order_id)).text == 'success'


def test_form_callback_is_accepted_and_disable_does_not_lose_existing_payment(env):
    order_id = create(env)['order']['id']; env.settings.zpay_enabled = False
    response = env.client.post('/api/v1/payments/zpay/notify', content=urlencode(notification(env, order_id)), headers={'Content-Type': 'application/x-www-form-urlencoded'})
    assert response.text == 'success'


def test_browser_return_cannot_credit_and_orders_are_owner_scoped(env):
    order_id = create(env)['order']['id']
    assert env.client.get('/api/v1/recharge/orders/' + order_id + '?trade_status=TRADE_SUCCESS').status_code == 200
    assert_not_paid(env, order_id)
    env.client.app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=env.other_id)
    assert env.client.get('/api/v1/recharge/orders/' + order_id).status_code == 404
    assert env.client.post('/api/v1/recharge/orders/' + order_id + '/refresh').status_code == 404
    assert env.client.get('/api/v1/recharge/orders').json()['total'] == 0


def test_late_payment_and_reconciliation_are_idempotent(env):
    order_id = create(env)['order']['id']
    with env.factory() as db:
        order = db.get(RechargeOrder, order_id); order.expires_at = payments.utcnow() - timedelta(hours=2); db.commit()
    assert env.client.get('/api/v1/recharge/orders/' + order_id).json()['expired'] is True
    counts = payments.reconcile_recharge_orders(session_factory=env.factory, settings=env.settings)
    assert counts == {'checked': 1, 'paid': 1, 'failed': 0}
    assert payments.reconcile_recharge_orders(session_factory=env.factory, settings=env.settings)['checked'] == 0


def test_paid_credit_consumption_and_failed_refund_preserve_exact_lots(env):
    order_id = create(env)['order']['id']
    env.client.get('/api/v1/payments/zpay/notify', params=notification(env, order_id))
    with env.factory() as db:
        job = SimpleNamespace(id='job-source-test')
        reserve_job_credits(db, job=job, user_id=env.user_id, amount=35, model_label='test', provider_name=None)
        db.commit()
        allocations = db.scalars(select(CreditAllocation).where(CreditAllocation.job_id == job.id)).all()
        assert sum(a.credits for a in allocations) == 35
        assert sum(a.credits for a in allocations if a.source_type_snapshot == 'paid') == 5
        assert sum((Fraction(a.amount_fen_snapshot * a.credits, a.total_credits_snapshot) for a in allocations), Fraction()) == 50
        refund_job_charge(db, job_id=job.id, reason='test failure'); db.commit()
        assert db.get(User, env.user_id).credits == 130
        assert all(a.reversed_at for a in db.scalars(select(CreditAllocation)).all())
        assert db.scalar(select(func.sum(CreditLot.remaining_credits))) == 130
        refund_job_charge(db, job_id=job.id, reason='duplicate'); db.commit()
        assert db.scalar(select(func.sum(CreditLot.remaining_credits))) == 130


def test_successful_job_does_not_restore_lots_and_admin_adjustments_are_not_paid(env):
    order_id = create(env)['order']['id']; env.client.get('/api/v1/payments/zpay/notify', params=notification(env, order_id))
    with env.factory() as db:
        adjust_user_credits(db, user_id=env.user_id, requested_amount=7, reason='gift'); db.commit()
        reserve_job_credits(db, job=SimpleNamespace(id='settled-job'), user_id=env.user_id, amount=40, model_label='test', provider_name=None)
        db.commit()
        settle_job_charge(db, job_id='settled-job'); db.commit()
        refund_job_charge(db, job_id='settled-job', reason='duplicate'); db.commit()
        assert db.get(User, env.user_id).credits == 97
        assert db.scalar(select(func.sum(CreditLot.remaining_credits))) == 97
        adjust_user_credits(db, user_id=env.user_id, requested_amount=-3, reason='adjust'); db.commit()
        assert db.scalar(select(func.sum(CreditLot.remaining_credits))) == 94


def test_packages_are_configurable_versioned_and_admin_only(env):
    response = env.client.get('/api/v1/admin/recharge/config'); pack = response.json()['packages'][0]
    assert response.headers['cache-control'] == 'private, no-store'
    body = {**pack, 'expected_revision': pack['revision'], 'price_fen': 2000}
    response = env.client.put('/api/v1/admin/recharge/packages/' + pack['id'], json=body)
    assert response.status_code == 200 and response.json()['revision'] == 2
    assert env.client.put('/api/v1/admin/recharge/packages/' + pack['id'], json=body).status_code == 409
    assert env.client.post('/api/v1/admin/recharge/packages', json={'name': 'bad&money=1', 'price_fen': 1000, 'paid_credits': 100}).status_code == 422
    env.client.app.dependency_overrides.pop(require_admin)
    assert env.client.get('/api/v1/admin/recharge/config').status_code in (401, 403)


def test_gateway_never_follows_redirects_or_accepts_oversized_response(env, monkeypatch):
    real_client = httpx.Client
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={'location': 'https://evil.example.test'})
    monkeypatch.setattr(zpay.httpx, 'Client', lambda **kw: real_client(**kw, transport=httpx.MockTransport(handler)))
    gateway = ZpayGateway(env.gateway.config)
    with pytest.raises(ZpayError): gateway.query_order('order-1')
    assert len(requests) == 1
    def large(request): return httpx.Response(200, content=b'x' * 65537)
    monkeypatch.setattr(zpay.httpx, 'Client', lambda **kw: real_client(**kw, transport=httpx.MockTransport(large)))
    with pytest.raises(ZpayError): gateway.query_order('order-1')


def test_history_can_resume_same_checkout_and_reject_other_accounts(env):
    order = create(env)
    resumed = env.client.post('/api/v1/recharge/orders/' + order['order']['id'] + '/checkout')
    assert resumed.json() == order
    env.client.app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=env.other_id)
    assert env.client.post('/api/v1/recharge/orders/' + order['order']['id'] + '/checkout').status_code == 404


def test_failed_manual_query_is_throttled_without_granting_credits(env, monkeypatch):
    oid = create(env)['order']['id']
    monkeypatch.setattr(env.gateway, 'query_order', lambda _: (_ for _ in ()).throw(ZpayError('query_failed')))
    assert env.client.post('/api/v1/recharge/orders/' + oid + '/refresh').status_code == 503
    assert env.client.post('/api/v1/recharge/orders/' + oid + '/refresh').status_code == 429
    assert_not_paid(env, oid)


def test_successful_payment_rolls_back_if_credit_ledger_cannot_commit(env, monkeypatch):
    oid = create(env)['order']['id']
    from sqlalchemy.exc import IntegrityError
    with env.factory() as db:
        monkeypatch.setattr(db, 'commit', lambda: (_ for _ in ()).throw(IntegrityError('fixture', {}, Exception())))
        with pytest.raises(ZpayError, match='integrity'):
            payments.confirm_payment(db, order_id=oid, gateway=env.gateway)
    assert_not_paid(env, oid)
    with env.factory() as db:
        assert db.scalar(select(func.count()).select_from(CreditLot)) == 0


def test_duplicate_provider_trade_number_cannot_fund_a_second_order(env, monkeypatch):
    first = create(env)['order']['id']; env.client.get('/api/v1/payments/zpay/notify', params=notification(env, first))
    second = create(env, 'second-intent-1234')['order']['id']
    query = env.gateway.query_order(second)
    monkeypatch.setattr(env.gateway, 'query_order', lambda _: {**query, 'trade_no': 'platform-' + first})
    response = env.client.get('/api/v1/payments/zpay/notify', params=notification(env, second, trade_no='platform-' + first))
    assert response.status_code == 400
    with env.factory() as db:
        assert db.get(User, env.user_id).credits == 130
        assert db.get(RechargeOrder, second).status == 'pending'


def test_redaction_covers_payment_credentials(env, monkeypatch):
    import logging
    from app.core import logging as app_logging
    monkeypatch.setattr(app_logging, 'get_settings', lambda: env.settings)
    secret = env.settings.zpay_key.get_secret_value()
    record = logging.LogRecord('httpx', logging.INFO, 'fixture', 1, 'GET https://gateway.example.test/api.php?key=%s', (secret,), None)
    app_logging.RedactSecretsFilter().filter(record)
    assert secret not in record.getMessage() and '[REDACTED]' in record.getMessage()


def test_httpx_redaction_survives_handler_replacement(env, monkeypatch):
    import io
    import logging
    from app.core import logging as app_logging
    monkeypatch.setattr(app_logging, 'get_settings', lambda: env.settings)
    app_logging.configure_logging()
    logger = logging.getLogger('httpx')
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    original_handlers, original_propagate, original_level = logger.handlers[:], logger.propagate, logger.level
    try:
        logger.handlers = [handler]; logger.propagate = False; logger.setLevel(logging.INFO)
        logger.info('GET https://gateway.example.test/api.php?key=%s', env.gateway.config.key)
        assert env.gateway.config.key not in stream.getvalue() and '[REDACTED]' in stream.getvalue()
    finally:
        logger.handlers = original_handlers; logger.propagate = original_propagate; logger.setLevel(original_level)


def dashboard_body(env, **changes):
    if not env.settings.payment_config_encryption_key.get_secret_value():
        env.settings.payment_config_encryption_key = SecretStr(Fernet.generate_key().decode())
    return {
        'expected_revision': 0, 'enabled': True, 'gateway_url': env.settings.zpay_gateway_url,
        'merchant_id': env.settings.zpay_merchant_id, 'merchant_key': env.settings.zpay_key.get_secret_value(),
        'public_base_url': env.settings.zpay_public_base_url, 'payment_methods': ['alipay'], **changes,
    }


def test_dashboard_encrypts_key_and_never_returns_it(env):
    body = dashboard_body(env)
    result = env.client.put('/api/v1/admin/recharge/config', json=body)
    assert result.status_code == 200, result.text
    assert result.headers['cache-control'] == 'private, no-store'
    assert result.json()['key_configured'] and result.json()['encryption_ready']
    assert result.json()['revision'] == 1
    for response in (result, env.client.get('/api/v1/admin/recharge/config'), env.client.get('/api/v1/recharge/catalog')):
        assert body['merchant_key'] not in response.text
        assert 'key_ciphertext' not in response.text and 'merchant_key' not in response.text
    with env.factory() as db:
        saved = db.get(PaymentConfiguration, 1)
        assert body['merchant_key'] not in saved.key_ciphertext
        assert payment_config.effective(env.settings, saved).zpay_key.get_secret_value() == body['merchant_key']
    assert env.client.get('/api/v1/recharge/catalog').json()['payment_methods'] == ['alipay']


def test_dashboard_blank_key_preserves_secret_and_disable_still_confirms_orders(env):
    assert env.client.put('/api/v1/admin/recharge/config', json=dashboard_body(env)).status_code == 200
    oid = create(env)['order']['id']
    result = env.client.put('/api/v1/admin/recharge/config', json=dashboard_body(env, expected_revision=1, merchant_key='', enabled=False))
    assert result.status_code == 200
    assert not env.client.get('/api/v1/recharge/catalog').json()['enabled']
    assert env.client.post('/api/v1/recharge/orders', headers={'Idempotency-Key': 'new-disabled-intent'}, json={
        'package_id': env.package_id, 'package_revision': 1, 'payment_method': 'alipay'}).status_code == 503
    assert env.client.get('/api/v1/payments/zpay/notify', params=notification(env, oid)).text == 'success'
    with env.factory() as db:
        assert db.get(User, env.user_id).credits == 130
        assert db.get(RechargeOrder, oid).config_revision == 1
        rows = db.scalars(select(PaymentConfiguration)).all()
        assert len(rows) == 2 and rows[0].key_ciphertext != rows[1].key_ciphertext


def test_historical_order_uses_original_merchant_and_key_after_configuration_change(env, monkeypatch):
    monkeypatch.setattr(payments, 'get_gateway', lambda s: ZpayGateway(ZpayConfig.from_settings(s)))
    queried = []
    def query(self, oid):
        queried.append((self.config.merchant_id, self.config.key))
        return {'code': 1, 'status': 1, 'pid': self.config.merchant_id, 'out_trade_no': oid,
                'trade_no': 'platform-' + oid, 'money': '10.00', 'type': 'alipay'}
    monkeypatch.setattr(ZpayGateway, 'query_order', query)
    first_body = dashboard_body(env)
    assert env.client.put('/api/v1/admin/recharge/config', json=first_body).status_code == 200
    first = create(env)['order']['id']
    assert env.client.put('/api/v1/admin/recharge/config', json=dashboard_body(env, expected_revision=1,
        merchant_id='20002', merchant_key='replacement-fixture-secret-1234')).status_code == 200
    second = create(env, 'another-dashboard-order')['order']['id']
    assert env.client.post(f'/api/v1/recharge/orders/{first}/checkout').json()['fields']['pid'] == '10001'
    assert env.client.post(f'/api/v1/recharge/orders/{second}/checkout').json()['fields']['pid'] == '20002'
    env.settings.zpay_key = SecretStr('')  # Simulate a restart with no legacy env credentials.
    assert env.client.get('/api/v1/payments/zpay/notify', params=notification(env, first)).text == 'success'
    assert queried == [('10001', first_body['merchant_key'])]
    counts = payments.reconcile_recharge_orders(session_factory=env.factory, settings=env.settings)
    assert counts['paid'] == 1
    assert queried[-1] == ('20002', 'replacement-fixture-secret-1234')


def test_dashboard_rejects_stale_revision_and_requires_new_key_for_new_merchant(env):
    body = dashboard_body(env)
    assert env.client.put('/api/v1/admin/recharge/config', json=body).status_code == 200
    assert env.client.put('/api/v1/admin/recharge/config', json=body).status_code == 409
    assert env.client.put('/api/v1/admin/recharge/config', json={**body, 'expected_revision': 1,
        'merchant_key': '', 'merchant_id': '20002'}).status_code == 422
    with env.factory() as db:
        assert db.scalar(select(func.count()).select_from(PaymentConfiguration)) == 1


@pytest.mark.parametrize('master_key', ['', 'invalid-key'])
def test_dashboard_cannot_save_plaintext_without_a_valid_master_key(env, master_key):
    body = dashboard_body(env)
    env.settings.payment_config_encryption_key = SecretStr(master_key)
    assert not env.client.get('/api/v1/admin/recharge/config').json()['encryption_ready']
    response = env.client.put('/api/v1/admin/recharge/config', json=body)
    assert response.status_code == 503 and body['merchant_key'] not in response.text
    with env.factory() as db:
        assert db.scalar(select(func.count()).select_from(PaymentConfiguration)) == 0


@pytest.mark.parametrize('failure', ['ciphertext', 'wrong_master', 'metadata'])
def test_unreadable_or_swapped_configuration_fails_closed(env, failure):
    assert env.client.put('/api/v1/admin/recharge/config', json=dashboard_body(env)).status_code == 200
    oid = create(env)['order']['id']
    with env.factory() as db:
        row = db.get(PaymentConfiguration, 1)
        if failure == 'ciphertext': row.key_ciphertext = 'tampered'
        elif failure == 'metadata': row.merchant_id = 'different'
        else: env.settings.payment_config_encryption_key = SecretStr(Fernet.generate_key().decode())
        db.commit()
    assert env.client.get('/api/v1/admin/recharge/config').json()['configuration_error']
    assert not env.client.get('/api/v1/recharge/catalog').json()['enabled']
    assert env.client.get('/api/v1/payments/zpay/notify', params=notification(env, oid)).status_code == 400
    assert_not_paid(env, oid)


def test_dashboard_rejects_unopened_method_and_unauthenticated_writes(env):
    body = dashboard_body(env)
    assert env.client.put('/api/v1/admin/recharge/config', json=body).status_code == 200
    result = env.client.post('/api/v1/recharge/orders', headers={'Idempotency-Key': 'unopened-wxpay-intent'}, json={
        'package_id': env.package_id, 'package_revision': 1, 'payment_method': 'wxpay'})
    assert result.status_code == 422
    env.client.app.dependency_overrides.pop(require_admin)
    assert env.client.put('/api/v1/admin/recharge/config', json=body).status_code in (401, 403)


def test_dynamic_key_and_notification_signature_are_redacted(env, monkeypatch):
    import logging
    from app.core import logging as app_logging
    monkeypatch.setattr(app_logging, 'get_settings', lambda: env.settings)
    record = logging.LogRecord('httpx', logging.INFO, 'fixture', 1,
        'GET https://gateway.example.test/api.php?pid=1&key=dynamic-db-secret&sign=callback-signature HTTP/1.1', (), None)
    app_logging.RedactSecretsFilter().filter(record)
    assert 'dynamic-db-secret' not in record.getMessage() and 'callback-signature' not in record.getMessage()


def test_pending_payment_preserves_user_for_late_notifications(env):
    from app.api.admin_routes import admin_router
    env.client.app.include_router(admin_router, prefix='/api/v1')
    create(env)
    result = env.client.delete(f'/api/v1/admin/users/{env.user_id}')
    assert result.status_code == 409
    with env.factory() as db:
        assert db.get(User, env.user_id) is not None
