-- Users of every kind: staff (CRM), patients (app) and service accounts (machines).
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    email VARCHAR(254) NOT NULL,
    user_type VARCHAR(10) NOT NULL CHECK (user_type IN ('STAFF', 'PATIENT', 'SERVICE')),
    status VARCHAR(10) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE')),
    -- NULL means "no password yet" (invited user, or a service account that uses API keys).
    password_hash VARCHAR(255),
    -- Hook for an external identity provider (SSO / OIDC "sub" claim). Unused in sprint 1.
    idp_subject VARCHAR(255),
    mfa_enabled BOOLEAN NOT NULL DEFAULT false,
    last_login_at TIMESTAMPTZ,
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    created_by UUID REFERENCES users(id),
    updated_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- One account per email address (case-insensitive), so login needs only email + password.
CREATE UNIQUE INDEX uq_users_email ON users (lower(email));
CREATE INDEX idx_users_org_type ON users (organisation_id, user_type, status);
CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Permission keys are fixed by the code (the code checks them). Roles are sets of keys.
CREATE TABLE permissions (
    key VARCHAR(60) PRIMARY KEY,
    description VARCHAR(255) NOT NULL
);

-- organisation_id NULL = built-in role shared by every organisation.
-- Organisations can get their own custom roles later without a schema change.
CREATE TABLE roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID REFERENCES organisations(id),
    key VARCHAR(40) NOT NULL,
    name VARCHAR(100) NOT NULL,
    description VARCHAR(255) NOT NULL DEFAULT '',
    -- Which kind of user may hold this role. Stops e.g. a patient getting a staff role.
    for_user_type VARCHAR(10) NOT NULL CHECK (for_user_type IN ('STAFF', 'PATIENT', 'SERVICE')),
    is_system BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_roles_system_key ON roles (key) WHERE organisation_id IS NULL;
CREATE UNIQUE INDEX uq_roles_org_key ON roles (organisation_id, key) WHERE organisation_id IS NOT NULL;

CREATE TABLE role_permissions (
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_key VARCHAR(60) NOT NULL REFERENCES permissions(key),
    PRIMARY KEY (role_id, permission_key)
);

CREATE TABLE user_roles (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES roles(id),
    assigned_by UUID REFERENCES users(id),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, role_id)
);
CREATE INDEX idx_user_roles_role ON user_roles (role_id);

-- Teams / services that patients can be assigned to (e.g. "Community Nursing - North").
CREATE TABLE teams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    name VARCHAR(120) NOT NULL,
    service VARCHAR(120),
    active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_teams_org_name UNIQUE (organisation_id, name)
);

CREATE TABLE team_members (
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, user_id)
);
CREATE INDEX idx_team_members_user ON team_members (user_id);

