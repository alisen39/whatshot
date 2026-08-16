"""Versioned DuckDB schema definitions owned by the Scheduler writer."""

from __future__ import annotations

SCHEMA_VERSION = 3

# Version 1 is intentionally retained verbatim so a new database and a legacy
# database travel through the same ordered migration chain.
SCHEMA_V1_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS scheduler_runs (
    run_id VARCHAR PRIMARY KEY,
    run_key VARCHAR UNIQUE NOT NULL,
    job_id VARCHAR NOT NULL,
    trigger_kind VARCHAR NOT NULL,
    scheduled_for TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status VARCHAR NOT NULL,
    attempt INTEGER NOT NULL,
    error_code VARCHAR,
    error_message VARCHAR,
    capture_id VARCHAR
);

CREATE TABLE IF NOT EXISTS captures (
    capture_id VARCHAR PRIMARY KEY,
    run_key VARCHAR UNIQUE NOT NULL,
    job_id VARCHAR NOT NULL,
    site VARCHAR NOT NULL,
    board_key VARCHAR NOT NULL,
    path_type VARCHAR NOT NULL,
    params_json JSON NOT NULL,
    kind VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    type_label VARCHAR NOT NULL,
    scheduled_for TIMESTAMPTZ NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    response_update_at TIMESTAMPTZ NOT NULL,
    item_count INTEGER NOT NULL,
    content_hash VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS hotlist_observations (
    capture_id VARCHAR NOT NULL,
    site VARCHAR NOT NULL,
    board_key VARCHAR NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    position INTEGER NOT NULL,
    source_item_id VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    url VARCHAR NOT NULL,
    mobile_url VARCHAR,
    hot BIGINT,
    author VARCHAR,
    description VARCHAR,
    cover_url VARCHAR,
    published_at TIMESTAMPTZ,
    PRIMARY KEY (capture_id, position)
);

CREATE TABLE IF NOT EXISTS newsflash_occurrences (
    capture_id VARCHAR NOT NULL,
    site VARCHAR NOT NULL,
    board_key VARCHAR NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    position INTEGER NOT NULL,
    source_item_id VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    content VARCHAR NOT NULL,
    summary VARCHAR,
    content_status VARCHAR NOT NULL,
    url VARCHAR NOT NULL,
    mobile_url VARCHAR,
    source VARCHAR,
    is_important BOOLEAN NOT NULL,
    tags_json JSON NOT NULL,
    images_json JSON NOT NULL,
    symbols_json JSON NOT NULL,
    metrics_json JSON NOT NULL,
    published_at TIMESTAMPTZ,
    PRIMARY KEY (capture_id, position)
);

CREATE TABLE IF NOT EXISTS gold_observations (
    capture_id VARCHAR NOT NULL,
    site VARCHAR NOT NULL,
    board_key VARCHAR NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    source_item_id VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    sell_price BIGINT,
    recycle_price BIGINT,
    description VARCHAR,
    price_date TIMESTAMPTZ,
    url VARCHAR NOT NULL,
    PRIMARY KEY (capture_id, source_item_id)
);

CREATE INDEX IF NOT EXISTS idx_captures_site_board_time
ON captures(site, board_key, observed_at);

CREATE INDEX IF NOT EXISTS idx_hotlist_site_board_time
ON hotlist_observations(site, board_key, observed_at);

CREATE INDEX IF NOT EXISTS idx_hotlist_item_time
ON hotlist_observations(site, board_key, source_item_id, observed_at);

CREATE OR REPLACE VIEW history_items AS
SELECT
    h.capture_id,
    'hotlist' AS kind,
    h.site,
    h.board_key,
    h.observed_at,
    h.source_item_id AS item_id,
    h.position AS rank,
    h.title,
    h.url,
    h.mobile_url,
    h.hot,
    h.author AS source,
    h.description,
    CAST(NULL AS VARCHAR) AS content,
    h.published_at,
    CAST(NULL AS BIGINT) AS sell_price,
    CAST(NULL AS BIGINT) AS recycle_price
FROM hotlist_observations h
UNION ALL
SELECT
    o.capture_id,
    'newsflash' AS kind,
    o.site,
    o.board_key,
    o.observed_at,
    o.source_item_id AS item_id,
    o.position AS rank,
    o.title,
    o.url,
    o.mobile_url,
    CAST(NULL AS BIGINT) AS hot,
    o.source,
    o.summary AS description,
    o.content,
    o.published_at,
    CAST(NULL AS BIGINT) AS sell_price,
    CAST(NULL AS BIGINT) AS recycle_price
FROM newsflash_occurrences o
UNION ALL
SELECT
    g.capture_id,
    'gold' AS kind,
    g.site,
    g.board_key,
    g.observed_at,
    g.source_item_id AS item_id,
    CAST(NULL AS INTEGER) AS rank,
    g.title,
    g.url,
    CAST(NULL AS VARCHAR) AS mobile_url,
    CAST(NULL AS BIGINT) AS hot,
    CAST(NULL AS VARCHAR) AS source,
    g.description,
    CAST(NULL AS VARCHAR) AS content,
    g.price_date AS published_at,
    g.sell_price,
    g.recycle_price
FROM gold_observations g;
"""

SCHEMA_MIGRATIONS_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'completed',
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_message VARCHAR,
    backup_path VARCHAR,
    backup_sha256 VARCHAR
);
"""

HISTORY_ITEMS_V2_SQL = """
CREATE OR REPLACE VIEW history_items AS
SELECT
    h.ingest_sequence,
    h.search_text_normalized,
    h.capture_id,
    'hotlist' AS kind,
    h.site,
    h.board_key,
    h.observed_at,
    h.source_item_id AS item_id,
    h.position AS rank,
    h.title,
    h.url,
    h.mobile_url,
    h.hot,
    h.author AS source,
    h.description,
    CAST(NULL AS VARCHAR) AS content,
    h.published_at,
    CAST(NULL AS BIGINT) AS sell_price,
    CAST(NULL AS BIGINT) AS recycle_price
FROM hotlist_observations h
UNION ALL
SELECT
    o.ingest_sequence,
    o.search_text_normalized,
    o.capture_id,
    'newsflash' AS kind,
    o.site,
    o.board_key,
    o.observed_at,
    o.source_item_id AS item_id,
    o.position AS rank,
    o.title,
    o.url,
    o.mobile_url,
    CAST(NULL AS BIGINT) AS hot,
    o.source,
    COALESCE(o.summary, o.content) AS description,
    o.content,
    o.published_at,
    CAST(NULL AS BIGINT) AS sell_price,
    CAST(NULL AS BIGINT) AS recycle_price
FROM newsflash_occurrences o
UNION ALL
SELECT
    g.ingest_sequence,
    g.search_text_normalized,
    g.capture_id,
    'gold' AS kind,
    g.site,
    g.board_key,
    g.observed_at,
    g.source_item_id AS item_id,
    CAST(NULL AS INTEGER) AS rank,
    g.title,
    g.url,
    CAST(NULL AS VARCHAR) AS mobile_url,
    CAST(NULL AS BIGINT) AS hot,
    CAST(NULL AS VARCHAR) AS source,
    g.description,
    CAST(NULL AS VARCHAR) AS content,
    g.price_date AS published_at,
    g.sell_price,
    g.recycle_price
FROM gold_observations g;
"""

GOLD_QUOTES_V3_SQL = """
ALTER TABLE gold_observations ADD COLUMN IF NOT EXISTS metal VARCHAR DEFAULT 'gold';
ALTER TABLE gold_observations ADD COLUMN IF NOT EXISTS quotes_json JSON;

CREATE TABLE IF NOT EXISTS gold_quote_observations (
    capture_id VARCHAR NOT NULL,
    site VARCHAR NOT NULL,
    board_key VARCHAR NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    source_item_id VARCHAR NOT NULL,
    quote_index INTEGER NOT NULL,
    series_key VARCHAR NOT NULL,
    quote_type VARCHAR NOT NULL,
    label VARCHAR NOT NULL,
    price DECIMAL(30, 10) NOT NULL,
    currency VARCHAR NOT NULL,
    unit VARCHAR NOT NULL,
    source_quote_at TIMESTAMPTZ,
    source_quote_time_trusted BOOLEAN NOT NULL,
    PRIMARY KEY (capture_id, source_item_id, quote_index)
);

"""

HISTORY_ITEMS_V3_SQL = """
CREATE OR REPLACE VIEW history_items AS
SELECT
    h.ingest_sequence,
    h.search_text_normalized,
    h.capture_id,
    'hotlist' AS kind,
    h.site,
    h.board_key,
    h.observed_at,
    h.source_item_id AS item_id,
    h.position AS rank,
    h.title,
    h.url,
    h.mobile_url,
    h.hot,
    h.author AS source,
    h.description,
    CAST(NULL AS VARCHAR) AS content,
    h.published_at,
    CAST(NULL AS BIGINT) AS sell_price,
    CAST(NULL AS BIGINT) AS recycle_price,
    CAST(NULL AS VARCHAR) AS metal,
    CAST(NULL AS JSON) AS quotes_json
FROM hotlist_observations h
UNION ALL
SELECT
    o.ingest_sequence,
    o.search_text_normalized,
    o.capture_id,
    'newsflash' AS kind,
    o.site,
    o.board_key,
    o.observed_at,
    o.source_item_id AS item_id,
    o.position AS rank,
    o.title,
    o.url,
    o.mobile_url,
    CAST(NULL AS BIGINT) AS hot,
    o.source,
    COALESCE(o.summary, o.content) AS description,
    o.content,
    o.published_at,
    CAST(NULL AS BIGINT) AS sell_price,
    CAST(NULL AS BIGINT) AS recycle_price,
    CAST(NULL AS VARCHAR) AS metal,
    CAST(NULL AS JSON) AS quotes_json
FROM newsflash_occurrences o
UNION ALL
SELECT
    g.ingest_sequence,
    g.search_text_normalized,
    g.capture_id,
    'gold' AS kind,
    g.site,
    g.board_key,
    g.observed_at,
    g.source_item_id AS item_id,
    CAST(NULL AS INTEGER) AS rank,
    g.title,
    g.url,
    CAST(NULL AS VARCHAR) AS mobile_url,
    CAST(NULL AS BIGINT) AS hot,
    CAST(NULL AS VARCHAR) AS source,
    g.description,
    CAST(NULL AS VARCHAR) AS content,
    g.price_date AS published_at,
    g.sell_price,
    g.recycle_price,
    g.metal,
    g.quotes_json
FROM gold_observations g;
"""

V2_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_captures_site_board_time
ON captures(site, board_key, observed_at);

CREATE INDEX IF NOT EXISTS idx_hotlist_site_board_sequence
ON hotlist_observations(site, board_key, observed_at, ingest_sequence);

CREATE INDEX IF NOT EXISTS idx_hotlist_item_time
ON hotlist_observations(site, board_key, source_item_id, observed_at);

CREATE INDEX IF NOT EXISTS idx_newsflash_site_board_sequence
ON newsflash_occurrences(site, board_key, observed_at, ingest_sequence);

CREATE INDEX IF NOT EXISTS idx_gold_site_board_sequence
ON gold_observations(site, board_key, observed_at, ingest_sequence);

CREATE UNIQUE INDEX IF NOT EXISTS idx_hotlist_ingest_sequence
ON hotlist_observations(ingest_sequence);

CREATE UNIQUE INDEX IF NOT EXISTS idx_newsflash_ingest_sequence
ON newsflash_occurrences(ingest_sequence);

CREATE UNIQUE INDEX IF NOT EXISTS idx_gold_ingest_sequence
ON gold_observations(ingest_sequence);
"""

# Temporary compatibility alias for code/tests importing the old constant.
SCHEMA_SQL = SCHEMA_V1_SQL
