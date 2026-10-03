# PROGRESS

## 2026-10-04 — M2: periods, get_financial_fact, compute_ratio

**Done**
- Housekeeping: PROJECT_PLAN.md 2.5 bullet on LLM-read numbers rewritten as asked (loaded only as
  `llm_extracted` with `verified_by` empty; excluded from eval/gold/quoted results until the author
  verifies). Loader now reads optional CSV columns `verified_by`, `verified_on` (blank -> NULL).
  `data/sample/` not touched.
- `src/erp/periods.py`: `resolve_period` ('FY26', 'Q2 FY27' -> real dates), `label_for_dates`
  (dates -> label), `prior_year_label`. Fiscal year end month is passed in from company config.
- Config periods in `tcs.yaml` are now cross-checked against the resolver at load time.
- `src/erp/tools/facts.py`: `get_financial_fact(conn, ticker, metric_id, period_label, basis)` ->
  `FactResult` (pydantic): canonical and as-reported value/unit, fact_id, source document, PDF page
  and printed label, entry method, verified flag. Raises on unknown metric/period/ticker/basis,
  missing fact, or two current facts for the same thing.
- `config/ratios.yaml` + `src/erp/tools/ratios.py`: `compute_ratio(conn, ticker, ratio_id,
  period_label, basis)` for pat_margin, revenue_growth_yoy, pat_growth_yoy, eps_growth_yoy.
  Each call writes a `computed_metric` row (formula_version, inputs_json with fact_ids + formula +
  basis + verified, git SHA). Verified only if every input is.
- `src/erp/version.py`: git SHA (`-dirty` if uncommitted changes; `unknown` if no git).
- Tests: 141 passing (39 M1 + 102 new). Expected ratio values are hand-worked literals
  (arithmetic in test comments, cross-checked with `bc`).
- pydantic 2.13.5 added and pinned (with its dependencies).

**Decisions**
- Function signature is `get_financial_fact(conn, ticker, metric_id, period_label,
  basis="consolidated")`: the DB connection and ticker are explicit, so nothing company-specific
  is hard-coded. The M5 tool layer can wrap it.
- Period labels are strict: only `FY26` and `Q2 FY27` spellings. `fy26`, `FY2026`, `Q2FY26`
  raise. Two-digit years mean 20xx.
- The period table still gets explicit dates from config (plan 4.1 rule 3); the resolver checks
  them rather than replacing them.
- If two current facts match (same metric/period/basis from two documents), lookup refuses
  (`AmbiguousFactError`) instead of picking one. Source precedence is an open author decision.
- `computed_metric` DDL is unchanged; formula text, basis and verified flag are stored inside
  `inputs_json` next to `fact_ids` (the DDL has no columns for them).
- Every `compute_ratio` call appends a row (an audit log; no de-duplication).
- Growth over a zero or negative prior-year base raises instead of returning a number.
- Verification needs both `verified_by` and `verified_on`, and the verifier must differ from
  `entered_by`.

**Known issues / flags for the author**
- All 10 sample facts are still unverified, so every ratio on them reports `verified=False`.
- Plan M2 acceptance says "≥5 ratios"; this milestone was scoped to 4 ratio types. Tests check
  5 hand-calculated values (pat_margin for FY25 and FY26, plus the three FY26 growths).
- Plan M2 also lists `units.py`; nothing new was needed there for these ratios, so it is unchanged.
- Rule "LLM-read numbers don't count toward eval/gold/quoted results until verified" is written
  down but not yet enforced in code (the eval harness and verifier are M6/M7).

**Next**
- M3: DCF engine + checks + `run_dcf` (toy-case unit test from plan 2.5 Day 3).

---

## 2026-10-04 — M1: repo skeleton, SQLite schema, loader, validation

**Done**
- Skeleton: `src/erp/` (`config.py`, `units.py`, `db/schema.sql`, `db/validate.py`, `db/load_facts.py`),
  `config/` (`metrics.yaml`, `companies/tcs.yaml`), `tests/`, `pyproject.toml` (pytest config),
  pinned `requirements.txt`.
- Schema: copied from PROJECT_PLAN.md 4.3 unchanged (has `source_page_label` and `generated_sample`).
- Loader: CSV -> SQLite, all-or-nothing, reports every bad row with its CSV line number.
  Derives `value`, `unit`, `conversion_factor` from the metric's canonical unit; resolves periods and
  sources from config; `entry_method` passed on the command line (`llm_extracted` for the sample);
  `verified_by` always NULL.
- Validation: see NOTES.md for the done/TODO list.
- Tests: 39 passing (`.venv/bin/pytest`). Sample CSV loads: 10 facts, 0 verified.
- Spot check (by Claude, so it is NOT a human verification): all 10 sample values appear on the cited
  PDF pages (166 = printed 196, balance sheet; 167 = printed 197, P&L) with matching row labels;
  both PDF sha256 values match `sources_hashes.txt`.

**Decisions**
- Config lives in a new top-level `config/` folder (not `data/manual/`, which is author-owned).
- Periods are listed explicitly with real dates in the company config. No label parsing in M1;
  the period resolver is M2.
- Plausibility bands live in the company config (they are company-scale specific).
- The SQLite file (`data/db/sample.sqlite`) is a build artifact: gitignored, rebuilt with `--replace`.
- Fact sheet PDF is `doc_type = fact_sheet` (see NOTES.md).
- Added a guard (not in the brief): facts may not cite a `generated_sample` document.

**Known issues / flags for the author**
- PROJECT_PLAN.md 2.5 says "No LLM-generated number ever enters SQLite. Numbers are hand-typed."
  The sample rows were entered by Claude (`llm_extracted`), loaded at the author's explicit request.
  They stay unverified until the author checks them. Consider tightening later (e.g. tools refuse
  unverified `llm_extracted` facts) — not done, not in M1 scope.
- M1 acceptance test names `financials_tcs.csv` and a "broken balance" rejection. Neither is possible
  yet (no full CSV; no total assets/liabilities metrics). Tested on `data/sample/facts_sample.csv`.

**Next**
- M2: `periods.py` (FY/Q label <-> dates), `units.py` extension, `get_financial_fact`,
  `compute_ratio` + `computed_metric` writes.

**How to run**
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pytest
PYTHONPATH=src .venv/bin/python -m erp.db.load_facts --csv data/sample/facts_sample.csv --entry-method llm_extracted --replace
```
