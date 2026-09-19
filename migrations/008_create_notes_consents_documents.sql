-- Visibility classes shared by notes and documents:
--   INTERNAL     CRM staff with the read permission (notes:read / documents:read)
--   CLINICAL     restricted care/clinical content: additionally needs notes:read_clinical
--                (coordinators/support and the patient app never see it)
--   APP_VISIBLE  CRM staff with the read permission AND the patient in the app

-- Interactions / notes on the patient timeline. Never deleted: a wrong note is marked
-- ENTERED_IN_ERROR, and every edit keeps the previous text in note_revisions.
CREATE TABLE notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    patient_id UUID NOT NULL REFERENCES patients(id),
    appointment_id UUID REFERENCES appointments(id),
    author_user_id UUID NOT NULL REFERENCES users(id),
    note_type VARCHAR(12) NOT NULL
        CHECK (note_type IN ('NOTE', 'PHONE_CALL', 'VISIT', 'EMAIL', 'SMS', 'MEETING', 'MESSAGE')),
    subject VARCHAR(200) NOT NULL,
    body TEXT NOT NULL CHECK (length(body) <= 20000),
    visibility VARCHAR(12) NOT NULL CHECK (visibility IN ('INTERNAL', 'CLINICAL', 'APP_VISIBLE')),
    occurred_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'ENTERED_IN_ERROR')),
    retracted_reason VARCHAR(255),
    version INTEGER NOT NULL DEFAULT 1,
    updated_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ck_notes_retracted CHECK ((status = 'ENTERED_IN_ERROR') = (retracted_reason IS NOT NULL))
);
CREATE INDEX idx_notes_patient ON notes (patient_id, occurred_at DESC);
CREATE INDEX idx_notes_org_author ON notes (organisation_id, author_user_id);
CREATE TRIGGER trg_notes_updated_at BEFORE UPDATE ON notes
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- The content of a note BEFORE each edit. Append-only.
CREATE TABLE note_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    note_id UUID NOT NULL REFERENCES notes(id),
    version INTEGER NOT NULL,
    note_type VARCHAR(12) NOT NULL,
    subject VARCHAR(200) NOT NULL,
    body TEXT NOT NULL,
    visibility VARCHAR(12) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    edited_by UUID NOT NULL REFERENCES users(id),
    edit_reason VARCHAR(255),
    edited_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_note_revisions_version UNIQUE (note_id, version)
);
CREATE TRIGGER trg_note_revisions_append_only BEFORE UPDATE OR DELETE ON note_revisions
    FOR EACH ROW EXECUTE FUNCTION prevent_change();

-- Document metadata. The file itself lives in private storage under storage_key, a random
-- non-guessable name; there are no public file URLs. Downloads use short-lived signed links
-- that re-check the caller's CURRENT authorisation.
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    patient_id UUID NOT NULL REFERENCES patients(id),
    category VARCHAR(16) NOT NULL
        CHECK (category IN ('REFERRAL', 'CARE_PLAN', 'LETTER', 'CONSENT_FORM', 'ASSESSMENT', 'IDENTITY', 'OTHER')),
    title VARCHAR(200),
    original_filename VARCHAR(255) NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
    storage_key VARCHAR(120) NOT NULL,
    checksum_sha256 CHAR(64),
    visibility VARCHAR(12) NOT NULL CHECK (visibility IN ('INTERNAL', 'CLINICAL', 'APP_VISIBLE')),
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING_UPLOAD'
        CHECK (status IN ('PENDING_UPLOAD', 'AVAILABLE', 'REJECTED', 'ARCHIVED')),
    -- Result of the malware-scanning hook (see app/storage.py).
    scan_status VARCHAR(12) NOT NULL DEFAULT 'NOT_SCANNED' CHECK (scan_status IN ('NOT_SCANNED', 'CLEAN', 'INFECTED')),
    rejected_reason VARCHAR(60),
    uploaded_by UUID NOT NULL REFERENCES users(id),
    uploaded_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ,
    archived_by UUID REFERENCES users(id),
    archived_reason VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_documents_storage_key UNIQUE (storage_key),
    CONSTRAINT ck_documents_available CHECK (status <> 'AVAILABLE' OR (uploaded_at IS NOT NULL AND checksum_sha256 IS NOT NULL))
);
CREATE INDEX idx_documents_patient ON documents (patient_id, created_at DESC);
CREATE TRIGGER trg_documents_updated_at BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Consent evidence. Append-only: a change is a NEW row, the previous one stays as evidence.
-- The current state of a type is its latest row.
CREATE TABLE consent_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    patient_id UUID NOT NULL REFERENCES patients(id),
    consent_type VARCHAR(30) NOT NULL CHECK (consent_type IN (
        'DATA_PROCESSING', 'CARE_INFORMATION_SHARING', 'APP_TERMS', 'MARKETING_EMAIL', 'MARKETING_SMS',
        'RESEARCH_CONTACT')),
    status VARCHAR(10) NOT NULL CHECK (status IN ('GRANTED', 'WITHDRAWN', 'REFUSED')),
    -- How the consent was given: in the app, verbally to staff, on a paper or electronic form...
    source VARCHAR(16) NOT NULL CHECK (source IN ('APP', 'STAFF_VERBAL', 'PAPER_FORM', 'ELECTRONIC_FORM', 'IMPORT')),
    -- Which version of the policy / consent wording the patient agreed to.
    policy_version VARCHAR(40) NOT NULL,
    -- When the patient gave it (may be earlier than recorded, e.g. a paper form).
    captured_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ,
    captured_by UUID NOT NULL REFERENCES users(id),
    captured_by_type VARCHAR(10) NOT NULL CHECK (captured_by_type IN ('STAFF', 'PATIENT')),
    evidence_document_id UUID REFERENCES documents(id),
    note VARCHAR(500),
    supersedes_id UUID REFERENCES consent_records(id),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),

    CONSTRAINT ck_consent_expiry CHECK (expires_at IS NULL OR expires_at > captured_at)
);
CREATE INDEX idx_consent_patient_type ON consent_records (patient_id, consent_type, recorded_at DESC);
CREATE TRIGGER trg_consent_records_append_only BEFORE UPDATE OR DELETE ON consent_records
    FOR EACH ROW EXECUTE FUNCTION prevent_change();

-- migrate:down
DROP TABLE consent_records;
DROP TABLE documents;
DROP TABLE note_revisions;
DROP TABLE notes;
