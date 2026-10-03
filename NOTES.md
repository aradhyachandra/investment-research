# NOTES

Open questions, TO VERIFY items, and validation TODOs. Newest first.

## TO VERIFY / decide (from M4, 2026-10-04)

**PDF extraction quality (FY26 annual report, PyMuPDF 1.28.2)**
- **Chunk text is never a source of numbers.** Numbers in extracted text are often mangled:
  stray spaces inside figures ("2, 7 1, 423" for 2,71,423), digits split across lines, table
  cells on separate lines. Numbers come from SQLite only; chunks answer qualitative questions.
- **Table-heavy flag.** `is_table_heavy` is set when >= 30% of a chunk's lines are numbers-only
  or >= 50% of its tokens are numbers (`config/ingest.yaml`, thresholds chosen by eye, TO VERIFY).
  229 of 1118 annual report chunks are flagged. `search_documents` multiplies their score by 0.85
  (TO VERIFY, arbitrary). Side effect seen: a qualitative sentence sitting inside a table chunk is
  penalised too (e.g. "no single customer is 10% or more of revenue", PDF 226).
- **Letter-spaced text.** On about 30 pages (mostly the designed intro spreads, PDF 5-31, plus
  some headings) words come out split: "T C S ’ I nteg rated". The spaces are real characters in
  the PDF (fonts with zero-width glyphs), so they are left as they are; any repair would be a guess.
  Retrieval on those pages is weaker.
- **Broken glyph mapping.** Some text has a wrong character map, e.g. PDF 24 (Financial Capital)
  "deĐůared three interiŵ diǀidends", PDF 37 "Đonsideration". Left as is.
- **No embedded page labels or bookmarks.** Printed page numbers are configured per source in
  `config/companies/tcs.yaml` (`page_labels`), read by Claude from the footers. TO VERIFY (author).
  AR: PDF 4-33 are two-page spreads (PDF 4 = printed 4|5), PDF 34-358 = printed 64-388;
  PDF 1-3 and 359-360 print no number. Fact sheet: slide number = PDF index, where printed.
- **Footer digits missing from the text layer** on 57 AR pages (e.g. PDF 60 prints "90" but only
  "9" is extractable). The ingest re-reads every footer and compares with the config: today
  0 contradictions, 57 "missing digits" (config kept). Fact sheet: 0 warnings.
- **Section detection is coarse.** A section is the latest bold line >= 1.5 pt above body size.
  Many sub-headings (e.g. each MD&A risk title, "Cyber Attacks (R & O)") are body-size bold and
  are not detected, so e.g. PDF 61-67 all carry "Enterprise Risk Management". Some section names
  are letter-spaced or carry footnote digits ("H uman Capital1").
- **Reading order** follows the PDF's own text order (not sorted by position), which keeps the
  two columns apart on TCS pages. Not checked page by page.

**Embeddings and the vector store**
- **nomic-embed-text task prefixes** ("search_document: ", "search_query: ") are added in code
  (`config/ingest.yaml`). TO VERIFY that Ollama does not also add them.
- **Chroma must never embed by itself.** Found while testing: with `embedding_function=None`,
  calling Chroma with `query_texts` downloaded its default ONNX model (~80 MB) from the internet.
  The collection now has an embedding function that always refuses; a test covers it. That one
  test download is in `~/.cache/chroma/onnx_models/` on the author's laptop (outside the repo).
- **Telemetry** is turned off (`anonymized_telemetry=False`). TO VERIFY that Chroma 1.5.9 makes
  no other outbound calls.
- **Score** = 1 - cosine distance. Not comparable across embedding models.
- **Licensing**: PyMuPDF is AGPL-3.0 (or commercial). TO VERIFY it is acceptable for this repo.
- **Re-index triggers**: registered sha256 changed, or embedding model name changed. A document
  removed from config is NOT removed from Chroma (delete `data/chroma/` to rebuild).
- **source_id stability**: ids are assigned when `load_facts --replace` seeds `source_document`
  in config order. Reordering or inserting sources in `tcs.yaml` changes the ids and leaves Chroma
  pointing at old ones. Until this is guarded, delete `data/chroma/` and re-index after any such change.
- Indexing the AR + fact sheet took ~60 s with peak memory ~245 MB (batches of 16).

**Retrieval baseline (PROVISIONAL, not the eval)**
- 12 probes in `tests/provisional_retrieval_probes.jsonl`, written by Claude from its own reading.
  recall@5 = 9 of 12, recall@10 = 11 of 12 (2026-10-04). Expected pages are Claude's judgement and
  may be too narrow (PROV-10: top hits were PDF 13-14 "AI-led transformation at TCS", arguably
  relevant). PROV-05 is sensitive to wording ("of revenue" finds PDF 293 at rank 3; "of TCS's
  revenue" misses). No threshold set; the real target comes from the author's P0.4 questions.

## TO VERIFY / decide (from M3, 2026-10-04)

- **Discounting convention**: year-end, whole years (DF_t = 1/(1+WACC)^t). Mid-year
  (t - 0.5) is a common alternative; not implemented. Must match the hand spreadsheet.
- **Stub period**: the valuation date is assumed to be the base fiscal year end. A valuation
  date part-way through a year is not handled.
- **Leases**: `lease_liabilities` is subtracted in the bridge. If leases are instead treated as
  operating costs inside EBIT, set it to 0 and say so in the rationale. Decide with the finance
  partner (plan 5.1: consistency between EBIT and the bridge).
- **Terminal growth >= risk-free rate**: stored as a failed check but the run still completes.
  Plan says "must be below"; confirm whether it should refuse.
- **TV share warning band** 50%-85% (`config/dcf.yaml`) is a placeholder, not sourced.
- **Negative EBIT** gives a tax credit in `EBIT x (1 - tax)`. Irrelevant for TCS; flag if used.
- **Tax shield rate** is a separate assumption (`debt_tax_rate`), not the cash tax rate.
- **Float tolerance**: WACC must exceed g by more than 1e-9.

## DCF checks: done vs TODO (PROJECT_PLAN.md 5.3)

Done in M3 (`src/erp/dcf/checks.py`, stored in `dcf_run.checks_json`):
- required assumptions present (blocking); terminal growth < WACC (blocking);
  terminal growth < risk-free rate (fail, not blocking); TV share of EV in band (warn)
- every assumption has a non-empty rationale and source (loader refuses otherwise)

TODO (need historical facts in SQLite; today only 5 metrics are loaded):
- [ ] Historical growth, margins, tax rate, D&A %, capex %, NWC changes shown beside assumptions
- [ ] Margin / growth jumps vs history flagged
- [ ] Historical FCFF
- [ ] Bridge items (cash, investments, debt, leases, minorities) and base-year revenue taken
      from the latest balance-sheet / P&L facts, with fact_ids, instead of the YAML
- [ ] All required facts present and from the same basis and period
- [ ] Implied multiples (implied EV/EBITDA, implied P/E)
- [ ] Golden test vs the hand spreadsheet (base within 0.1% + 2 more scenarios) after P0.3

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
