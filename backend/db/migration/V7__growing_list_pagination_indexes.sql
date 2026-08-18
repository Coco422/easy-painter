CREATE INDEX ix_users_created_at_id
    ON users (created_at DESC, id DESC);

CREATE INDEX ix_redemption_codes_created_at_id
    ON redemption_codes (created_at DESC, id DESC);

CREATE INDEX ix_redemption_codes_used_created_at_id
    ON redemption_codes (used_by, created_at DESC, id DESC);

CREATE INDEX ix_credit_transactions_created_at_id
    ON credit_transactions (created_at DESC, id DESC);

CREATE INDEX ix_credit_transactions_user_created_at_id
    ON credit_transactions (user_id, created_at DESC, id DESC);

CREATE INDEX ix_announcements_created_at_id
    ON announcements (created_at DESC, id DESC);

CREATE INDEX ix_reference_images_user_created_at_id
    ON reference_images (user_id, created_at DESC, id DESC);

CREATE INDEX ix_inspirations_available_created_at_id
    ON inspirations (created_at DESC, id DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX ix_generation_jobs_user_gallery_page
    ON generation_jobs (user_id, is_public, finished_at DESC, id DESC)
    WHERE deleted_at IS NULL AND object_key IS NOT NULL;

CREATE INDEX ix_generation_jobs_public_gallery_page
    ON generation_jobs (is_public, finished_at DESC, id DESC)
    WHERE deleted_at IS NULL AND object_key IS NOT NULL;
