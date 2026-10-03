# PROGRESS

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
