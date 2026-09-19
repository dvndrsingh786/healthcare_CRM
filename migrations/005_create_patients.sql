-- Trigram indexes make "contains" name search (ILIKE '%smi%') fast. pg_trgm is a trusted
-- extension, so the database owner can enable it without superuser rights.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Patients / care recipients. Field classification (see app/modules/patients/schemas.py):
--   SENSITIVE: mrn, date_of_birth, address_*  -> only returned with patients:read_sensitive
--   PERSONAL:  names, email, phone, preferences -> returned to anyone who may see the patient
CREATE TABLE patients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    -- Optional internal reference (MRN-like). Unique inside the organisation when present.
    mrn VARCHAR(40),
    legal_first_name VARCHAR(100) NOT NULL,
    legal_last_name VARCHAR(100) NOT NULL,
    preferred_name VARCHAR(100),
    date_of_birth DATE NOT NULL,
    email VARCHAR(254),
    phone VARCHAR(30),
    address_line1 VARCHAR(200),
    address_line2 VARCHAR(200),
    city VARCHAR(100),
    postcode VARCHAR(20),
    country CHAR(2) NOT NULL DEFAULT 'GB',
    preferred_language VARCHAR(10) NOT NULL DEFAULT 'en',
    -- Communication preferences (channel opt-in). Consent evidence lives in consent_records.
    contact_by_email BOOLEAN NOT NULL DEFAULT true,
    contact_by_sms BOOLEAN NOT NULL DEFAULT false,
    contact_by_push BOOLEAN NOT NULL DEFAULT true,
    status VARCHAR(10) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE', 'ARCHIVED')),
    archived_at TIMESTAMPTZ,
    archived_reason VARCHAR(255),
    -- The patient's own app account, if they have one.
    app_user_id UUID REFERENCES users(id),
    -- Optimistic locking: every update must send the version it read, and bumps it by one.
    version INTEGER NOT NULL DEFAULT 1,
    created_by UUID REFERENCES users(id),
    updated_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ck_patients_archived CHECK ((status = 'ARCHIVED') = (archived_at IS NOT NULL)),
    CONSTRAINT uq_patients_app_user UNIQUE (app_user_id)
);
CREATE UNIQUE INDEX uq_patients_org_mrn ON patients (organisation_id, mrn) WHERE mrn IS NOT NULL;
CREATE INDEX idx_patients_org_status ON patients (organisation_id, status, updated_at DESC);
CREATE INDEX idx_patients_duplicate_check ON patients (organisation_id, lower(legal_last_name), date_of_birth);
CREATE INDEX idx_patients_name_search ON patients
    USING gin ((lower(legal_first_name || ' ' || legal_last_name || ' ' || coalesce(preferred_name, ''))) gin_trgm_ops);
CREATE INDEX idx_patients_email ON patients (organisation_id, lower(email));
CREATE TRIGGER trg_patients_updated_at BEFORE UPDATE ON patients
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE emergency_contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    patient_id UUID NOT NULL REFERENCES patients(id),
    name VARCHAR(150) NOT NULL,
    relationship VARCHAR(60) NOT NULL,
    phone VARCHAR(30),
    email VARCHAR(254),
    -- 1 = call first.
    priority SMALLINT NOT NULL DEFAULT 1 CHECK (priority BETWEEN 1 AND 9),
    is_next_of_kin BOOLEAN NOT NULL DEFAULT false,
    created_by UUID REFERENCES users(id),
    updated_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ck_emergency_contacts_reachable CHECK (phone IS NOT NULL OR email IS NOT NULL)
);
CREATE INDEX idx_emergency_contacts_patient ON emergency_contacts (patient_id, priority);
CREATE TRIGGER trg_emergency_contacts_updated_at BEFORE UPDATE ON emergency_contacts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Who is responsible for a patient: one staff member OR one team per row.
-- Ending an assignment keeps the row (active = false) so history is preserved.
CREATE TABLE patient_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    patient_id UUID NOT NULL REFERENCES patients(id),
    staff_user_id UUID REFERENCES users(id),
    team_id UUID REFERENCES teams(id),
    assignment_type VARCHAR(10) NOT NULL CHECK (assignment_type IN ('PRIMARY', 'SECONDARY', 'TEAM')),
    starts_on DATE NOT NULL DEFAULT CURRENT_DATE,
    ends_on DATE,
    active BOOLEAN NOT NULL DEFAULT true,
    created_by UUID REFERENCES users(id),
    ended_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ,

    CONSTRAINT ck_assignment_target CHECK ((staff_user_id IS NULL) <> (team_id IS NULL)),
    CONSTRAINT ck_assignment_dates CHECK (ends_on IS NULL OR ends_on >= starts_on)
);
-- The same person/team cannot be actively assigned twice, and there is one active PRIMARY at most.
CREATE UNIQUE INDEX uq_assignment_active_staff ON patient_assignments (patient_id, staff_user_id)
    WHERE active AND staff_user_id IS NOT NULL;
CREATE UNIQUE INDEX uq_assignment_active_team ON patient_assignments (patient_id, team_id)
    WHERE active AND team_id IS NOT NULL;
CREATE UNIQUE INDEX uq_assignment_active_primary ON patient_assignments (patient_id)
    WHERE active AND assignment_type = 'PRIMARY';
CREATE INDEX idx_assignment_staff ON patient_assignments (staff_user_id) WHERE active;
CREATE INDEX idx_assignment_team ON patient_assignments (team_id) WHERE active;

-- migrate:down
DROP TABLE patient_assignments;
DROP TABLE emergency_contacts;
DROP TABLE patients;
DROP EXTENSION IF EXISTS pg_trgm;
