DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM users WHERE credits < 0) THEN
        RAISE EXCEPTION 'Cannot enable credit ledger: users with negative balances exist';
    END IF;
END $$;

ALTER TABLE users
    ADD CONSTRAINT ck_users_credits_nonnegative CHECK (credits >= 0);

ALTER TABLE generation_jobs
    ADD COLUMN model_label_snapshot VARCHAR(256),
    ADD COLUMN provider_id_snapshot VARCHAR(36),
    ADD COLUMN provider_name_snapshot VARCHAR(128),
    ADD COLUMN credit_cost_snapshot INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN idempotency_key VARCHAR(128),
    ADD COLUMN request_fingerprint VARCHAR(64),
    ADD COLUMN execution_token VARCHAR(128),
    ADD COLUMN lease_expires_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE generation_jobs
    ADD CONSTRAINT uq_generation_job_user_idempotency UNIQUE (user_id, idempotency_key);

CREATE INDEX ix_generation_jobs_lease_expires_at ON generation_jobs (lease_expires_at);

ALTER TABLE credit_transactions
    ADD COLUMN transaction_type VARCHAR(32) NOT NULL DEFAULT 'reconciliation',
    ADD COLUMN job_id VARCHAR(36),
    ADD COLUMN related_transaction_id VARCHAR(36),
    ADD COLUMN idempotency_key VARCHAR(160),
    ADD COLUMN details JSON;

ALTER TABLE credit_transactions
    ADD CONSTRAINT ck_credit_transaction_type CHECK (
        transaction_type IN (
            'opening_balance', 'redeem', 'job_reserve', 'job_refund', 'admin_adjust', 'reconciliation'
        )
    );

CREATE INDEX ix_credit_transactions_transaction_type ON credit_transactions (transaction_type);
CREATE INDEX ix_credit_transactions_job_id ON credit_transactions (job_id);
CREATE UNIQUE INDEX uq_credit_transactions_idempotency_key
    ON credit_transactions (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE job_charges (
    id VARCHAR(36) PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL UNIQUE,
    user_id VARCHAR(36) NOT NULL REFERENCES users (id),
    amount INTEGER NOT NULL CHECK (amount > 0),
    status VARCHAR(16) NOT NULL,
    reserve_transaction_id VARCHAR(36) NOT NULL UNIQUE,
    refund_transaction_id VARCHAR(36) UNIQUE,
    model_label VARCHAR(256) NOT NULL,
    provider_name VARCHAR(128),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    settled_at TIMESTAMP WITH TIME ZONE,
    refunded_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT ck_job_charge_status CHECK (status IN ('reserved', 'settled', 'refunded'))
);

CREATE INDEX ix_job_charges_job_id ON job_charges (job_id);
CREATE INDEX ix_job_charges_user_id ON job_charges (user_id);
CREATE INDEX ix_job_charges_status ON job_charges (status);

CREATE TABLE outbox_events (
    id VARCHAR(36) PRIMARY KEY,
    event_type VARCHAR(64) NOT NULL,
    aggregate_id VARCHAR(36) NOT NULL,
    payload JSON NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMP WITH TIME ZONE NOT NULL,
    published_at TIMESTAMP WITH TIME ZONE,
    last_error TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT ck_outbox_event_status CHECK (status IN ('pending', 'published', 'discarded')),
    CONSTRAINT uq_outbox_event_type_aggregate UNIQUE (event_type, aggregate_id)
);

CREATE INDEX ix_outbox_events_event_type ON outbox_events (event_type);
CREATE INDEX ix_outbox_events_aggregate_id ON outbox_events (aggregate_id);
CREATE INDEX ix_outbox_events_status ON outbox_events (status);
CREATE INDEX ix_outbox_events_available_at ON outbox_events (available_at);
