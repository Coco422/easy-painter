-- Optional VIP cloud copies. Local canvases never create rows here.
CREATE TABLE canvas_projects (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(120) NOT NULL,
    document JSON,
    version INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_canvas_projects_user_id ON canvas_projects(user_id);
CREATE TABLE canvas_assets (
    project_id VARCHAR(36) NOT NULL REFERENCES canvas_projects(id) ON DELETE CASCADE,
    digest VARCHAR(64) NOT NULL,
    object_key VARCHAR(512) NOT NULL UNIQUE,
    content_type VARCHAR(64) NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
    PRIMARY KEY (project_id, digest)
);
