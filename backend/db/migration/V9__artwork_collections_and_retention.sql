CREATE TABLE favorites (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id VARCHAR(36),
    inspiration_id VARCHAR(36),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_favorite_one_target CHECK (
        (job_id IS NOT NULL AND inspiration_id IS NULL) OR
        (job_id IS NULL AND inspiration_id IS NOT NULL)
    ),
    CONSTRAINT uq_favorite_user_job UNIQUE (user_id, job_id),
    CONSTRAINT uq_favorite_user_inspiration UNIQUE (user_id, inspiration_id)
);
CREATE INDEX ix_favorites_user_created ON favorites(user_id, created_at, id);
CREATE INDEX ix_favorites_job_id ON favorites(job_id);
CREATE INDEX ix_favorites_inspiration_id ON favorites(inspiration_id);
-- Stable legacy IDs avoid a UUID extension dependency. Keep expired bookmarks.
INSERT INTO favorites(id, user_id, job_id, created_at)
SELECT j.id, j.user_id, j.id, j.created_at
FROM generation_jobs j JOIN users u ON u.id = j.user_id
WHERE j.is_favorite = TRUE;

CREATE TABLE community_submissions (
    job_id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMPTZ,
    review_reason TEXT,
    inspiration_id VARCHAR(36),
    CONSTRAINT ck_submission_status CHECK (status IN ('pending','approved','rejected','withdrawn','expired'))
);
CREATE INDEX ix_submissions_user_id ON community_submissions(user_id);
CREATE INDEX ix_submissions_status_submitted ON community_submissions(status, submitted_at, job_id);
-- Existing gallery membership is NOT consent to submit to the community.
INSERT INTO community_submissions(job_id, user_id, status, submitted_at, reviewed_at, inspiration_id)
SELECT DISTINCT ON (source_job_id) source_job_id, source_user_id, 'approved',
       COALESCE(curated_at, created_at), COALESCE(curated_at, created_at), id
FROM inspirations WHERE source = 'community-curated' AND source_job_id IS NOT NULL AND source_user_id IS NOT NULL
ORDER BY source_job_id, created_at;

ALTER TABLE generation_jobs
    ADD COLUMN thumbnail_key VARCHAR(512), ADD COLUMN thumbnail_hash VARCHAR(64),
    ADD COLUMN thumbnail_size_bytes BIGINT, ADD COLUMN media_hash VARCHAR(64),
    ADD COLUMN thumbnail_attempts INTEGER NOT NULL DEFAULT 0, ADD COLUMN thumbnail_retry_at TIMESTAMPTZ;
ALTER TABLE reference_images
    ADD COLUMN thumbnail_key VARCHAR(512), ADD COLUMN thumbnail_hash VARCHAR(64),
    ADD COLUMN thumbnail_size_bytes BIGINT, ADD COLUMN media_hash VARCHAR(64),
    ADD COLUMN thumbnail_attempts INTEGER NOT NULL DEFAULT 0, ADD COLUMN thumbnail_retry_at TIMESTAMPTZ;
ALTER TABLE inspirations
    ADD COLUMN thumbnail_key VARCHAR(512), ADD COLUMN thumbnail_hash VARCHAR(64),
    ADD COLUMN thumbnail_size_bytes BIGINT, ADD COLUMN media_hash VARCHAR(64),
    ADD COLUMN thumbnail_attempts INTEGER NOT NULL DEFAULT 0, ADD COLUMN thumbnail_retry_at TIMESTAMPTZ;

UPDATE user_groups SET generated_retention_hours = 48, reference_retention_hours = 48 WHERE code <> 'vip';
-- Grant exactly 48 hours from rollout to still-live non-VIP media. Never revive
-- expired, deleted or deletion-pending objects; historical pricing stays intact.
UPDATE generation_jobs j SET media_expires_at = CURRENT_TIMESTAMP + INTERVAL '48 hours'
WHERE status = 'SUCCEEDED' AND deleted_at IS NULL AND media_state = 'available' AND object_key IS NOT NULL
  AND (media_expires_at IS NULL OR media_expires_at > CURRENT_TIMESTAMP)
  AND NOT EXISTS (SELECT 1 FROM users u WHERE u.id = j.user_id AND u.group_code = 'vip');
UPDATE generation_jobs j SET generated_retention_hours_snapshot = 48
WHERE status IN ('QUEUED', 'PROCESSING') AND deleted_at IS NULL
  AND NOT EXISTS (SELECT 1 FROM users u WHERE u.id = j.user_id AND u.group_code = 'vip');
UPDATE reference_images r SET media_expires_at = CURRENT_TIMESTAMP + INTERVAL '48 hours'
WHERE media_state = 'available' AND (media_expires_at IS NULL OR media_expires_at > CURRENT_TIMESTAMP)
  AND NOT EXISTS (SELECT 1 FROM users u WHERE u.id = r.user_id AND u.group_code = 'vip');

CREATE INDEX ix_generation_jobs_history ON generation_jobs(user_id, created_at DESC, id DESC) WHERE deleted_at IS NULL;
