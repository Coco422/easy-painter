-- Immutable encrypted merchant configurations; legacy environment orders stay NULL.
CREATE TABLE payment_configurations (
    revision INTEGER PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    gateway_url VARCHAR(256) NOT NULL,
    merchant_id VARCHAR(64) NOT NULL,
    key_ciphertext TEXT NOT NULL,
    public_base_url VARCHAR(256) NOT NULL,
    payment_methods JSON NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_payment_configuration_revision CHECK (revision > 0)
);
ALTER TABLE recharge_orders ADD COLUMN config_revision INTEGER REFERENCES payment_configurations(revision);
