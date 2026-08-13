CREATE TABLE user_groups (
    code VARCHAR(64) PRIMARY KEY,
    name VARCHAR(128) NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    billing_multiplier_bps INTEGER NOT NULL,
    generated_retention_hours INTEGER NOT NULL,
    reference_retention_hours INTEGER NOT NULL,
    max_reference_images INTEGER NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_user_groups_multiplier CHECK (
        billing_multiplier_bps >= 0 AND billing_multiplier_bps <= 100000
    ),
    CONSTRAINT ck_user_groups_generated_retention CHECK (
        generated_retention_hours >= 1 AND generated_retention_hours <= 87600
    ),
    CONSTRAINT ck_user_groups_reference_retention CHECK (
        reference_retention_hours >= 1 AND reference_retention_hours <= 87600
    ),
    CONSTRAINT ck_user_groups_reference_limit CHECK (
        max_reference_images >= 0 AND max_reference_images <= 10000
    )
);

CREATE UNIQUE INDEX uq_user_groups_single_default
    ON user_groups (is_default)
    WHERE is_default = TRUE;

INSERT INTO user_groups (
    code, name, description, billing_multiplier_bps,
    generated_retention_hours, reference_retention_hours,
    max_reference_images, is_enabled, is_default
) VALUES
    ('standard', '普通用户', '默认用户组', 10000, 24, 24, 3, TRUE, TRUE),
    ('vip', 'VIP', 'VIP 用户组', 5000, 720, 720, 50, TRUE, FALSE);

ALTER TABLE users
    ADD COLUMN group_code VARCHAR(64) NOT NULL DEFAULT 'standard';

ALTER TABLE users
    ADD CONSTRAINT fk_users_group_code
    FOREIGN KEY (group_code) REFERENCES user_groups (code);

CREATE INDEX ix_users_group_code ON users (group_code);

-- The rollout intentionally resets only current model configuration. Historical
-- job charges and immutable ledger rows keep their original amounts.
UPDATE model_configs SET credit_cost = 2;
ALTER TABLE model_configs ALTER COLUMN credit_cost SET DEFAULT 2;

ALTER TABLE generation_jobs
    ADD COLUMN group_code_snapshot VARCHAR(64),
    ADD COLUMN group_name_snapshot VARCHAR(128),
    ADD COLUMN base_credit_cost_snapshot INTEGER,
    ADD COLUMN billing_multiplier_bps_snapshot INTEGER,
    ADD COLUMN generated_retention_hours_snapshot INTEGER;

ALTER TABLE job_charges
    ADD COLUMN group_code_snapshot VARCHAR(64),
    ADD COLUMN group_name_snapshot VARCHAR(128),
    ADD COLUMN base_credit_cost_snapshot INTEGER,
    ADD COLUMN billing_multiplier_bps_snapshot INTEGER;

-- Free groups still create auditable charge/ledger snapshots with amount 0.
ALTER TABLE job_charges
    DROP CONSTRAINT job_charges_amount_check,
    ADD CONSTRAINT ck_job_charges_amount_nonnegative CHECK (amount >= 0);
