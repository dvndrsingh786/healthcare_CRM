-- btree_gist lets one exclusion constraint combine "same staff member" (=) with
-- "overlapping time" (&&), so double-booking is refused by the database itself, even when two
-- requests arrive at the same moment. It is a trusted extension (no superuser needed).
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Appointments / visits. Times are stored in UTC (TIMESTAMPTZ); `timezone` keeps the IANA zone
-- the appointment was booked in, so the app can show local time correctly across DST changes.
CREATE TABLE appointments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    patient_id UUID NOT NULL REFERENCES patients(id),
    -- Who delivers it: a staff member, a team/service, or both.
    staff_user_id UUID REFERENCES users(id),
    team_id UUID REFERENCES teams(id),
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    timezone VARCHAR(64) NOT NULL,
    appointment_type VARCHAR(20) NOT NULL
        CHECK (appointment_type IN ('HOME_VISIT', 'CLINIC', 'ASSESSMENT', 'REVIEW', 'FOLLOW_UP', 'OTHER')),
    mode VARCHAR(10) NOT NULL CHECK (mode IN ('IN_PERSON', 'PHONE', 'VIDEO')),
    location VARCHAR(255),
    -- Shown to the patient in the app (e.g. "Bring your medication list").
    patient_instructions VARCHAR(1000),
    -- CRM only. Never returned by app endpoints.
    internal_note VARCHAR(2000),
    status VARCHAR(12) NOT NULL DEFAULT 'SCHEDULED'
        CHECK (status IN ('SCHEDULED', 'CONFIRMED', 'COMPLETED', 'NO_SHOW', 'CANCELLED')),
    cancellation_reason VARCHAR(255),
    cancelled_at TIMESTAMPTZ,
    cancelled_by UUID REFERENCES users(id),
    outcome_recorded_at TIMESTAMPTZ,
    outcome_recorded_by UUID REFERENCES users(id),
    -- false = CRM-only appointment (e.g. an internal case review); the patient app does not see it.
    app_visible BOOLEAN NOT NULL DEFAULT true,
    version INTEGER NOT NULL DEFAULT 1,
    created_by UUID REFERENCES users(id),
    updated_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ck_appointments_times CHECK (ends_at > starts_at AND ends_at <= starts_at + interval '24 hours'),
    CONSTRAINT ck_appointments_cancelled CHECK (
        (status = 'CANCELLED') = (cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL)),
    CONSTRAINT ck_appointments_outcome CHECK (
        (status IN ('COMPLETED', 'NO_SHOW')) = (outcome_recorded_at IS NOT NULL)),
    -- One staff member cannot have two live appointments at overlapping times.
    CONSTRAINT ex_appointments_staff_overlap EXCLUDE USING gist (
        staff_user_id WITH =, tstzrange(starts_at, ends_at) WITH &&
    ) WHERE (staff_user_id IS NOT NULL AND status IN ('SCHEDULED', 'CONFIRMED'))
);
CREATE INDEX idx_appointments_org_start ON appointments (organisation_id, starts_at);
CREATE INDEX idx_appointments_patient ON appointments (patient_id, starts_at DESC);
CREATE INDEX idx_appointments_staff ON appointments (staff_user_id, starts_at) WHERE staff_user_id IS NOT NULL;
CREATE TRIGGER trg_appointments_updated_at BEFORE UPDATE ON appointments
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Every lifecycle step of an appointment. Append-only, so history cannot be rewritten.
CREATE TABLE appointment_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    appointment_id UUID NOT NULL REFERENCES appointments(id),
    event VARCHAR(20) NOT NULL
        CHECK (event IN ('CREATED', 'UPDATED', 'RESCHEDULED', 'CONFIRMED', 'CANCELLED', 'COMPLETED', 'NO_SHOW')),
    from_status VARCHAR(12),
    to_status VARCHAR(12) NOT NULL,
    old_starts_at TIMESTAMPTZ,
    new_starts_at TIMESTAMPTZ,
    reason VARCHAR(255),
    actor_user_id UUID REFERENCES users(id),
    -- clock_timestamp(), not now(): several events written in one transaction keep their real order.
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX idx_appointment_events_appointment ON appointment_events (appointment_id, occurred_at);
CREATE TRIGGER trg_appointment_events_append_only BEFORE UPDATE OR DELETE ON appointment_events
    FOR EACH ROW EXECUTE FUNCTION prevent_change();

-- CRM tasks / follow-ups. Linked to a patient and/or an appointment, owned by one staff member.
CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    patient_id UUID REFERENCES patients(id),
    appointment_id UUID REFERENCES appointments(id),
    owner_user_id UUID NOT NULL REFERENCES users(id),
    title VARCHAR(200) NOT NULL,
    description VARCHAR(4000),
    priority VARCHAR(10) NOT NULL DEFAULT 'NORMAL' CHECK (priority IN ('LOW', 'NORMAL', 'HIGH', 'URGENT')),
    due_at TIMESTAMPTZ,
    status VARCHAR(12) NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'IN_PROGRESS', 'DONE', 'CANCELLED')),
    completed_at TIMESTAMPTZ,
    completed_by UUID REFERENCES users(id),
    version INTEGER NOT NULL DEFAULT 1,
    created_by UUID REFERENCES users(id),
    updated_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- A DONE task always says who completed it and when; other statuses never do.
    CONSTRAINT ck_tasks_completed CHECK (
        (status = 'DONE') = (completed_at IS NOT NULL AND completed_by IS NOT NULL))
);
CREATE INDEX idx_tasks_owner_open ON tasks (owner_user_id, due_at) WHERE status IN ('OPEN', 'IN_PROGRESS');
CREATE INDEX idx_tasks_org_status_due ON tasks (organisation_id, status, due_at);
CREATE INDEX idx_tasks_patient ON tasks (patient_id) WHERE patient_id IS NOT NULL;
CREATE INDEX idx_tasks_appointment ON tasks (appointment_id) WHERE appointment_id IS NOT NULL;
CREATE TRIGGER trg_tasks_updated_at BEFORE UPDATE ON tasks
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- migrate:down
DROP TABLE tasks;
DROP TABLE appointment_events;
DROP TABLE appointments;
DROP EXTENSION IF EXISTS btree_gist;
