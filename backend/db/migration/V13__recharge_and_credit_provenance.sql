-- Additive payment records; existing balances remain legacy, never inferred paid.
ALTER TABLE credit_transactions DROP CONSTRAINT ck_credit_transaction_type;
ALTER TABLE credit_transactions ADD CONSTRAINT ck_credit_transaction_type CHECK (
    transaction_type IN ('opening_balance', 'redeem', 'recharge', 'job_reserve', 'job_refund', 'admin_adjust', 'reconciliation')
);

CREATE TABLE recharge_packages (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(80) NOT NULL,
    price_fen INTEGER NOT NULL,
    paid_credits INTEGER NOT NULL,
    gift_credits INTEGER NOT NULL DEFAULT 0,
    is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_recharge_package_amounts CHECK (price_fen > 0 AND paid_credits > 0 AND gift_credits >= 0)
);
INSERT INTO recharge_packages (id, name, price_fen, paid_credits, gift_credits, is_enabled)
VALUES ('basic-100', '灵感丝线 100 丝', 1000, 100, 0, FALSE);

CREATE TABLE recharge_orders (
    id VARCHAR(32) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id),
    package_id VARCHAR(36) NOT NULL REFERENCES recharge_packages(id),
    package_revision INTEGER NOT NULL,
    package_name VARCHAR(80) NOT NULL,
    amount_fen INTEGER NOT NULL,
    paid_credits INTEGER NOT NULL,
    gift_credits INTEGER NOT NULL,
    payment_method VARCHAR(16) NOT NULL,
    gateway_url VARCHAR(256) NOT NULL,
    merchant_id VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    provider_trade_no VARCHAR(64),
    idempotency_key VARCHAR(128) NOT NULL,
    credit_transaction_id VARCHAR(36) UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    paid_at TIMESTAMPTZ,
    last_checked_at TIMESTAMPTZ,
    last_check_error VARCHAR(64),
    CONSTRAINT uq_recharge_user_intent UNIQUE (user_id, idempotency_key),
    CONSTRAINT uq_recharge_provider_trade UNIQUE (gateway_url, merchant_id, provider_trade_no),
    CONSTRAINT ck_recharge_order_amounts CHECK (amount_fen > 0 AND paid_credits > 0 AND gift_credits >= 0),
    CONSTRAINT ck_recharge_order_status CHECK (status IN ('pending', 'paid'))
);
CREATE INDEX ix_recharge_orders_user_id ON recharge_orders(user_id);
CREATE INDEX ix_recharge_orders_status ON recharge_orders(status);
CREATE INDEX ix_recharge_orders_created_at ON recharge_orders(created_at);

CREATE TABLE credit_lots (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id),
    source_type VARCHAR(24) NOT NULL,
    source_id VARCHAR(160) NOT NULL UNIQUE,
    recharge_order_id VARCHAR(32) REFERENCES recharge_orders(id),
    total_credits INTEGER NOT NULL,
    remaining_credits INTEGER NOT NULL,
    amount_fen INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_credit_lot_balance CHECK (total_credits > 0 AND remaining_credits >= 0 AND remaining_credits <= total_credits),
    CONSTRAINT ck_credit_lot_cash_basis CHECK (amount_fen >= 0 AND (source_type = 'paid' OR amount_fen = 0))
);
CREATE INDEX ix_credit_lots_user_id ON credit_lots(user_id);
CREATE INDEX ix_credit_lots_recharge_order_id ON credit_lots(recharge_order_id);
INSERT INTO credit_lots (id, user_id, source_type, source_id, total_credits, remaining_credits, amount_fen)
SELECT md5('legacy-balance:' || id), id, 'legacy', 'legacy-balance:' || id, credits, credits, 0 FROM users WHERE credits > 0;

CREATE TABLE credit_allocations (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id),
    lot_id VARCHAR(36) NOT NULL REFERENCES credit_lots(id),
    transaction_id VARCHAR(36) NOT NULL,
    job_id VARCHAR(36),
    credits INTEGER NOT NULL,
    source_type_snapshot VARCHAR(24) NOT NULL,
    amount_fen_snapshot INTEGER NOT NULL,
    total_credits_snapshot INTEGER NOT NULL,
    reversed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_credit_allocation_transaction_lot UNIQUE (transaction_id, lot_id),
    CONSTRAINT ck_credit_allocation_amounts CHECK (credits > 0 AND amount_fen_snapshot >= 0 AND total_credits_snapshot > 0)
);
CREATE INDEX ix_credit_allocations_user_id ON credit_allocations(user_id);
CREATE INDEX ix_credit_allocations_lot_id ON credit_allocations(lot_id);
CREATE INDEX ix_credit_allocations_transaction_id ON credit_allocations(transaction_id);
CREATE INDEX ix_credit_allocations_job_id ON credit_allocations(job_id);
