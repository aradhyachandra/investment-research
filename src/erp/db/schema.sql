-- SQLite schema, copied from PROJECT_PLAN.md Section 4.3.
-- Rules enforced in the loader rather than here (see src/erp/db/validate.py):
--   fact.unit = metric.canonical_unit, value = reported_value * conversion_factor,
--   plausibility bands, period labels resolved to real dates from config.

PRAGMA foreign_keys = ON;

CREATE TABLE company (
  company_id            INTEGER PRIMARY KEY,
  ticker_nse            TEXT NOT NULL UNIQUE,          -- 'TCS'
  ticker_bse            TEXT,                          -- (to verify)
  isin                  TEXT,                          -- (to verify)
  name                  TEXT NOT NULL,
  fiscal_year_end_month INTEGER NOT NULL DEFAULT 3,
  reporting_currency    TEXT NOT NULL DEFAULT 'INR'
);

CREATE TABLE source_document (
  source_id      INTEGER PRIMARY KEY,
  company_id     INTEGER NOT NULL REFERENCES company(company_id),
  doc_type       TEXT NOT NULL CHECK (doc_type IN
                   ('annual_report','quarterly_results','fact_sheet',
                    'investor_presentation','press_release','analyst_note',
                    'generated_sample','other')),
  title          TEXT NOT NULL,
  publisher      TEXT NOT NULL,
  url            TEXT,
  local_path     TEXT,              -- path inside the local checkout of the private data repo
  published_date TEXT,              -- ISO date
  period_covered TEXT,              -- e.g. 'FY25'
  sha256         TEXT,              -- of the file, for traceability
  retrieved_on   TEXT NOT NULL,
  licence_note   TEXT               -- terms of use as you understood them (to verify)
);

CREATE TABLE metric (
  metric_id   TEXT PRIMARY KEY,     -- 'revenue_from_operations'
  display_name TEXT NOT NULL,
  statement   TEXT NOT NULL CHECK (statement IN ('income','balance_sheet','cash_flow','other')),
  unit_kind   TEXT NOT NULL CHECK (unit_kind IN ('currency','per_share','shares','percent','count','days')),
  canonical_unit TEXT NOT NULL CHECK (canonical_unit IN
                   ('INR_CRORE','INR_PER_SHARE','SHARES_CRORE','PERCENT','COUNT','DAYS')),
  is_flow     INTEGER NOT NULL CHECK (is_flow IN (0,1)),   -- 1 = over a period, 0 = point in time
  definition  TEXT NOT NULL         -- exact definition incl. what is included/excluded
);

CREATE TABLE period (
  period_id   INTEGER PRIMARY KEY,
  company_id  INTEGER NOT NULL REFERENCES company(company_id),
  period_type TEXT NOT NULL CHECK (period_type IN ('FY','Q1','Q2','Q3','Q4')),
  fiscal_year INTEGER NOT NULL,     -- FY ending Mar 2025 => 2025
  label       TEXT NOT NULL,        -- 'FY25', 'Q2 FY26'
  start_date  TEXT NOT NULL,
  end_date    TEXT NOT NULL,
  UNIQUE (company_id, period_type, fiscal_year)
);

CREATE TABLE fact (
  fact_id          INTEGER PRIMARY KEY,
  company_id       INTEGER NOT NULL REFERENCES company(company_id),
  metric_id        TEXT    NOT NULL REFERENCES metric(metric_id),
  period_id        INTEGER NOT NULL REFERENCES period(period_id),
  basis            TEXT    NOT NULL CHECK (basis IN ('consolidated','standalone')),
  value            REAL    NOT NULL,            -- in the metric's canonical unit
  unit             TEXT    NOT NULL,            -- must equal metric.canonical_unit (enforced in loader + test)
  currency         TEXT    NOT NULL DEFAULT 'INR',
  reported_value   REAL    NOT NULL,            -- exactly as printed
  reported_unit    TEXT    NOT NULL,            -- e.g. 'INR_CRORE','INR_MILLION'
  conversion_factor REAL   NOT NULL,            -- value = reported_value * conversion_factor
  source_id        INTEGER NOT NULL REFERENCES source_document(source_id),
  source_page      INTEGER NOT NULL,           -- PDF page index (1-based)
  source_page_label TEXT,                      -- page number printed on the page, if different
  source_locator   TEXT,                        -- e.g. 'Consolidated Statement of Profit and Loss, line 1'
  entry_method     TEXT NOT NULL CHECK (entry_method IN ('manual','parsed','llm_extracted')),
  entered_by       TEXT NOT NULL,
  verified_by      TEXT,                        -- second pair of eyes, or NULL
  verified_on      TEXT,
  restated         INTEGER NOT NULL DEFAULT 0,
  supersedes_fact_id INTEGER REFERENCES fact(fact_id),
  UNIQUE (company_id, metric_id, period_id, basis, source_id)
);

CREATE VIEW fact_current AS
SELECT f.* FROM fact f
WHERE NOT EXISTS (SELECT 1 FROM fact g WHERE g.supersedes_fact_id = f.fact_id);

CREATE TABLE computed_metric (
  computed_id     INTEGER PRIMARY KEY,
  company_id      INTEGER NOT NULL REFERENCES company(company_id),
  ratio_id        TEXT NOT NULL,                 -- 'operating_margin'
  period_id       INTEGER NOT NULL REFERENCES period(period_id),
  value           REAL NOT NULL,
  unit            TEXT NOT NULL,
  formula_version TEXT NOT NULL,
  inputs_json     TEXT NOT NULL,                 -- list of fact_ids used
  code_version    TEXT NOT NULL,                 -- git sha
  computed_at     TEXT NOT NULL
);

CREATE TABLE dcf_run (
  run_id           INTEGER PRIMARY KEY,
  company_id       INTEGER NOT NULL REFERENCES company(company_id),
  scenario_name    TEXT NOT NULL,
  valuation_date   TEXT NOT NULL,
  assumptions_json TEXT NOT NULL,                -- full copy of the YAML used
  outputs_json     TEXT NOT NULL,                -- every intermediate value
  checks_json      TEXT NOT NULL,                -- pass/fail sanity checks
  code_version     TEXT NOT NULL,
  run_at           TEXT NOT NULL
);
