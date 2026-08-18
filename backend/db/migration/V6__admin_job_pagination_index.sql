CREATE INDEX ix_generation_jobs_created_at_id
    ON generation_jobs (created_at DESC, id DESC);