CREATE TABLE staff_profiles (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    display_name VARCHAR(120) NOT NULL,
    job_title VARCHAR(120),
    phone VARCHAR(30),
    active BOOLEAN NOT NULL DEFAULT true,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_staff_profiles_updated_at BEFORE UPDATE ON staff_profiles
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------- Built-in permissions and roles ----------

INSERT INTO permissions (key, description) VALUES
    ('org:manage',               'Change organisation settings'),
    ('users:read',               'List staff users, roles and teams'),
    ('users:manage',             'Create, update, activate and deactivate users and service accounts'),
    ('roles:manage',             'Assign and remove roles'),
    ('audit:read',               'Search the audit log'),
    ('patients:read_all',        'See every patient in the organisation'),
    ('patients:read_assigned',   'See patients assigned to you or your team'),
    ('patients:read_sensitive',  'See date of birth, address and identifiers'),
    ('patients:write',           'Create and update patients and emergency contacts'),
    ('patients:archive',         'Archive and restore patients'),
    ('assignments:manage',       'Assign staff and teams to patients, manage teams'),
    ('appointments:read',        'See appointments of visible patients'),
    ('appointments:write',       'Create, reschedule and cancel appointments'),
    ('appointments:update_outcome', 'Mark appointments completed or no-show'),
    ('tasks:read_all',           'See every task in the organisation'),
    ('tasks:write',              'Create and update tasks'),
    ('notes:read',               'Read internal and app-visible notes'),
    ('notes:read_clinical',      'Read restricted clinical/care notes and documents'),
    ('notes:write',              'Write notes and interactions'),
    ('consents:read',            'See consent records'),
    ('consents:write',           'Record consent changes'),
    ('documents:read',           'List and download documents'),
    ('documents:write',          'Upload and archive documents'),
    ('notifications:send',       'Request notifications'),
    ('notifications:read',       'See notification status'),
    ('notifications:process',    'Run the notification outbox (service accounts)'),
    ('summary:read',             'See the CRM dashboard counts'),
    ('app:self',                 'Patient app: own records only');

INSERT INTO roles (key, name, description, for_user_type, is_system) VALUES
    ('SYSTEM_ADMIN', 'System Admin', 'Organisation settings, users, roles and audit. No clinical access by default.', 'STAFF', true),
    ('OPS_ADMIN', 'CRM / Operations Admin', 'Patient demographics, appointments, assignments, tasks and communications.', 'STAFF', true),
    ('CARE_STAFF', 'Healthcare / Care Staff', 'Assigned patients, clinical notes, appointment outcomes, own tasks.', 'STAFF', true),
    ('COORDINATOR', 'Coordinator / Support', 'Minimum operational data, scheduling and follow-ups. No clinical notes.', 'STAFF', true),
    ('APP_USER', 'App User / Patient', 'Own profile, appointments, consents and app-visible documents.', 'PATIENT', true),
    ('NOTIFICATION_WORKER', 'Notification worker', 'Machine account that processes the notification outbox.', 'SERVICE', true);

INSERT INTO role_permissions (role_id, permission_key)
SELECT roles.id, grants.permission_key
FROM (VALUES
    ('SYSTEM_ADMIN', 'org:manage'), ('SYSTEM_ADMIN', 'users:read'), ('SYSTEM_ADMIN', 'users:manage'),
    ('SYSTEM_ADMIN', 'roles:manage'), ('SYSTEM_ADMIN', 'audit:read'), ('SYSTEM_ADMIN', 'notifications:read'),

    ('OPS_ADMIN', 'users:read'), ('OPS_ADMIN', 'patients:read_all'), ('OPS_ADMIN', 'patients:read_sensitive'),
    ('OPS_ADMIN', 'patients:write'), ('OPS_ADMIN', 'patients:archive'), ('OPS_ADMIN', 'assignments:manage'),
    ('OPS_ADMIN', 'appointments:read'), ('OPS_ADMIN', 'appointments:write'),
    ('OPS_ADMIN', 'appointments:update_outcome'), ('OPS_ADMIN', 'tasks:read_all'), ('OPS_ADMIN', 'tasks:write'),
    ('OPS_ADMIN', 'notes:read'), ('OPS_ADMIN', 'notes:write'), ('OPS_ADMIN', 'consents:read'),
    ('OPS_ADMIN', 'consents:write'), ('OPS_ADMIN', 'documents:read'), ('OPS_ADMIN', 'documents:write'),
    ('OPS_ADMIN', 'notifications:send'), ('OPS_ADMIN', 'notifications:read'), ('OPS_ADMIN', 'summary:read'),

    ('CARE_STAFF', 'users:read'), ('CARE_STAFF', 'patients:read_assigned'), ('CARE_STAFF', 'patients:read_sensitive'),
    ('CARE_STAFF', 'appointments:read'), ('CARE_STAFF', 'appointments:update_outcome'), ('CARE_STAFF', 'tasks:write'),
    ('CARE_STAFF', 'notes:read'), ('CARE_STAFF', 'notes:read_clinical'), ('CARE_STAFF', 'notes:write'),
    ('CARE_STAFF', 'consents:read'), ('CARE_STAFF', 'consents:write'), ('CARE_STAFF', 'documents:read'),
    ('CARE_STAFF', 'documents:write'), ('CARE_STAFF', 'summary:read'),

    ('COORDINATOR', 'users:read'), ('COORDINATOR', 'patients:read_all'), ('COORDINATOR', 'appointments:read'),
    ('COORDINATOR', 'appointments:write'), ('COORDINATOR', 'tasks:read_all'), ('COORDINATOR', 'tasks:write'),
    ('COORDINATOR', 'notes:read'), ('COORDINATOR', 'notes:write'), ('COORDINATOR', 'consents:read'),
    ('COORDINATOR', 'notifications:send'), ('COORDINATOR', 'notifications:read'), ('COORDINATOR', 'summary:read'),

    ('APP_USER', 'app:self'),

    ('NOTIFICATION_WORKER', 'notifications:process')
) AS grants (role_key, permission_key)
JOIN roles ON roles.key = grants.role_key AND roles.organisation_id IS NULL;

-- migrate:down
DROP TABLE staff_profiles;
DROP TABLE team_members;
DROP TABLE teams;
DROP TABLE user_roles;
DROP TABLE role_permissions;
DROP TABLE roles;
DROP TABLE permissions;
DROP TABLE users;
