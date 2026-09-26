-- ============================================================================
-- Canada B2B Business Data Automation System — PostgreSQL Schema
-- ============================================================================
-- Design goals:
--   * One canonical "businesses" row per real-world company (post-dedup).
--   * Every field keeps a source-history trail (business_field_sources) so we
--     never blindly overwrite conflicting data.
--   * Contacts (decision-makers) are separate rows, many-to-one with business.
--   * Dedup is driven by a normalized "business_identifiers" key table, not
--     by fuzzy-matching the businesses table directly.
--   * job_runs gives full pipeline observability (per source, per run).
--   * new_business_events is an append-only feed the dashboard/CRM reads for
--     "new today / last 7 days / last 30 days" and "recently changed".
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- fuzzy name matching for dedup
CREATE EXTENSION IF NOT EXISTS unaccent;     -- accent-insensitive name matching

CREATE OR REPLACE FUNCTION immutable_unaccent(text)
RETURNS text AS $$
    SELECT public.unaccent('public.unaccent', $1)
$$ LANGUAGE sql IMMUTABLE;

-- ---------------------------------------------------------------------------
-- ENUMS
-- ---------------------------------------------------------------------------
CREATE TYPE business_status AS ENUM ('active', 'inactive', 'dissolved', 'unknown');
CREATE TYPE size_confidence AS ENUM ('confirmed', 'estimated');
CREATE TYPE contact_role AS ENUM (
    'owner', 'founder', 'president', 'general_manager', 'office_manager',
    'operations_manager', 'it_manager', 'it_director', 'procurement',
    'other_decision_maker'
);
CREATE TYPE source_kind AS ENUM (
    'federal_registry', 'provincial_registry', 'municipal_open_data',
    'business_directory', 'company_website', 'manual', 'other'
);
CREATE TYPE job_status AS ENUM ('running', 'success', 'partial_failure', 'failed');
CREATE TYPE new_event_type AS ENUM (
    'new_today', 'new_7d', 'new_30d', 'recently_changed', 'new_location'
);

