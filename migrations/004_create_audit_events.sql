-- The global audit log. Append-only: the trigger below rejects UPDATE and DELETE,
-- so normal application code (and anyone using the app's database user) cannot edit history.
--
-- We store WHICH fields changed, never their values, so patient data and secrets
-- do not end up copied into the audit log.
CREATE TABLE audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- NULL only for events with no known organisation (e.g. login with an unknown email).
    organisation_id UUID REFERENCES organisations(id),
    actor_user_id UUID REFERENCES users(id),
    actor_type VARCHAR(10) NOT NULL CHECK (actor_type IN ('STAFF', 'PATIENT', 'SERVICE', 'SYSTEM', 'ANONYMOUS')),
    action VARCHAR(60) NOT NULL,
    resource_type VARCHAR(40),
    resource_id VARCHAR(64),
    outcome VARCHAR(10) NOT NULL CHECK (outcome IN ('SUCCESS', 'FAILURE', 'DENIED')),
    changed_fields TEXT[],
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    ip_address VARCHAR(45),
    user_agent VARCHAR(255),
    request_id VARCHAR(64),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_org_time ON audit_events (organisation_id, occurred_at DESC);
CREATE INDEX idx_audit_org_actor ON audit_events (organisation_id, actor_user_id, occurred_at DESC);
CREATE INDEX idx_audit_org_resource ON audit_events (organisation_id, resource_type, resource_id);
CREATE INDEX idx_audit_org_action ON audit_events (organisation_id, action, occurred_at DESC);

CREATE TRIGGER trg_audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION prevent_change();

-- migrate:down
DROP TABLE audit_events;
