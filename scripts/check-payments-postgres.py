#!/usr/bin/env python3
"""Isolated payment SQL + concurrency rehearsal; never reads a production URL.

From backend: PYTHONPATH=. uv run --with pgserver==0.1.4 python ../scripts/check-payments-postgres.py
Runs migration SQL in embedded PostgreSQL, not the Flyway container itself.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile

import pgserver
import psycopg
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.models.credit_transaction import CreditTransaction, CreditTransactionType
from app.models.payment import CreditAllocation, CreditLot, RechargeOrder, RechargePackage
from app.models.user import User
from app.schemas.payment import CreateRechargeRequest
from app.services.billing import reserve_job_credits, refund_job_charge
from app.services import payments
from app.services.zpay import ZpayConfig, ZpayGateway
from app.services import payment_config
from app.schemas.payment import PaymentConfigInput
from cryptography.fernet import Fernet


def main():
    root = Path(__file__).resolve().parents[1]
    pg = pgserver.get_server(Path(tempfile.mkdtemp(prefix='easy-painter-payment-pg-'))/'data', cleanup_mode='stop')
    engine = None
    try:
        uri = pg.get_uri()
        with psycopg.connect(uri, autocommit=True) as conn:
            for migration in sorted((root/'backend/db/migration').glob('V*__*.sql'), key=lambda p: int(p.name.split('__')[0][1:])):
                if migration.name.startswith('V2__'):
                    conn.execute("INSERT INTO users(id,username,password_hash,credits,created_at) VALUES('legacy-user','legacy_user','fixture',10,CURRENT_TIMESTAMP)")
                conn.execute(migration.read_text())
            version = conn.execute('SHOW server_version').fetchone()[0]
            assert conn.execute("SELECT total_credits,amount_fen,source_type FROM credit_lots WHERE user_id='legacy-user'").fetchone() == (10, 0, 'legacy')
            assert conn.execute("SELECT price_fen,paid_credits,is_enabled FROM recharge_packages WHERE id='basic-100'").fetchone() == (1000, 100, False)
        engine = create_engine(uri.replace('postgresql://', 'postgresql+psycopg://', 1), pool_size=12)
        factory = sessionmaker(engine, autoflush=False, expire_on_commit=False)
        settings = Settings(_env_file=None, zpay_enabled=True, zpay_gateway_url='https://gateway.example.test', zpay_public_base_url='https://app.example.test',
                            zpay_merchant_id='10001', zpay_key='fixture-secret-key-123456', payment_config_encryption_key=Fernet.generate_key().decode())
        gateway = ZpayGateway(ZpayConfig.from_settings(settings))
        gateway.query_order = lambda oid: {'code': 1, 'status': 1, 'pid': '10001', 'out_trade_no': oid, 'trade_no': 'PG-' + oid, 'money': '10.00', 'type': 'alipay'}
        with factory() as db:
            payment_config.save(db, settings, PaymentConfigInput(expected_revision=0, enabled=True,
                gateway_url=settings.zpay_gateway_url, merchant_id=settings.zpay_merchant_id,
                merchant_key=settings.zpay_key, public_base_url=settings.zpay_public_base_url))
            package = db.get(RechargePackage, 'basic-100'); package.is_enabled = True; package.gift_credits = 20; db.commit()
        def create(_):
            with factory() as db:
                return payments.create_order(db, user_id='legacy-user', body=CreateRechargeRequest(package_id='basic-100', package_revision=1, payment_method='alipay'),
                    intent='same-concurrent-intent', settings=settings).id
        with ThreadPoolExecutor(max_workers=12) as pool:
            order_ids = list(pool.map(create, range(12)))
        assert len(set(order_ids)) == 1
        with factory() as db:
            assert db.get(RechargeOrder, order_ids[0]).config_revision == 1
        def update_configuration(_):
            from fastapi import HTTPException
            with factory() as db:
                try:
                    payment_config.save(db, settings, PaymentConfigInput(expected_revision=1, enabled=False,
                        gateway_url=settings.zpay_gateway_url, merchant_id='20002', merchant_key='second-fixture-secret-123456',
                        public_base_url=settings.zpay_public_base_url))
                    return 200
                except HTTPException as exc:
                    return exc.status_code
        with ThreadPoolExecutor(max_workers=12) as pool:
            updates = list(pool.map(update_configuration, range(12)))
        assert updates.count(200) == 1 and updates.count(409) == 11
        with factory() as db:
            original = payments.gateway_for_order(db, settings, db.get(RechargeOrder, order_ids[0]))
            assert original.config.merchant_id == '10001' and original.config.key == settings.zpay_key.get_secret_value()
        def confirm(_):
            with factory() as db:
                return payments.confirm_payment(db, order_id=order_ids[0], gateway=gateway).status
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(confirm, range(12)))
        assert set(results) == {'paid'}
        with factory() as db:
            assert db.get(User, 'legacy-user').credits == 130
            assert db.scalar(select(func.count()).select_from(RechargeOrder)) == 1
            assert db.scalar(select(func.count()).select_from(CreditTransaction).where(CreditTransaction.transaction_type == CreditTransactionType.RECHARGE)) == 1
            assert db.scalar(select(func.count()).select_from(CreditLot)) == 3
            reserve_job_credits(db, job=SimpleNamespace(id='fixture-job'), user_id='legacy-user', amount=35, model_label='fixture', provider_name=None)
            db.commit()
            assert db.scalar(select(func.sum(CreditAllocation.credits)).where(CreditAllocation.source_type_snapshot == 'paid')) == 5
        def refund(_):
            with factory() as db:
                refund_job_charge(db, job_id='fixture-job', reason='fixture'); db.commit()
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(refund, range(12)))
        with factory() as db:
            assert db.get(User, 'legacy-user').credits == 130
            assert db.scalar(select(func.sum(CreditLot.remaining_credits))) == 130
            assert db.scalar(select(func.count()).select_from(CreditTransaction)) == 4
            assert db.scalar(select(func.sum(CreditTransaction.amount))) == 130
        print(json.dumps({'postgres': version, 'sql_migrations': 'V1–V14', 'legacy_cash_basis_fen': 0,
                          'configuration_updates': 12, 'accepted_updates': 1, 'stale_updates_rejected': 11, 'historical_credentials_preserved': True,
                          'concurrent_creations': 12, 'orders_created': 1, 'concurrent_confirmations': 12,
                          'recharge_credits_granted': 120, 'concurrent_job_refunds': 12, 'final_balance': 130}, ensure_ascii=False))
    finally:
        if engine is not None: engine.dispose()
        pg.cleanup()


if __name__ == '__main__':
    main()
