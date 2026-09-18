-- A login session. The client holds two random tokens; we store only their SHA-256 hashes,
-- so a leaked database backup cannot be used to log in.
--   access token:  short-lived, sent on every request
--   refresh token: longer-lived, swapped for a NEW pair on every refresh (rotation)
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    -- 'crm' for staff, 'app' for patients. CRM and app endpoints each accept only their own scope.
    scope VARCHAR(10) NOT NULL CHECK (scope IN ('crm', 'app')),
    access_token_hash CHAR(64) NOT NULL,
    access_expires_at TIMESTAMPTZ NOT NULL,
    refresh_token_hash CHAR(64) NOT NULL,
    refresh_expires_at TIMESTAMPTZ NOT NULL,
    -- The refresh token that was just replaced. If it is ever used again, someone copied it,
    -- so the whole session is revoked (refresh-token reuse detection).
    previous_refresh_hash CHAR(64),
    revoked_at TIMESTAMPTZ,
    revoked_reason VARCHAR(40),
    ip_address VARCHAR(45),
    user_agent VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_refreshed_at TIMESTAMPTZ,

    CONSTRAINT uq_sessions_access UNIQUE (access_token_hash),
    CONSTRAINT uq_sessions_refresh UNIQUE (refresh_token_hash)
);
CREATE INDEX idx_sessions_user ON sessions (user_id) WHERE revoked_at IS NULL;
CREATE INDEX idx_sessions_previous_refresh ON sessions (previous_refresh_hash) WHERE previous_refresh_hash IS NOT NULL;

-- Password reset requests. Only the token hash is stored; the raw token is sent to the user once.
CREATE TABLE password_resets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash CHAR(64) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_password_resets_token UNIQUE (token_hash)
);
CREATE INDEX idx_password_resets_user ON password_resets (user_id);

-- API keys for service accounts (machine-to-machine). Always expire; can be rotated and revoked.
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- First characters of the key, shown in lists so people can tell keys apart. Not secret.
    prefix VARCHAR(12) NOT NULL,
    key_hash CHAR(64) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_api_keys_hash UNIQUE (key_hash)
);
CREATE INDEX idx_api_keys_user ON api_keys (user_id);

-- Fixed-window rate limit counters. Kept in the database so they work across several API processes.
CREATE TABLE rate_limits (
    bucket_key CHAR(64) PRIMARY KEY,
    hits INTEGER NOT NULL,
    window_ends_at TIMESTAMPTZ NOT NULL
);

-- migrate:down
DROP TABLE rate_limits;
DROP TABLE api_keys;
DROP TABLE password_resets;
DROP TABLE sessions;
