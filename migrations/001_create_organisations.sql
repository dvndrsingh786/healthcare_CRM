-- Shared helper: keeps updated_at correct on every UPDATE, without relying on the app code.
CREATE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Shared helper: makes a table append-only (used for audit events and consent evidence).
-- Normal application flows can only INSERT; UPDATE and DELETE raise an error.
CREATE FUNCTION prevent_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

-- An organisation (tenant). Every other business record belongs to exactly one.
CREATE TABLE organisations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    slug VARCHAR(60) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'SUSPENDED')),
    timezone VARCHAR(64) NOT NULL DEFAULT 'Europe/London',
    -- Placeholders for where data must live and org-specific rules (retention, policies).
    data_region VARCHAR(32) NOT NULL DEFAULT 'uk',
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_organisations_slug UNIQUE (slug)
);

CREATE TRIGGER trg_organisations_updated_at BEFORE UPDATE ON organisations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- migrate:down
DROP TABLE organisations;
DROP FUNCTION prevent_change();
DROP FUNCTION set_updated_at();
