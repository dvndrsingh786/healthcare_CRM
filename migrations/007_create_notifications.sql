-- Notification outbox. A row is written in the SAME transaction as the business change
-- (e.g. an appointment booking), so a message is never lost and never sent for a change
-- that was rolled back. A worker (service account) sends due rows through the provider.
--
-- Minimum-necessary data: no names, addresses, phone numbers or message text are stored here.
-- The recipient's address is looked up at send time and the text comes from a template.
CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    patient_id UUID REFERENCES patients(id),
    recipient_user_id UUID REFERENCES users(id),
    channel VARCHAR(5) NOT NULL CHECK (channel IN ('EMAIL', 'SMS', 'PUSH')),
    template_key VARCHAR(60) NOT NULL,
    -- What the message is about, as ids only (e.g. appointment + its id).
    reference_type VARCHAR(30),
    reference_id UUID,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    transactional BOOLEAN NOT NULL DEFAULT false,
    status VARCHAR(10) NOT NULL DEFAULT 'QUEUED'
        CHECK (status IN ('QUEUED', 'SENDING', 'SENT', 'FAILED', 'SKIPPED', 'CANCELLED')),
    -- Why a message was not sent (OPTED_OUT, NO_ADDRESS, ...). Codes only.
    skip_reason VARCHAR(30),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    scheduled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- A worker that picks a row "leases" it until this time. If the worker dies, the lease
    -- runs out and another worker retries (with the same provider idempotency key).
    locked_until TIMESTAMPTZ,
    last_error_code VARCHAR(60),
    sent_at TIMESTAMPTZ,
    provider_message_id VARCHAR(120),
    -- Same key again = same request: the existing row is returned instead of a second message.
    idempotency_key VARCHAR(160) NOT NULL,
    -- Hash of the request body, so reusing a key for a DIFFERENT request is detected.
    request_hash CHAR(64),
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_notifications_idempotency UNIQUE (organisation_id, idempotency_key),
    CONSTRAINT ck_notifications_recipient CHECK (patient_id IS NOT NULL OR recipient_user_id IS NOT NULL),
    CONSTRAINT ck_notifications_sent CHECK ((status = 'SENT') = (sent_at IS NOT NULL))
);
CREATE INDEX idx_notifications_due ON notifications (organisation_id, next_attempt_at)
    WHERE status IN ('QUEUED', 'SENDING');
CREATE INDEX idx_notifications_patient ON notifications (patient_id, created_at DESC);
CREATE INDEX idx_notifications_reference ON notifications (reference_type, reference_id);
CREATE TRIGGER trg_notifications_updated_at BEFORE UPDATE ON notifications
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- One row per delivery attempt, so provider failures are recorded and never silently lost.
CREATE TABLE notification_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notification_id UUID NOT NULL REFERENCES notifications(id),
    attempt_number INTEGER NOT NULL,
    outcome VARCHAR(10) NOT NULL CHECK (outcome IN ('SENT', 'FAILED', 'SKIPPED')),
    error_code VARCHAR(60),
    provider_message_id VARCHAR(120),
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX idx_notification_attempts_notification ON notification_attempts (notification_id, attempt_number);
CREATE TRIGGER trg_notification_attempts_append_only BEFORE UPDATE OR DELETE ON notification_attempts
    FOR EACH ROW EXECUTE FUNCTION prevent_change();

-- Push tokens of patient app devices. Registered by the app after login, revocable by the user.
CREATE TABLE device_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform VARCHAR(10) NOT NULL CHECK (platform IN ('IOS', 'ANDROID', 'WEB')),
    push_token VARCHAR(4096) NOT NULL,
    -- Lookup/uniqueness by hash: one device token belongs to one user at a time.
    token_hash CHAR(64) NOT NULL,
    device_name VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX uq_device_tokens_active ON device_tokens (token_hash) WHERE revoked_at IS NULL;
CREATE INDEX idx_device_tokens_user ON device_tokens (user_id) WHERE revoked_at IS NULL;

-- migrate:down
DROP TABLE device_tokens;
DROP TABLE notification_attempts;
DROP TABLE notifications;
