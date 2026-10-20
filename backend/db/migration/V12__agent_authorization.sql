-- Additive: browser sessions, existing jobs and billing records remain unchanged.
CREATE TABLE agent_clients (
    id VARCHAR(36) PRIMARY KEY, name VARCHAR(100) NOT NULL,
    redirect_uris JSON NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE agent_grants (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    client_id VARCHAR(36) NOT NULL REFERENCES agent_clients(id),
    resource VARCHAR(2048) NOT NULL, label VARCHAR(100) NOT NULL, scopes JSON NOT NULL, password_digest VARCHAR(64) NOT NULL,
    max_per_job INTEGER NOT NULL, daily_limit INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL, revoked_at TIMESTAMPTZ,
    CONSTRAINT ck_agent_grant_limits CHECK (max_per_job >= 0 AND daily_limit >= max_per_job)
);
CREATE INDEX ix_agent_grants_user_id ON agent_grants(user_id);
CREATE TABLE agent_authorizations (
    id VARCHAR(36) PRIMARY KEY, client_id VARCHAR(36) NOT NULL REFERENCES agent_clients(id),
    redirect_uri VARCHAR(2048) NOT NULL, state VARCHAR(1024) NOT NULL,
    challenge VARCHAR(43) NOT NULL, scopes JSON NOT NULL, resource VARCHAR(2048) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    grant_id VARCHAR(36) REFERENCES agent_grants(id) ON DELETE CASCADE,
    code_hash VARCHAR(64) UNIQUE, consumed_at TIMESTAMPTZ
);
CREATE INDEX ix_agent_authorizations_expires_at ON agent_authorizations(expires_at);
CREATE TABLE agent_credentials (
    token_hash VARCHAR(64) PRIMARY KEY,
    grant_id VARCHAR(36) NOT NULL REFERENCES agent_grants(id) ON DELETE CASCADE,
    kind VARCHAR(10) NOT NULL CHECK (kind IN ('access', 'refresh')),
    expires_at TIMESTAMPTZ NOT NULL, used_at TIMESTAMPTZ
);
CREATE INDEX ix_agent_credentials_grant_id ON agent_credentials(grant_id);
CREATE INDEX ix_agent_credentials_expires_at ON agent_credentials(expires_at);
CREATE TABLE agent_usage (
    job_id VARCHAR(36) PRIMARY KEY REFERENCES generation_jobs(id) ON DELETE CASCADE,
    grant_id VARCHAR(36) NOT NULL REFERENCES agent_grants(id) ON DELETE CASCADE,
    request_key VARCHAR(128) NOT NULL, request_digest VARCHAR(64) NOT NULL, created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_agent_usage_request UNIQUE (grant_id, request_key)
);
CREATE INDEX ix_agent_usage_grant_id ON agent_usage(grant_id);
CREATE INDEX ix_agent_usage_created_at ON agent_usage(created_at);
