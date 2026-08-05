CREATE TABLE users (
    id VARCHAR(36) PRIMARY KEY,
    username VARCHAR(64) NOT NULL UNIQUE,
    email VARCHAR(320),
    password_hash VARCHAR(128) NOT NULL,
    display_name VARCHAR(128) NOT NULL DEFAULT '',
    is_public BOOLEAN NOT NULL DEFAULT FALSE,
    credits INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE UNIQUE INDEX ix_users_username ON users (username);
CREATE UNIQUE INDEX ix_users_email ON users (email) WHERE email IS NOT NULL;

CREATE TABLE upstream_providers (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    base_url VARCHAR(512) NOT NULL,
    api_key VARCHAR(512) NOT NULL,
    timeout_seconds INTEGER NOT NULL DEFAULT 700,
    default_size VARCHAR(32) NOT NULL DEFAULT 'auto',
    default_quality VARCHAR(32) NOT NULL DEFAULT 'high',
    default_output_format VARCHAR(32) NOT NULL DEFAULT 'jpeg',
    default_output_compression INTEGER NOT NULL DEFAULT 85,
    default_background VARCHAR(32) NOT NULL DEFAULT 'auto',
    default_moderation VARCHAR(32) NOT NULL DEFAULT 'auto',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE TABLE generation_jobs (
    id VARCHAR(36) PRIMARY KEY,
    status VARCHAR(10) NOT NULL DEFAULT 'QUEUED',
    prompt TEXT NOT NULL,
    revised_prompt TEXT,
    model VARCHAR(128) NOT NULL,
    size VARCHAR(32) NOT NULL DEFAULT 'auto',
    aspect_ratio VARCHAR(16) NOT NULL DEFAULT 'auto',
    reference_image_key VARCHAR(512),
    reference_image_content_type VARCHAR(128),
    reference_image_filename VARCHAR(255),
    user_id VARCHAR(36),
    object_key VARCHAR(512),
    public_url VARCHAR(512),
    error_message TEXT,
    provider_job_meta JSON,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE,
    finished_at TIMESTAMP WITH TIME ZONE,
    is_public BOOLEAN NOT NULL DEFAULT FALSE,
    is_prompt_public BOOLEAN NOT NULL DEFAULT TRUE,
    is_favorite BOOLEAN NOT NULL DEFAULT FALSE,
    tags JSON,
    CONSTRAINT generationjobstatus CHECK (status IN ('QUEUED', 'PROCESSING', 'SUCCEEDED', 'FAILED'))
);

CREATE INDEX ix_generation_jobs_status ON generation_jobs (status);
CREATE INDEX ix_generation_jobs_user_id ON generation_jobs (user_id);
CREATE INDEX ix_generation_jobs_finished_at ON generation_jobs (finished_at);
CREATE INDEX ix_generation_jobs_is_public ON generation_jobs (is_public);
CREATE INDEX ix_generation_jobs_is_favorite ON generation_jobs (is_favorite);

CREATE TABLE model_configs (
    id VARCHAR(128) PRIMARY KEY,
    provider_id VARCHAR(36) NOT NULL REFERENCES upstream_providers (id),
    label VARCHAR(256) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    supports_reference_image BOOLEAN NOT NULL DEFAULT TRUE,
    supported_sizes JSON NOT NULL DEFAULT '[]'::json,
    sort_order INTEGER NOT NULL DEFAULT 0,
    credit_cost INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX ix_model_configs_provider_id ON model_configs (provider_id);

CREATE TABLE reference_images (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    object_key VARCHAR(512) NOT NULL,
    content_type VARCHAR(128) NOT NULL,
    filename VARCHAR(255) NOT NULL,
    used_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX ix_reference_images_user_id ON reference_images (user_id);

CREATE TABLE credit_transactions (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users (id),
    amount INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    reason VARCHAR(256) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX ix_credit_transactions_user_id ON credit_transactions (user_id);

CREATE TABLE redemption_codes (
    id VARCHAR(36) PRIMARY KEY,
    code VARCHAR(64) NOT NULL UNIQUE,
    credits INTEGER NOT NULL,
    created_by VARCHAR(36) NOT NULL REFERENCES users (id),
    used_by VARCHAR(36) REFERENCES users (id),
    used_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE UNIQUE INDEX ix_redemption_codes_code ON redemption_codes (code);

CREATE TABLE announcements (
    id VARCHAR(36) PRIMARY KEY,
    title VARCHAR(128) NOT NULL,
    content TEXT NOT NULL,
    level VARCHAR(16) NOT NULL DEFAULT 'info',
    audience VARCHAR(32) NOT NULL DEFAULT 'all',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX ix_announcements_level ON announcements (level);
CREATE INDEX ix_announcements_audience ON announcements (audience);
CREATE INDEX ix_announcements_enabled ON announcements (enabled);

CREATE TABLE gallery_likes (
    id VARCHAR(36) PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL REFERENCES generation_jobs (id),
    user_id VARCHAR(36) NOT NULL REFERENCES users (id),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_gallery_like_job_user UNIQUE (job_id, user_id)
);

CREATE INDEX ix_gallery_likes_job_id ON gallery_likes (job_id);
CREATE INDEX ix_gallery_likes_user_id ON gallery_likes (user_id);

CREATE TABLE inspirations (
    id VARCHAR(36) PRIMARY KEY,
    title VARCHAR(256) NOT NULL,
    description TEXT,
    prompt TEXT NOT NULL,
    image_url VARCHAR(512) NOT NULL,
    image_object_key VARCHAR(512),
    external_id VARCHAR(256),
    source VARCHAR(128) NOT NULL,
    source_url VARCHAR(512),
    author_name VARCHAR(128),
    author_url VARCHAR(512),
    language VARCHAR(8) NOT NULL DEFAULT 'zh',
    categories JSON,
    is_featured BOOLEAN NOT NULL DEFAULT FALSE,
    like_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_inspiration_source_ext_id UNIQUE (source, external_id)
);

CREATE INDEX ix_inspirations_external_id ON inspirations (external_id);
CREATE INDEX ix_inspirations_source ON inspirations (source);
CREATE INDEX ix_inspirations_is_featured ON inspirations (is_featured);
