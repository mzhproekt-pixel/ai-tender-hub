-- Canonical manufacturers schema with provenance.
-- All raw API payloads land in entity_sources.raw (JSONB), normalised facets
-- are projected into the typed tables. Joining across sources happens via
-- entity_identifiers (LEI, CIK, INN, OGRN, BIN, etc.) and entity_matches.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Per-source ingestion runs, used for traceability and incremental updates.
CREATE TABLE IF NOT EXISTS ingestion_runs (
    id            BIGSERIAL PRIMARY KEY,
    source        TEXT        NOT NULL,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    status        TEXT        NOT NULL DEFAULT 'running',  -- running | ok | error
    rows_in       BIGINT      NOT NULL DEFAULT 0,
    rows_upserted BIGINT      NOT NULL DEFAULT 0,
    error         TEXT,
    params        JSONB       NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ingestion_runs_source_idx ON ingestion_runs(source, started_at DESC);

-- Canonical entity (legal person, manufacturer, trader).
CREATE TABLE IF NOT EXISTS entities (
    id              BIGSERIAL PRIMARY KEY,
    canonical_name  TEXT,
    name_norm       TEXT,                   -- ASCII-folded, lowercase, no legal-form suffixes
    country         CHAR(2),                -- ISO 3166-1 alpha-2
    legal_form      TEXT,
    status          TEXT,                   -- active | inactive | dissolved | unknown
    founded_on      DATE,
    dissolved_on    DATE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS entities_country_idx       ON entities(country);
CREATE INDEX IF NOT EXISTS entities_name_trgm_idx     ON entities USING gin (name_norm gin_trgm_ops);

-- Raw payload per (entity, source). Allows re-derivation without re-fetching.
CREATE TABLE IF NOT EXISTS entity_sources (
    id              BIGSERIAL PRIMARY KEY,
    entity_id       BIGINT      NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    source          TEXT        NOT NULL,    -- 'gleif' | 'sec_edgar' | 'un_comtrade' | ...
    source_ref      TEXT        NOT NULL,    -- LEI / CIK / partner code / ...
    raw             JSONB       NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id          BIGINT      REFERENCES ingestion_runs(id) ON DELETE SET NULL,
    UNIQUE (source, source_ref)
);
CREATE INDEX IF NOT EXISTS entity_sources_entity_idx ON entity_sources(entity_id);

-- External identifiers (LEI, CIK, INN, OGRN, BIN, IIN, DUNS, VAT, CRN ...).
CREATE TABLE IF NOT EXISTS entity_identifiers (
    id              BIGSERIAL PRIMARY KEY,
    entity_id       BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    scheme          TEXT   NOT NULL,
    value           TEXT   NOT NULL,
    source          TEXT   NOT NULL,
    UNIQUE (scheme, value)
);
CREATE INDEX IF NOT EXISTS entity_identifiers_entity_idx ON entity_identifiers(entity_id);

CREATE TABLE IF NOT EXISTS entity_addresses (
    id              BIGSERIAL PRIMARY KEY,
    entity_id       BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    kind            TEXT   NOT NULL DEFAULT 'legal',  -- legal | hq | mailing | branch
    country         CHAR(2),
    region          TEXT,
    city            TEXT,
    postal_code     TEXT,
    street          TEXT,
    raw             TEXT,
    source          TEXT   NOT NULL
);
CREATE INDEX IF NOT EXISTS entity_addresses_entity_idx ON entity_addresses(entity_id);

CREATE TABLE IF NOT EXISTS entity_contacts (
    id              BIGSERIAL PRIMARY KEY,
    entity_id       BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    kind            TEXT   NOT NULL,        -- email | phone | website | fax
    value           TEXT   NOT NULL,
    source          TEXT   NOT NULL,
    UNIQUE (entity_id, kind, value)
);

CREATE TABLE IF NOT EXISTS entity_officers (
    id              BIGSERIAL PRIMARY KEY,
    entity_id       BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    name            TEXT   NOT NULL,
    role            TEXT,
    appointed_on    DATE,
    resigned_on    DATE,
    source          TEXT   NOT NULL
);
CREATE INDEX IF NOT EXISTS entity_officers_entity_idx ON entity_officers(entity_id);

CREATE TABLE IF NOT EXISTS entity_financials (
    id              BIGSERIAL PRIMARY KEY,
    entity_id       BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    period_end      DATE,
    currency        CHAR(3),
    revenue         NUMERIC(20,2),
    net_income      NUMERIC(20,2),
    assets          NUMERIC(20,2),
    employees       INTEGER,
    source          TEXT   NOT NULL,
    UNIQUE (entity_id, period_end, source)
);

CREATE TABLE IF NOT EXISTS entity_products (
    id              BIGSERIAL PRIMARY KEY,
    entity_id       BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    name            TEXT   NOT NULL,
    description     TEXT,
    hs_code         TEXT,                   -- Harmonised System code, 2-6 digits
    naics           TEXT,
    nace            TEXT,
    source          TEXT   NOT NULL
);
CREATE INDEX IF NOT EXISTS entity_products_hs_idx ON entity_products(hs_code);

-- Aggregate trade flows (from UN Comtrade and similar). Country-level, not per-entity.
CREATE TABLE IF NOT EXISTS trade_flows (
    id              BIGSERIAL PRIMARY KEY,
    period          INTEGER NOT NULL,        -- YYYY or YYYYMM
    flow            TEXT    NOT NULL,        -- import | export | re-export | re-import
    reporter_iso    CHAR(3) NOT NULL,
    partner_iso     CHAR(3),
    hs_code         TEXT    NOT NULL,
    trade_value_usd NUMERIC(22,2),
    net_weight_kg   NUMERIC(22,3),
    qty             NUMERIC(22,3),
    qty_unit        TEXT,
    source          TEXT    NOT NULL,
    UNIQUE (source, period, flow, reporter_iso, partner_iso, hs_code)
);
CREATE INDEX IF NOT EXISTS trade_flows_hs_period_idx ON trade_flows(hs_code, period);

-- Cross-source matching. score in [0,1]; method describes the matcher.
CREATE TABLE IF NOT EXISTS entity_matches (
    id              BIGSERIAL PRIMARY KEY,
    entity_id_a     BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    entity_id_b     BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    score           NUMERIC(5,4) NOT NULL,
    method          TEXT   NOT NULL,
    decided         TEXT   NOT NULL DEFAULT 'pending', -- pending | merge | reject
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (entity_id_a < entity_id_b),
    UNIQUE (entity_id_a, entity_id_b, method)
);
