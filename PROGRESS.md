# PROGRESS

## 2026-10-04 — M3: DCF engine, assumptions loader, checks, run_dcf

**Done**
- `src/erp/dcf/engine.py` (pure arithmetic, no LLM, no database, no market price):
  `build_fcff` (FCFF from drivers, plan 5.1; other income excluded), `cost_of_equity`,
  `compute_wacc` (all-equity is `debt_weight = 0`), `equity_bridge`, `value_firm` (discount
  factors, PV per year, terminal value, PV of TV, EV, equity, per share, TV % of EV),
  `sensitivity_grid` (WACC x terminal growth). Every function returns its intermediates.
- `src/erp/dcf/assumptions.py`: reads the assumptions YAML (`shared` block + named scenarios,
  scenario keys override shared). Refuses on a missing/blank rationale or source anywhere in
  the file, naming the assumption and block; also on unknown names, rates written as percents
  (12 instead of 0.12), wrong-length per-year lists, non-positive shares, horizon < 1.
- `src/erp/dcf/checks.py`: required inputs present (blocking), terminal growth < WACC
  (blocking), terminal growth < risk-free (stored fail, not blocking), TV share of EV inside a
  warning band (stored warn).
- `src/erp/dcf/run.py`: `run_dcf(conn, ticker, scenario, assumptions_path=...)` -> `DCFResult`
  and one `dcf_run` row (full YAML text + sha256 + resolved assumptions; every intermediate;
  checks; git SHA). A failed blocking check refuses and stores nothing.
- `config/dcf.yaml`: TV warning band and sensitivity offsets (method settings, not assumptions).
- `src/erp/units.py`: money units (INR, INR_MILLION, INR_CRORE) and share units for per-share.
- Toy fixture `tests/fixtures/dcf_toy_assumptions.yaml` (clearly labelled NOT TCS), commented
  as the format guide for the real file.
- Tests: 252 passing (71 new). Toy case: 153.273278... per share, TV 80.97% of EV; every
  intermediate checked against hand arithmetic cross-checked with `bc`.

**Decisions**
- Year-end discounting, whole years: DF_t = 1/(1+WACC)^t (TO VERIFY; mid-year not built).
- Terminal value: Gordon growth on FCFF_n x (1 + g), valued at end of year n.
- WACC must exceed g by more than 1e-9: in floating point 0.07 + 1.0 x 0.05 = 0.12000000000000001,
  so g = 0.12 would otherwise pass and give a near-infinite TV (found by a test).
- Final-year FCFF must be positive (Gordon growth on zero/negative FCFF is meaningless).
- Rates are decimals in the YAML. Value per share is always INR per share.
- Tax rate for the interest tax shield is its own assumption (`debt_tax_rate`).
- Base-year revenue and bridge items come from the YAML (with sources), not SQLite, for now.
- Assumptions YAML default path: `data/manual/dcf_inputs.yaml` (not created; author-owned).

**Known issues / flags for the author**
- Plan M3 acceptance = golden test vs the hand spreadsheet (P0.3). Not possible yet; only the
  toy-case unit tests exist. M3 is "engine done, golden test pending".
- TV warning band 50%-85% in `config/dcf.yaml` is a placeholder chosen by Claude (TO VERIFY).
- Plan 5.3 items not built (need SQLite history): see NOTES.md TODO list.

**Next**
- M4: annual report PDF -> chunks with page numbers -> ChromaDB (not started).

---
## 2026-10-04 — M2.1: net margin, duplicate-fact policy (housekeeping)

**Done**
- New metric `profit_attributable_to_owners` (INR crore, flow; statutory, after exceptional
  items, after non-controlling interests). `profit_after_tax` definition reworded to
  "profit for the year, including non-controlling interests". Plausibility band added.
- Ratios: `pat_margin` -> `net_margin`, `pat_growth_yoy` -> `net_profit_growth_yoy` (both on
  profit_attributable_to_owners). Every ratio definition states "statutory, after exceptional
  items" and that TCS's fact-sheet headline margins exclude exceptional items.
- Duplicate-fact policy (new `src/erp/db/duplicates.py`, loader, `get_financial_fact`):
  primary source by `period_covered`; agreeing figures kept as `cross_checked_by`;
  disagreeing figures rejected with both values, sources and pages; restatements via CSV
  columns `restated` + `supersedes_source_doc` (stored as `restated` / `supersedes_fact_id`),
  returned by default, original available with `as_first_reported=True`; comparisons only
  within one accounting standard.
- Config: `primary_accounting_standard`, per-source `accounting_standard` /
  `accounting_standard_by_page`, `reporting_rounding` (printing step per reported unit), all in
  `config/companies/tcs.yaml`. `period_covered` must be a valid period label.
- PROJECT_PLAN.md 4.1: rule 3 note on the period resolver; new rule 8 (duplicate facts).
- Fixed a duplicated paragraph in the `load_facts.py` docstring (left over from M2).
- Tests: 181 total. In this checkout 170 pass and 11 fail; all 11 need the author's two
  `profit_attributable_to_owners` rows in `data/sample/facts_sample.csv`. With those two rows
  added to a scratch copy of the repo: 180 passed, 1 skipped (PDF hash test; PDFs not copied).

**Decisions**
- Accounting standard is NOT a schema column (TO VERIFY, see NOTES.md). It is worked out from
  the source document and page via config, at load time and at lookup time. So
  `get_financial_fact` reads the company config (`config/companies/<ticker>.yaml`, or a
  `ctx=` argument).
- Fact sheet standards from the page headings: IFRS = PDF pages 14, 16, 17, 18, 20; Ind AS =
  21, 22. Other pages have no configured standard, so facts cannot cite them yet.
- "Primary source" = document whose `period_covered` equals the fact's period label exactly
  (FY26 fact -> AR FY26; Q1 FY27 fact -> Q1 FY27 fact sheet). If none, the first-loaded row is
  returned and `primary_source` is False (true for all FY25 sample facts today).
- "Agree" = difference no more than half of each figure's printing step added together
  (e.g. whole crore vs whole million: 0.5 + 0.05 crore).
- Restatement checks: a restated row needs the row it replaces to be loaded first (database or
  earlier in the CSV); rows restating the same figure must agree; a later restatement may
  supersede an earlier one. Ordinary rows must agree with other ordinary rows (the figures as
  first published).
- Every source must declare a standard (stricter than "if a source carries one").

**Known issues / flags for the author**
- 11 tests fail until you add the two CSV rows (see "what to check").
- Schema can't hold an Ind AS and an IFRS figure for the same metric/period/basis from the
  SAME document (UNIQUE constraint has no standard). See NOTES.md.
- Lookup-time standard depends on config matching the database; if a source is renamed in
  config, lookups on old rows fail loudly.

**Next**
- M3: DCF engine + checks + `run_dcf`.

---

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
