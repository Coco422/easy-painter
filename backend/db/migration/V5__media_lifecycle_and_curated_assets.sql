ALTER TABLE generation_jobs
    ADD COLUMN media_state VARCHAR(24) NOT NULL DEFAULT 'none',
    ADD COLUMN media_expires_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN media_size_bytes BIGINT,
    ADD COLUMN media_content_type VARCHAR(128),
    ADD COLUMN media_deleted_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE generation_jobs
    ADD CONSTRAINT ck_generation_jobs_media_state CHECK (
        media_state IN ('none', 'available', 'delete_pending', 'deleted')
    );

CREATE INDEX ix_generation_jobs_media_expires_at
    ON generation_jobs (media_expires_at);
CREATE INDEX ix_generation_jobs_media_state
    ON generation_jobs (media_state);
CREATE INDEX ix_generation_jobs_deleted_at
    ON generation_jobs (deleted_at);

UPDATE generation_jobs
SET media_state = 'available',
    media_expires_at = CURRENT_TIMESTAMP + INTERVAL '30 days'
WHERE status = 'SUCCEEDED' AND object_key IS NOT NULL;

ALTER TABLE reference_images
    ADD COLUMN group_code_snapshot VARCHAR(64),
    ADD COLUMN group_name_snapshot VARCHAR(128),
    ADD COLUMN retention_hours_snapshot INTEGER,
    ADD COLUMN media_state VARCHAR(24) NOT NULL DEFAULT 'available',
    ADD COLUMN media_expires_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN media_size_bytes BIGINT,
    ADD COLUMN media_deleted_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE reference_images
    ADD CONSTRAINT ck_reference_images_media_state CHECK (
        media_state IN ('available', 'delete_pending', 'deleted')
    );

UPDATE reference_images
SET media_expires_at = CURRENT_TIMESTAMP + INTERVAL '30 days';

CREATE INDEX ix_reference_images_media_expires_at
    ON reference_images (media_expires_at);
CREATE INDEX ix_reference_images_media_state
    ON reference_images (media_state);

ALTER TABLE inspirations
    ADD COLUMN media_state VARCHAR(24) NOT NULL DEFAULT 'available',
    ADD COLUMN media_size_bytes BIGINT,
    ADD COLUMN media_content_type VARCHAR(128),
    ADD COLUMN source_job_id VARCHAR(36),
    ADD COLUMN source_user_id VARCHAR(36),
    ADD COLUMN curated_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE inspirations
    ADD CONSTRAINT ck_inspirations_media_state CHECK (
        media_state IN ('available', 'delete_pending', 'deleted')
    );

CREATE INDEX ix_inspirations_media_state ON inspirations (media_state);
CREATE UNIQUE INDEX uq_inspirations_source_job_id
    ON inspirations (source_job_id)
    WHERE source_job_id IS NOT NULL;

CREATE TABLE media_deletion_tasks (
    id VARCHAR(36) PRIMARY KEY,
    bucket_type VARCHAR(24) NOT NULL,
    object_key VARCHAR(512) NOT NULL,
    resource_type VARCHAR(32) NOT NULL,
    resource_id VARCHAR(36),
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_error TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT ck_media_deletion_bucket_type CHECK (
        bucket_type IN ('media', 'reference')
    ),
    CONSTRAINT ck_media_deletion_status CHECK (
        status IN ('pending', 'completed')
    ),
    CONSTRAINT uq_media_deletion_object UNIQUE (bucket_type, object_key)
);

CREATE INDEX ix_media_deletion_tasks_status_next
    ON media_deletion_tasks (status, next_attempt_at);
CREATE INDEX ix_media_deletion_tasks_resource
    ON media_deletion_tasks (resource_type, resource_id);