-- ---------------------------------------------------------------------------
-- CORE: businesses
-- ---------------------------------------------------------------------------
CREATE TABLE businesses (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    legal_name              TEXT,
    operating_name          TEXT,

    province                TEXT,               -- 2-letter code, e.g. 'ON'
    city                    TEXT,
    address_line1           TEXT,
    address_line2           TEXT,
    postal_code             TEXT,

    website                 TEXT,
    domain                  TEXT,                -- normalized (no scheme/www), used for dedup
    phone                   TEXT,                -- normalized E.164 where possible
    email                   TEXT,

    industry                TEXT,
    naics_code              TEXT,

    employee_count_min      INTEGER,
    employee_count_max      INTEGER,
    size_category            TEXT,                -- '1-4','5-9','10-19','20-49','50-99',
                                                    -- '100-199','200-499','500-999','1000+'
    size_confidence          size_confidence DEFAULT 'estimated',

    corporation_number       TEXT,                -- federal/provincial registry ID
    business_number          TEXT,                -- CRA BN9, when available
    incorporation_date        DATE,
    business_status           business_status DEFAULT 'unknown',

    quality_score             NUMERIC(5,2) DEFAULT 0,   -- 0-100
    lead_ready                 BOOLEAN DEFAULT FALSE,
    do_not_call                BOOLEAN DEFAULT FALSE,
    do_not_call_reason         TEXT,
    do_not_call_at             TIMESTAMPTZ,

    first_seen_at              TIMESTAMPTZ DEFAULT now(),
    last_verified_at           TIMESTAMPTZ,
    last_updated_at             TIMESTAMPTZ DEFAULT now(),
    created_at                  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_businesses_province_city ON businesses (province, city);
CREATE INDEX idx_businesses_industry ON businesses (industry);
CREATE INDEX idx_businesses_naics ON businesses (naics_code);
CREATE INDEX idx_businesses_size ON businesses (size_category);
CREATE INDEX idx_businesses_quality ON businesses (quality_score DESC);
CREATE INDEX idx_businesses_first_seen ON businesses (first_seen_at DESC);
CREATE INDEX idx_businesses_domain ON businesses (domain);
CREATE INDEX idx_businesses_name_trgm ON businesses USING gin (immutable_unaccent(coalesce(legal_name,'') || ' ' || coalesce(operating_name,'')) gin_trgm_ops);

-- ---------------------------------------------------------------------------
-- SOURCE HISTORY: every field we captured, per source, never overwritten
-- ---------------------------------------------------------------------------
CREATE TABLE business_field_sources (
    id              BIGSERIAL PRIMARY KEY,
    business_id     UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    field_name      TEXT NOT NULL,          -- e.g. 'phone', 'employee_count', 'address'
    field_value     TEXT NOT NULL,
    source_name     TEXT NOT NULL,          -- e.g. 'corporations_canada_federal'
    source_kind     source_kind NOT NULL,
    source_url      TEXT,
    confidence      NUMERIC(4,2) DEFAULT 0.5,  -- 0-1
    retrieved_at    TIMESTAMPTZ DEFAULT now(),
    is_current_pick BOOLEAN DEFAULT FALSE   -- flags which source value currently "wins" on businesses row
);

CREATE INDEX idx_bfs_business ON business_field_sources (business_id, field_name);
CREATE INDEX idx_bfs_source ON business_field_sources (source_name);

-- ---------------------------------------------------------------------------
-- DEDUP KEYS: normalized identifiers used to detect the same company
-- across sources (name hash, domain, phone, corp number, address hash...)
-- ---------------------------------------------------------------------------
CREATE TABLE business_identifiers (
    id            BIGSERIAL PRIMARY KEY,
    business_id   UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    key_type      TEXT NOT NULL,   -- 'name_hash' | 'domain' | 'phone' | 'corp_number' | 'address_hash' | 'postal_name'
    key_value     TEXT NOT NULL,
    UNIQUE (key_type, key_value, business_id)
);

CREATE INDEX idx_identifiers_lookup ON business_identifiers (key_type, key_value);

-- ---------------------------------------------------------------------------
-- CONTACTS / DECISION-MAKERS
-- ---------------------------------------------------------------------------
CREATE TABLE contacts (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    business_id     UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    full_name       TEXT,
    title_raw       TEXT,                 -- as found on source, e.g. "VP Operations"
    role_category   contact_role,
    email           TEXT,
    phone           TEXT,
    source_name     TEXT NOT NULL,
    source_url      TEXT,
    confidence      NUMERIC(4,2) DEFAULT 0.5,
    retrieved_at    TIMESTAMPTZ DEFAULT now(),
    is_active       BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_contacts_business ON contacts (business_id);
CREATE INDEX idx_contacts_role ON contacts (role_category);

-- ---------------------------------------------------------------------------
-- NEW-BUSINESS / CHANGE DETECTION FEED
-- ---------------------------------------------------------------------------
CREATE TABLE new_business_events (
    id              BIGSERIAL PRIMARY KEY,
    business_id     UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    event_type      new_event_type NOT NULL,
    detected_at     TIMESTAMPTZ DEFAULT now(),
    detail          JSONB              -- e.g. {"changed_fields": ["phone","address"]}
);

CREATE INDEX idx_new_events_type_time ON new_business_events (event_type, detected_at DESC);
CREATE INDEX idx_new_events_business ON new_business_events (business_id);

-- ---------------------------------------------------------------------------
-- JOB / PIPELINE LOGGING
-- ---------------------------------------------------------------------------
CREATE TABLE job_runs (
    id                  BIGSERIAL PRIMARY KEY,
    source_name         TEXT NOT NULL,
    job_type            TEXT NOT NULL,     -- 'collect' | 'enrich' | 'dedup' | 'score' | 'refresh'
    status              job_status DEFAULT 'running',
    started_at          TIMESTAMPTZ DEFAULT now(),
    finished_at         TIMESTAMPTZ,
    records_collected   INTEGER DEFAULT 0,
    records_new         INTEGER DEFAULT 0,
    records_updated     INTEGER DEFAULT 0,
    errors_count        INTEGER DEFAULT 0,
    error_detail        TEXT,
    notes               TEXT
);

CREATE INDEX idx_job_runs_source_time ON job_runs (source_name, started_at DESC);

-- ---------------------------------------------------------------------------
-- DO-NOT-CALL AUDIT TRAIL (separate from the businesses.do_not_call flag,
-- which is what the dialer/CRM should actually check before every call)
-- ---------------------------------------------------------------------------
CREATE TABLE do_not_call_requests (
    id              BIGSERIAL PRIMARY KEY,
    business_id     UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    requested_by    TEXT,             -- caller name / agent id who logged it
    channel         TEXT,             -- 'phone' | 'email' | 'website_form' | 'manual'
    note            TEXT,
    requested_at    TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- CONVENIENCE VIEW: sales-ready leads
-- ---------------------------------------------------------------------------
CREATE VIEW sales_ready_leads AS
SELECT *
FROM businesses
WHERE lead_ready = TRUE
  AND do_not_call = FALSE
  AND business_status = 'active';

-- ---------------------------------------------------------------------------
-- CONVENIENCE VIEW: today's new businesses
-- ---------------------------------------------------------------------------
CREATE VIEW new_businesses_today AS
SELECT b.*
FROM businesses b
JOIN new_business_events e ON e.business_id = b.id
WHERE e.event_type = 'new_today'
  AND e.detected_at >= date_trunc('day', now());
