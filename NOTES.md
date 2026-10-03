# NOTES

Open questions, TO VERIFY items, and validation TODOs. Newest first.

## TO VERIFY / decide (from M2.1, 2026-10-04)

- **Accounting standard as a schema column?** Today the standard is NOT stored in SQLite. It is
  derived from (source document, PDF page) via `config/companies/tcs.yaml` at load and lookup
  time. Consequences: (1) the database alone does not say which standard a fact is in;
  (2) the `fact` UNIQUE constraint (company, metric, period, basis, source) means an Ind AS and an
  IFRS figure for the same metric/period/basis cannot both come from the same fact sheet.
  Adding `fact.accounting_standard` (and to the UNIQUE key) would fix both but changes the plan's
  DDL (Section 4.3). Author to decide.
- **Fact sheet pages with no stated standard** (4-12, 15, 19, 23: highlights, growth summaries,
  expense by nature, currency): which standard do they follow? Until set, facts cannot cite them.
  Page 15 "Expense by Nature" is in crore and footnoted "Excludes exceptional items".
- **Printing rounding** (`reporting_rounding`): INR crore whole, INR million whole, EPS 2 decimals,
  taken from the two documents we have. Check each new document.
- **Primary source for quarters**: exact match of `period_covered` to the fact's period label.
  A Q1 FY27 figure's primary is the Q1 FY27 fact sheet, not an FY27 annual report.
- **No-primary fallback**: when no document is "for" the period (e.g. FY25 figures from AR FY26
  only), the first-loaded row is returned. Fine while figures agree; revisit if it matters which
  page is cited.
- **Exceptional items**: net margin and net profit growth are statutory (after exceptional
  items). TCS's headline fact-sheet margins exclude them, so eval gold answers must say which
  basis they use.

## TO VERIFY / decide (from M2, 2026-10-04)

- ~~PAT margin definition~~ Resolved in M2.1: replaced by `net_margin` on profit attributable to
  shareholders (after non-controlling interests).
- **EPS growth**: uses reported basic EPS with no adjustment for bonus issues or splits. Check
  before comparing years where the share count changed for that reason.
- ~~Source precedence~~ Resolved in M2.1: duplicate-fact policy (PROJECT_PLAN.md 4.1 rule 8).
- **Two-digit years**: `FY26` is read as 2026. Labels before 2000 are not supported.
- **`code_version`** ends in `-dirty` whenever the working tree has uncommitted changes (including
  untracked files), so ratios computed before a commit are marked that way.
- Eval exclusion of unverified `llm_extracted` facts (plan 2.5) is a rule on paper only until M6/M7.

## TO VERIFY (from M1, 2026-10-04)

- **Plausibility bands** (`config/companies/tcs.yaml`) are provisional engineering guards set by Claude,
  roughly 2-3x around TCS's FY25/FY26 scale. Author to review once FY21+ figures are keyed; widen if any
  real figure falls outside.
- **`retrieved_on`** for both PDFs is the file date on disk (2026-10-03), not a recorded download date.
- **Annual report `published_date`** is blank. Only the auditor's report date (9 April 2026) was seen.
- **`ticker_bse`, `isin`, `licence_note`** are blank on purpose (not looked up).
- **Fact sheet `doc_type`** is set to `fact_sheet`, not `annual_report`. The M1 brief said
  `doc_type = annual_report`; that fits the annual report but not the Q1 FY27 fact sheet.
- **EPS**: the FY26 annual report prints one "Basic and diluted" EPS line. If a later year prints
  different basic and diluted figures, `eps_diluted` needs its own rows.

## Load-time validation: done vs TODO (PROJECT_PLAN.md 4.1 / 4.4)

Done in M1 (`src/erp/db/validate.py`, tested in `tests/test_load_facts.py`):
- unit = metric's canonical unit; reported unit must have a known conversion
- value = reported_value x conversion_factor (derived in code, then re-checked)
- every fact has a source page (positive whole number); printed page label stored if given
- plausibility band per metric (catches 10x and 1000x slips)
- duplicates rejected (within the CSV and against rows already in the DB)
- basis must be `consolidated` or `standalone`
- metric, period, ticker and source document must all be known from config
- source PDFs re-hashed against `sources_hashes.txt` when present
- a fact cannot cite a `generated_sample` document
- all-or-nothing: one bad row blocks the whole load

TODO (need data we don't have yet):
- [ ] Balance sheet: total assets = total equity + total liabilities (needs total_assets, liabilities)
      -- the M1 acceptance test mentions "broken balance"; cannot be built until these metrics exist.
- [ ] Cash flow: opening cash + net change = closing cash (needs cash-flow metrics)
- [ ] Q1+Q2+Q3+Q4 = FY for flow metrics, tolerance ~0.1% (needs quarterly facts; tolerance TO VERIFY)
- [x] Same fact from two sources must agree, else the load is rejected (M2.1)
- [x] Restatements via `restated` + `supersedes_source_doc` -> `supersedes_fact_id` (M2.1)
- [~] `verified_by` workflow: CSV columns `verified_by`/`verified_on` exist (M2); both required
      together; verifier must differ from `entered_by`. Double entry itself is a manual process.
