ALTER TABLE model_configs
    ADD COLUMN credit_cost_by_size JSON NOT NULL DEFAULT '{}'::json;
