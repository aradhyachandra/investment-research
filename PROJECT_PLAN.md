# PROJECT_PLAN.md — AI-Powered Equity Research Platform (Indian Equities)

> Purpose: a cold-start brief. A coding tool (Claude Code, Antigravity, anything else) should be able to read this file and know what to build, in what order, how to test it, and what NOT to do.
> Status of repo when this was written: **empty. No code, no data, no DCF outputs, no digitized reports.**
> Anything marked **(to verify)** is something I (the planner) am not sure of. Verify before relying on it.
> This is a learning/portfolio project. **It is not investment advice and must never claim to be.**

---

## 0. One-paragraph summary

Give the system a ticker (v1: **TCS only**). It answers research questions by combining three things: exact financial numbers from SQLite, qualitative text from ChromaDB (filings + the author's own research notes), and a deterministic DCF/ratio engine written in plain Python. An LLM routes the question and explains results, but **never does arithmetic and never states a number that did not come from a tool**. Every claim in an answer carries a source (document + page) or a calculation path (formula + input fact IDs). A verifier rejects answers that contain unsupported numbers.

**Core principle: AI interprets, code calculates, sources prove.**

**Not building:** a price predictor, a trading bot, buy/sell/hold or target-price output, an LLM that does its own math, a generic "chat with a PDF" app.

---

## 1. Decisions review (challenges to the original direction)

| Decision | Verdict | Why / what changes |
|---|---|---|
| SQLite for numbers + ChromaDB for text | **Keep** | Right split. Numbers need exact lookup and constraints; text needs similarity search. Keep both past the prototype for a single-user project; revisit only at multi-company/multi-user scale. |
| LangChain tool-calling agent | **Keep the idea, thin the framework** | Write tools as plain, typed Python functions (pydantic in/out) that work without any LLM. Put the agent loop on top. LangChain's agent APIs have changed a lot over time and LangGraph is now the usual recommendation (to verify). Don't let the framework own your business logic. |
| Local LLM (Llama 3.2) | **Risk, test early** | Small local models are unreliable at tool calling and at following strict output schemas (to verify for your exact model/size). You have no API budget, so the app's runtime LLM must be local or a free hosted tier (to verify limits/terms of e.g. Google AI Studio's free tier). Plan includes a **deterministic fallback router** so the project never depends on one flaky model. |
| "I write the research reports myself, on paper" | **Push back** | (1) Handwriting → LLM digitization adds an error layer that undermines "traceable". (2) Your own opinions are *interpretation*, not *evidence*. **Change:** type reports directly as Markdown in a fixed template (Section 3.4). Tag them `source_type=analyst_note`, separate from `filing`. Filings are the evidence; your report is the analyst view. |
| Hand-calculate the TCS DCF first | **Keep, and make it a test** | Do it in a spreadsheet with your classmate. The spreadsheet becomes the **golden test**: Python must reproduce it within 0.1%. |
| Classmate helps with DCF methodology | **Keep, but schedule it** | The assumption sign-off is a dependency. Book fixed sessions (Section 9, P0.3). Unknown: their availability (open question). |
| "1–2 weeks" | **Unrealistic for the full v1** | See Section 2. |
| Voice I/O, live news, multi-company, report generation | **Defer** (already deferred) | Agree. Also defer any price-dependent output (see 8.7). |

---

## 2. v1 scope and honest effort estimate

### 2.1 v1 scope (TCS only)

**In v1**
- One company: TCS, **consolidated** Ind AS financials, fiscal years FY21–latest (to verify which years are available) plus the last 4–8 quarters.
- ~25 financial metrics (Section 4.2) hand-keyed from official filings into a CSV, then loaded into SQLite with validation checks.
- Qualitative corpus: latest 2 annual reports, last 4 quarterly result documents/fact sheets (to verify what TCS publishes and where), and the author's typed TCS report.
- Tools: `get_financial_fact`, `compute_ratio`, `run_dcf`, `search_documents`.
- Agent + structured answers with citations and calculation paths.
- Verifier (numeric grounding + citation checks).
- Evaluation: ~41 hand-written questions, 2 headline metrics, a naive-RAG baseline.
- Streamlit UI showing the answer, claims, citations, and calc path.
- README with results.

**Not in v1:** other companies, earnings-call transcripts, news, price data, beta/price-history computation, report generation, voice, watchlists, authentication, deployment.

### 2.2 Effort estimate (my estimate, uncertainty about ±40%)

| Phase | Work | Hours |
|---|---|---|
| Phase 0 (manual, no coding tool needed) | Source inventory, hand-keying financials, hand DCF, gold eval set, typed report, environment checks | 25–40 |
| Phase 1 (build, 9 sessions) | M1–M9 below, including debugging and review of generated code | 40–70 |
| Eval and polish | Baseline, ablations, README, demo | 10–15 |
| **Total** | | **~80–125 h** |

Calendar time = total hours ÷ hours per week:
- 10 h/week → ~8–12 weeks
- 20 h/week → ~4–6 weeks
- 40 h/week (full-time, e.g. a break) → ~2–3 weeks

**Verdict: 1–2 weeks is not realistic for this v1.** What *is* realistic in 1–2 weeks: all of Phase 0 (which is the true bottleneck), or a thin vertical slice (M1 + M2 + a minimal M5 on ~10 metrics).

### 2.3 Budget/timing consequence

Only about one month of Claude Pro is available, and it covers the coding tool, **not** the app's runtime LLM (see Section 10).
- **Revised (Oct 3, 2026):** the paid month starts as soon as the author subscribes (planned for this week), because the author has a free week and the early milestones (M1–M5) need only a few hand-typed rows and the real annual report PDF, not the full dataset. Phase 0 manual work (full financials, hand DCF, eval questions, typed report) runs in parallel in evenings and sessions; it needs no coding tool.
- The paid month is for building (M1–M8); manual Phase 0 hours should not be spent inside coding-tool sessions.
- Claude Pro includes Claude Code (per Anthropic's support pages), with an included usage limit whose size is to verify. Monitor it with `/status`, pace the work, and decline paid extra usage. **Never set `ANTHROPIC_API_KEY` in the shell**, or Claude Code bills API usage instead of using the subscription. Antigravity (free via the Gemini plan; limits to verify) is the overflow when the limit is hit. Each milestone below is sized to roughly one working session.

### 2.4 If behind schedule, cut in this order
1. Streamlit polish → plain minimal UI
2. Ablations (keep the baseline comparison)
3. Quarterly data (keep annual only)
4. Second annual report
5. Never cut: schema constraints, validation checks, golden DCF test, the verifier, the eval set.

### 2.5 Week 1 plan (plumbing on sample data, Oct 2026)

**Goal:** build the pipeline on a handful of real, hand-typed rows plus the real annual report PDF. Week 1 produces working plumbing, **not results**: no accuracy numbers, DCF values or performance claims go in the README or on a resume until the full dataset, the hand DCF and the frozen test split exist.

| Day | Milestone | Notes |
|---|---|---|
| 1 | M1 | Repo, schema, loader, validation tests. Fixture: about 10 hand-typed TCS facts (e.g. revenue and PAT for 2–3 fiscal years) with page numbers, in `data/sample/` |
| 2 | M2 | Period and unit handling, `get_financial_fact`, `compute_ratio` |
| 3 | M3 | DCF engine. Unit-test it on the toy case: free cash flows 100, 110, 121; discount rate 12%; terminal growth 4%; cash 200; debt 50; 10 shares → about 153.3 per share, with terminal value about 81% of enterprise value. The golden test against the real spreadsheet comes later |
| 4 | M4 | Real annual report PDF → chunks with page numbers → ChromaDB; test retrieval |
| 5 | M5 | Tools plus the two-step router. Run the P0.6 model test first (3–4B models on 8 GB RAM) |
| 6 | M6 | Verifier plus about 10 sample eval questions (dev split only) |
| 7 | Buffer | Slippage, reading about DCF, Phase 0 items |

**Sample-data labelling rules**
- LLM-generated notes (e.g. Gemini summaries of the reports) are reading aids and test fixtures only. Keep them in `data/sample/generated/` with `doc_type = generated_sample`. They are excluded from the eval, from any real retrieval run, and from the public repo.
- Retrieval tests index the real annual report PDF, not notes about it, so page citations stay real.
- No LLM-generated number ever enters SQLite. Numbers are hand-typed from the filings.
- The public report `data/manual/reports/tcs.md` is written by the author. A generated summary may help as a reading aid, but the final text and its page citations are the author's own.

---

## 3. Architecture

### 3.1 Data flow

```
 OFFICIAL DOCS (PDF)                         HAND-KEYED FACTS (CSV)           USER ASSUMPTIONS (YAML)
        │                                          │                                   │
        ▼                                          ▼                                   ▼
 ingest_docs.py                              load_facts.py                       dcf_inputs.yaml
 (PyMuPDF/pdfplumber → text                  (validate units, periods,           (every assumption has
  chunks with page + section)                 reconcile checks)                    a rationale + source)
        │                                          │                                   │
        ▼                                          ▼                                   ▼
   ChromaDB  ◄── metadata: source_id,          SQLite  ◄── facts, sources,         DCF engine (pure Python)
   (qualitative)  page, section, source_type   (numbers)    computed_metric,       writes dcf_run rows
        │                                          │         dcf_run                   │
        └──────────────┬───────────────────────────┴───────────────────────────────────┘
                       ▼
              TOOL LAYER (plain typed Python, no LLM inside)
   get_financial_fact | compute_ratio | run_dcf | search_documents
                       ▼
              AGENT LOOP (LLM routes + explains)  ──► structured Answer {claims[], evidence[], limitations}
                       ▼
              VERIFIER (numeric grounding, citation existence, unit/period match)
                       ▼
              STREAMLIT UI (answer + citations + calc path)       EVAL HARNESS (same pipeline, scored)
```

### 3.2 Tools (contract)

| Tool | Input | Output | Notes |
|---|---|---|---|
| `get_financial_fact` | metric_id, period label (e.g. `FY25`, `Q2 FY26`), basis | value, unit, fact_id, source_id, page | Returns canonical value **and** as-reported value/unit. Errors if missing — never guesses. |
| `compute_ratio` | ratio_id, period | value, unit, formula, input fact_ids | Deterministic. Writes a `computed_metric` row. |
| `run_dcf` | scenario name (from YAML) | full output JSON: every intermediate, inputs, checks | Never takes numeric assumptions from the LLM. |
| `search_documents` | query, optional filters (source_type, doc, year) | top-k chunks with source_id, page, section, score | Same retrieval idea as your legal chatbot, but each chunk **must** carry source_id + page so citations are structural, not generated text. |

### 3.3 How the agent decides which tool to use

Four question types and the expected tool pattern:

| Type | Example | Tool pattern |
|---|---|---|
| Numerical | "TCS consolidated PAT in FY25?" | `get_financial_fact` (and `compute_ratio` if derived) |
| Qualitative | "What risks does the annual report highlight about client concentration?" | `search_documents` |
| Valuation | "Base-case DCF value per share? What if WACC is +1%?" | `run_dcf` (scenario variants pre-defined in YAML; a "+1% WACC" variant is a named scenario or a sensitivity-grid lookup, not LLM arithmetic) |
| Mixed | "Margin trend, and what management says about it?" | `get_financial_fact`/`compute_ratio` + `search_documents`, then compose |
| Out of scope | "Will TCS go up?", "Should I buy?", "Compare with Infosys" | Refuse politely, state why, no tools called |

**Router v0:** LLM tool-calling with strict tool descriptions and a system prompt containing the rules above.
**Router v1 (fallback):** if routing accuracy on the dev set is below ~90% (threshold is a suggestion; tune it), switch to a two-step design: (1) LLM emits a constrained JSON intent `{type, metric_ids, periods, needs_docs}`; (2) deterministic dispatcher calls tools; (3) LLM only writes the explanation from tool outputs. This is more robust with small local models.
Measure routing accuracy as its own metric (secondary). With 8 GB RAM, expect Router v1 (two-step) to be the default: build it first in M5 and treat free-form tool calling as an experiment.

### 3.4 Qualitative corpus format (answers "which format and what all")

**What goes in (v1):**
- `filing` type: latest 2 annual reports; last 4 quarterly results/fact sheets (to verify exact document names and URLs on TCS investor pages / exchange sites).
- `analyst_note` type: the author's own TCS report.
- Later (not v1): earnings-call transcripts, investor presentations.

**Author report format: Markdown, typed, one file per company**, e.g. `data/manual/reports/tcs.md`:

```markdown
---
company: TCS
as_of: 2026-10-xx
author: Aradhya Chandra
source_type: analyst_note
---
## Business overview
...
## Segments and revenue drivers
...
## Margins and cost structure
...
## Capital allocation
...
## Risks
...
## Management commentary
(Quote nothing long. Paraphrase and cite: [AR FY25 p.xx])
## Open questions
...
```

Rules: stable `##` headings (chunk by heading, then by size); every factual sentence that comes from a filing ends with a bracketed cite `[doc, page]`; opinions are clearly labelled as opinion. Retrieval metadata per chunk: `source_id, source_type, doc_title, page (or heading), fiscal_year`.

**The report is public.** It lives in the public main repo so a reader can see the author's own analysis, not just the filings. Because of that: paraphrase filings and cite them, never paste long passages from the annual report; and the report must contain no buy/sell/hold calls, target prices or "undervalued/overvalued" verdicts (see Section 7, risk 9). Opinions are fine if clearly labelled as the author's view and framed as analysis.
If the author insists on paper: budget a separate digitization step (photo → LLM transcription → **manual proofread**), and expect errors (to verify quality on actual handwriting).

---

## 4. SQLite schema (financials)

### 4.1 Design rules
1. Every number is stored with **period, basis, unit, currency, and a source (document + page)**.
2. Canonical units are enforced per metric (Section 4.2). Store the **as-reported** value and unit too, plus the conversion factor, so any unit mix-up is auditable.
3. Fiscal years are **Indian FY (April–March)**. `FY25` = 1 Apr 2024 – 31 Mar 2025 (TCS fiscal year end is 31 March; to verify against the filing). Store real `start_date` and `end_date`. Never infer period from labels in code.
4. Restatements create a **new** fact that supersedes the old one; old rows are kept.
5. Derived values never live in `fact`. They live in `computed_metric` with a formula ID and input fact IDs.
6. **Page numbers:** the page printed on a page often differs from the PDF's page index (cover, contents, etc.). Store both (`source_page` = PDF index, `source_page_label` = printed number, if different). Citations in the UI show the PDF index with the printed label in brackets, so a reader can find the page either way.
7. **Company-defined vs computed metrics:** where TCS reports its own figure (e.g. operating margin) and our formula differs (e.g. EBIT-based), keep both: the reported one as a `fact`, ours as a `computed_metric`, with the definitions written down. Eval gold answers must name which definition they use.

### 4.2 Metric list for v1 (proposed; finalize in P0.2)
Income: revenue_from_operations, other_income, total_expenses, employee_benefit_expense, depreciation_amortisation, finance_costs, ebit (as defined in `metric.definition`), profit_before_tax, tax_expense, profit_after_tax, eps_basic, eps_diluted.
Balance sheet: cash_and_equivalents, other_investments (treasury; define precisely), borrowings, lease_liabilities, total_equity, total_assets, non-controlling_interest.
Cash flow: cash_from_operations, capex (purchase of PP&E and intangibles), dividends_paid, share_buybacks.
Other: shares_outstanding, diluted_shares, headcount, attrition_percent (if reported).

### 4.3 DDL

```sql
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
```

### 4.4 Load-time validation checks (loader must fail loudly)
- `fact.unit == metric.canonical_unit`; `value == reported_value * conversion_factor`.
- Value plausibility bands per metric (a ₹ crore figure 1000× off should be impossible to load).
- Balance sheet: assets = equity + liabilities (within rounding).
- Cash flow: opening cash + net change = closing cash (within rounding).
- Q1+Q2+Q3+Q4 ≈ FY for flow metrics (tolerance ~0.1%; to verify what TCS rounding allows).
- Same fact from two sources (e.g. annual report vs result press release) must agree, else flagged.
- Every fact has `source_page`.
- Any manual entry is double-entered or independently re-checked before `verified_by` is set.

---

## 5. DCF module design

### 5.1 Concepts (read before building; short on purpose)

- **FCFF (free cash flow to the firm):** cash the *business operations* generate for all capital providers = EBIT × (1 − tax) + D&A − capex − increase in net working capital. Use operating profit, so **exclude other income** (for TCS, treasury income is large and would be double-counted if you also add the investments in the bridge below).
- **WACC:** the discount rate = weighted cost of equity and debt. For a nearly debt-free company, WACC ≈ cost of equity = risk-free rate + beta × equity risk premium. How to treat lease liabilities under Ind AS 116 (to verify with your finance partner): the key is *consistency* between how EBIT/FCFF treat lease costs and how the bridge treats lease liabilities.
- **Terminal value (TV):** value of all cash flows after the explicit forecast, usually Gordon growth: FCFF_(n+1) / (WACC − g). TV is often most of the total value, so it is the first thing to sanity-check.
- **EV → equity bridge:** Enterprise value + cash and treasury investments − debt − lease liabilities (if treated as debt) − minorities = equity value; ÷ diluted shares = value per share.
- **Output meaning:** a DCF value per share is "what these assumptions imply", not a prediction or a recommendation.

### 5.2 Assumptions the human MUST set (in `dcf_inputs.yaml`, each with `value`, `rationale`, `source`)

The engine **refuses to run** if any assumption lacks a rationale.

| Assumption | Notes |
|---|---|
| Valuation date | Fixed date; all discounting relative to it |
| Explicit forecast horizon | Suggest 5 (or 10 with fade) |
| Revenue growth per forecast year | Informed by history but your call |
| EBIT margin per forecast year | |
| Cash tax rate | |
| D&A as % of revenue | |
| Capex as % of revenue | |
| Net working capital change (% of incremental revenue) | |
| Risk-free rate | India 10-year government bond yield as of valuation date; source to verify |
| Equity risk premium | Documented source (e.g. a published country-risk dataset; to verify) |
| Beta | v1: set manually with a documented source. Computing from prices is out of scope (needs price data + licensing) |
| Cost of debt and target capital weights | Likely ≈ all-equity for TCS (to verify) |
| Terminal growth rate | Must be below long-run nominal growth and below the risk-free rate (the engine checks) |
| Treatment of leases and treasury investments | Decide once with your finance partner; document it |
| Share count basis | Diluted (to verify what TCS reports) |
| Scenarios | Base / bear / bull defined by the human as named YAML blocks |

### 5.3 What the code derives (no human input)
- Historical growth, margins, tax rate, D&A %, capex %, NWC changes from SQLite facts (shown beside the assumptions so you see how your inputs compare with history).
- Historical FCFF.
- Forecast FCFF, discount factors, PV of each year, terminal value, enterprise value.
- Bridge items from the latest balance sheet facts (cash, investments, debt, leases, minorities).
- Equity value, value per share.
- Sensitivity grid: WACC × terminal growth (computed by code, never by the LLM).
- Implied multiples (implied EV/EBITDA, implied P/E on the DCF value) and terminal value as % of EV.
- Sanity checks (stored in `checks_json`): terminal growth < WACC; terminal growth < risk-free rate; TV share of EV within a warning band; margin/growth jumps vs history flagged; all required facts present and from the same basis/period.

### 5.4 Interface and testing
- `run_dcf(scenario) -> DCFResult` (pydantic), every intermediate exposed, so the UI can display the calculation path.
- **Golden test:** the hand-built spreadsheet (P0.3) is the reference. Python must match its equity value per share within 0.1% for the base case, plus at least 2 other scenarios.
- Unit tests for each function (discounting, TV, bridge) with tiny hand-computed examples.
- The DCF never uses market price in v1. If a price is ever shown, it is a manually entered value with a date, and no "undervalued/overvalued" wording (see 8.7).

---

## 6. Evaluation plan

### 6.1 Question set (~41 questions, written by hand in Phase 0, before any model runs)

| Category | Count | Examples |
|---|---|---|
| A. Direct numeric lookup | 9 | "TCS consolidated revenue in FY25?" |
| B. Unit/period traps | 6 | "FY25 revenue in ₹ million?" "What period is Q2 FY26?" "Is FY25 calendar 2025?" |
| C. Derived ratios | 7 | Operating margin, PAT margin, 3-year revenue CAGR, EPS growth, FCF conversion |
| D. DCF | 5 | Base-case value per share; WACC sensitivity; TV share of EV |
| E. Qualitative (RAG) | 7 | Risks cited in the annual report; capital allocation policy; client concentration commentary; at least 3 questions answerable only from the author's own report |
| F. Mixed | 3 | Margin trend + management explanation |
| G. Guardrail/refusal | 4 | "Will TCS go up?", "Should I buy?", "Compare with Infosys" (out of v1 scope), an unanswerable-from-data question |

Format: `eval/questions.jsonl`, one object per line:
`{id, category, question, gold_answer, gold_value, gold_unit, gold_period, tolerance, gold_sources:[{source_id, page}], must_refuse, split:"dev"|"test", notes}`

**Split:** about 20 `dev` (use while building) and about 20 `test` (frozen; run only at milestone reviews and for the final numbers). Coding tools must never edit gold files. Have the finance classmate spot-check at least 10 gold answers (an author-written gold set can carry the author's own mistakes).

### 6.2 Headline metrics (pick these two for the resume)

1. **Numeric accuracy:** share of numeric claims in answers that match gold value, unit, and period. Exact match after rounding to the stated precision for reported facts; ±0.5% relative for derived/DCF values. Automated.
2. **Citation correctness:** share of claims whose cited `(source_id, page)` is in the gold evidence set (numeric claims, automated) and, for qualitative claims, whether the cited chunk actually supports the claim (manual label on a ~20-claim sample). Report both parts.

Secondary: routing accuracy, refusal correctness (G), unsupported-claim rate (claims with no evidence), verifier rejection rate.

### 6.3 Baseline and ablations (this is what makes the number meaningful)
- **Baseline:** naive RAG over the same PDFs only (no SQLite, no tools, no verifier), same LLM, same questions.
- **Ablation:** full system with the verifier off vs on.
- Report **counts, not just percentages** (e.g. "37 of 41"), since n≈41 is small; do not quote decimals that imply precision you don't have. Report dev and test separately. Don't quote any number on the resume that this harness didn't produce.

---

## 7. Risks and mitigations

| # | Risk | Mitigation |
|---|---|---|
| 1 | **Wrong numbers** (typos in hand-keying, wrong line item, parser errors) | Double-entry or independent re-check; reconciliation checks (4.4); second-source cross-check; `verified_by` field; never use LLM-extracted numbers without human verification in v1. |
| 2 | **Unit mix-ups** (₹ crore vs ₹ million vs USD; quarterly docs vs annual report may use different units/currencies, to verify) | `canonical_unit` per metric; `reported_unit` + `conversion_factor` stored; plausibility bands; unit-trap questions in the eval (category B). |
| 3 | **Fiscal-year/period mix-ups** (FY25 vs calendar 2025; Q2 FY26 = Jul–Sep 2025; restated figures) | Real `start_date/end_date` on every period; period resolver is a tested function; the LLM never converts periods itself; restatement handling via `supersedes_fact_id`. |
| 4 | **Consolidated vs standalone; reported vs adjusted** | `basis` is mandatory and defaults to consolidated; metric definitions state inclusions/exclusions. |
| 5 | **Unsourced or LLM-computed numbers in answers** | Verifier: extract every number from the answer text; each must match a tool output (within rounding) or the answer is rejected/regenerated; claims without evidence are dropped or flagged. |
| 6 | **Hallucinated citations** | Citations come from tool metadata only; verifier checks that cited `(source_id, page)` exist and the chunk text contains the claim's key terms (heuristic; to verify effectiveness). |
| 7 | **Small local LLM can't do tool calling or schemas reliably** | Test in Phase 0 (P0.6); keep the deterministic fallback router (3.3); measure routing accuracy. |
| 8 | **Data licensing / scraping terms** | v1 uses manually downloaded official filings; don't scrape sites whose terms forbid it (Screener, exchange sites, etc. — terms to verify); PDFs live in a **separate private repo** (`equity-research-data`), never in the public main repo; the main repo holds only a `sources.md` manifest (title, URL, date, sha256). Check redistribution terms before ever making the data repo public (to verify). yfinance-style unofficial sources are unreliable for Indian fundamentals and the terms are unclear (to verify). |
| 9 | **Regulatory framing** | No buy/sell/hold, target prices, or "undervalued/overvalued" verdicts. SEBI's research analyst regulations may apply to publicly publishing research recommendations in India (to verify; this plan is not legal advice). Persistent disclaimer in UI and README. |
| 10 | **Own report becomes "evidence"** | Tag `analyst_note`; retrieval prompt must label author views as opinion; filings outrank notes for factual claims. |
| 11 | **Scope creep and the one-month paid window** | Phase 0 done before subscribing; strict milestone order; cut list in 2.4. |
| 12 | **Eval overfitting** | Frozen test split; gold files read-only for coding tools; no tuning on test. |
| 13 | **Collaborator availability** (DCF review) | Book dated sessions in Phase 0; if unavailable, scenarios are labelled "author's assumptions, unreviewed" in README. |

---

## 8. Working agreements for any coding tool

1. Read this file first. Work on **one milestone at a time**, in order.
2. **Tests before code** where a test is specified. A milestone isn't done until its acceptance test passes.
3. **No LLM arithmetic, ever.** All math lives in `tools/` and `dcf/` as deterministic functions.
4. **No network scraping.** Data comes from files the human placed in `data/`. **Never commit anything from `data/raw/` (the private data repo checkout) to this public repo.**
5. Don't edit `eval/questions.jsonl`, `data/manual/*.csv`, or `dcf_inputs.yaml` unless the human asked. Never invent financial figures or assumptions.
6. When unsure (library behavior, data semantics), write "TO VERIFY" in code comments and `NOTES.md` instead of guessing.
7. Keep a running `PROGRESS.md`: what was done, what's next, known issues, decisions made. Update it at the end of every session.
8. Prefer small dependencies; pin versions in `requirements.txt`.
9. Never produce text implying investment advice (see Section 7, risk 9).
10. Company-specific details (metric names, units, assumptions, valuation method) live in config files, never hard-coded, so adding a second company is a config + data change, not a code change.
11. The runtime LLM is called only through one function, with the model name taken from config, so models can be swapped and compared on the eval set. Run evals at temperature 0 and record the model name and version with every result.
12. After each milestone, the coding tool writes a short plain-language note in `docs/` on what it built and why; the author re-explains it in their own words before moving on (interview readiness: every module must be explainable by the author).
13. Secrets (API keys, if a hosted model is ever used) go in `.env`, which is gitignored; never commit them to the public repo.

### 8.1 Suggested stack (open to change)
Python 3.11+ (to verify your installed version), `sqlite3` + pydantic, pytest, PyMuPDF or pdfplumber (to verify behavior on the actual TCS PDFs; table extraction is often messy, which is why financials are hand-keyed in v1), ChromaDB, `nomic-embed-text` via Ollama (already known from the legal chatbot), Ollama for the local LLM, Streamlit.

### 8.2 Suggested repo layout
```
equity-research/
  PROJECT_PLAN.md   PROGRESS.md   README.md   NOTES.md
  AGENTS.md / CLAUDE.md        # 5 lines: "read PROJECT_PLAN.md; follow section 8"
  data/
    raw/            # local checkout of the private data repo (gitignored in this repo)
    manual/         # financials_tcs.csv, reports/tcs.md, dcf_inputs.yaml
  src/erp/
    db/ (schema.sql, load_facts.py, validate.py)
    periods.py  units.py
    tools/ (facts.py, ratios.py, search.py)
    dcf/ (engine.py, checks.py)
    ingest/ (pdf_to_chunks.py, index_chroma.py)
    agent/ (router.py, loop.py, answer_schema.py, verifier.py)
  eval/  (questions.jsonl, run_eval.py, results/)
  app/streamlit_app.py
  tests/
```

### 8.3 Answer schema (agent output)
```json
{
  "answer_text": "...",
  "claims": [
    {"text": "...", "type": "number|qualitative|inference",
     "value": 0.0, "unit": "INR_CRORE", "period": "FY25",
     "evidence": [{"kind": "fact|calc|dcf_run|doc_chunk", "id": 123, "page": 45}]}
  ],
  "limitations": ["..."],
  "data_as_of": "date of the latest filing used",
  "disclaimer": "Illustrative analysis, not investment advice."
}
```

### 8.4 Numeric grounding verifier (concept, explained)
The LLM writes the final prose. The verifier scans that prose for numbers, normalizes them (₹ crore, %, per share), and checks each against the set of values returned by tools in this turn (allowing for rounding, e.g. 25.1% vs 0.2509). If a number in the prose isn't in the tool outputs, the answer is rejected and regenerated with the instruction to use only provided values. This is cheap, deterministic, and is what makes "the LLM never does math" an enforced property instead of a hope.

### 8.5 Chunking and metadata for ChromaDB
Same pipeline idea as the legal chatbot (split → embed → store), but metadata is mandatory: `source_id, source_type, doc_title, page, section, fiscal_year`. Test retrieval alone (recall@k on category E questions) before wiring it to the agent.

### 8.6 Persistence decisions (resolve at the end of v1)
SQLite and ChromaDB: keep. Revisit only if adding many companies with concurrent users (then consider Postgres and a hosted vector store; to verify costs). **PDF storage:** the private data repo is fine for TCS plus a few peers (v1–v1.1). Beyond roughly 10 companies, move PDFs out of git (local disk plus a backup); the `sources.md` manifest stays in the repo and a script checks local files against its sha256 values.

### 8.7 Price-related output
v1 does not ingest market prices. If a market price is ever displayed, it must be manually entered with a date and shown beside the DCF value without any valuation verdict.

---

## 9. Milestones (each sized for ~one working session) and Definition of Done

### Phase 0 — Manual pre-work (no coding tool needed; runs in parallel with Week 1)

| ID | Task | Done when |
|---|---|---|
| P0.1 | Create the private data repo (`equity-research-data`). Inventory sources: download latest 2 TCS annual reports + last 4–8 quarterly results/fact sheets from official sources; record URLs and dates (what TCS publishes, and where: to verify) | PDFs committed to the private data repo (plain git is fine; each TCS annual report is about 20 MB, under GitHub's 50 MB warning size (to verify), so no Git LFS needed; commit each PDF once and don't re-commit); `sources.md` manifest (title, URL, date, sha256) in the main repo; data repo checked out locally at `data/raw` and gitignored in the main repo |
| P0.2 | Hand-key the v1 metric list (4.2) for FY21–latest and recent quarters into `financials_tcs.csv` with page numbers and as-reported units | Every row has source + page; second-pass check done on ≥20% of rows; reconciliation checks (4.4) done manually once |
| P0.3 | Hand-built DCF in a spreadsheet, with finance classmate; fill `dcf_inputs.yaml` with rationales | Spreadsheet gives base/bear/bull per-share values; assumptions reviewed; the author can explain each input in one sentence |
| P0.4 | Write the ~41 eval questions with gold answers and source pages; split dev/test | `questions.jsonl` complete; gold values traced to pages |
| P0.5 | Type the TCS report in Markdown using the template (3.4); cite filings inline | File exists, all sections have at least a first draft |
| P0.6 | Environment check: hardware is a MacBook Air M2 with 8 GB RAM (start with ~3–4B models and test one 7–8B model only to see whether it fits; the two-step router is the default design; the fanless Air may throttle on long eval runs; all to verify), Python version, Ollama running, test 2–3 local models for tool-calling and JSON-schema reliability on 5 toy prompts (which models support tool calling in Ollama: to verify) | A note in `NOTES.md` with the model chosen and why |

### Phase 1 — Build (paid month)

| ID | Session goal | Acceptance test |
|---|---|---|
| M1 | Repo skeleton + SQLite schema + loader + validation checks | Loading `financials_tcs.csv` succeeds; deliberately corrupted rows (wrong unit, missing page, broken balance) are rejected by tests |
| M2 | `periods.py`, `units.py`, `get_financial_fact`, `compute_ratio` + `computed_metric` writes | Period resolver tests (FY/Q labels ↔ dates); ratio results match the hand-calculated values for ≥5 ratios |
| M3 | DCF engine + checks + `run_dcf` | **Golden test:** base case within 0.1% of the spreadsheet; 2 more scenarios; unit tests for discounting/TV/bridge; refuses to run if a rationale is missing |
| M4 | PDF → chunks → ChromaDB with metadata; `search_documents` | Recall@k on dev category E questions meets a target you set after seeing a first run (record baseline); every chunk has source_id + page |
| M5 | Tool layer + agent loop (Router v0) + structured Answer | End-to-end answers for 10 dev questions with evidence IDs filled; routing accuracy measured |
| M6 | Verifier (numeric grounding, citation existence) + refusal handling + fallback router if needed | Injected bad numbers/citations are caught in tests; guardrail questions (G) refused correctly on dev |
| M7 | Eval harness + naive-RAG baseline + ablation | `run_eval.py` outputs per-category and headline metrics for dev; test split run once; results saved |
| M8 | Streamlit UI: question box, answer, claim list with citations (each badged **Filing** or **Author's note**, so the author's own work is visible), expandable calculation path (inputs → formula → result), disclaimer | Manual walkthrough of 5 questions; a reviewer can trace one number back to its source page in ≤3 clicks |
| M9 | README, results table, demo script/screenshots, cleanup | README complete (below); clean-clone setup works from README alone |

### Definition of Done (v1)
- All of P0.1–P0.6 and M1–M9 done.
- Golden DCF test passes (≤0.1%).
- Load-time validation checks pass on the full dataset.
- Eval run on the frozen test split completed, with the two headline metrics, the baseline comparison, and dev/test reported separately.
- Every answer in the UI shows evidence and, for computed values, the calculation path; answers with unsupported numbers are rejected by the verifier.
- Out-of-scope questions (predictions, advice, other companies) are refused with an explanation.
- Disclaimer visible in UI and README.
- A fresh clone can be set up and run from the README (README explains how to obtain the filings: the private data repo for the author, official download links for everyone else).

---

## 10. Open decisions (do not treat as decided)

| Question | Recommendation | Decide by |
|---|---|---|
| **Which LLM** at runtime? | Local via Ollama by default (**no hosted API budget**). With 8 GB RAM: a small (~3–4B) model plus the two-step router is the default; a free hosted tier is the fallback. Note: an **API** is a way for your code to call a model over HTTP and is billed per use, separate from a Claude Pro subscription; Claude Pro powers the coding tool, not your app. You already use a local API: your legal chatbot talked to Ollama. A free hosted tier (e.g. Google AI Studio; terms/limits to verify) is a possible fallback. | P0.6 |
| Data providers and licensing | v1: official filings, downloaded by hand. Revisit paid/licensed providers only if you expand beyond a portfolio project (terms to verify). | Before any public release |
| SQLite/ChromaDB beyond prototype | Keep for single-user | End of M9 |
| Frontend beyond Streamlit | Streamlit for v1 | End of M9 |
| Repo visibility | **Decided:** the main repo will be public (resume); PDFs and raw data stay in a separate private data repo. The typed report `data/manual/reports/tcs.md` is public by design (it is the author's own work, and it is what shows an interviewer the author's input). Still open: whether `financials_tcs.csv` may sit in the public repo (to verify) | Before M9 |
| Beta and price data for WACC | Manual input for v1 | P0.3 |
| Lease and treasury-investment treatment in DCF | Decide once with the finance partner; document in YAML | P0.3 |

## 11. Later (post-v1, in rough priority)
1. **Staged growth, not Nifty 50 up front.** Nifty 50 is out of scope until data loading is automated and licensing is settled (to verify). Order:
   - **v1:** TCS only (everything above).
   - **v1.1:** add 2 IT-services peers (e.g. Infosys, HCLTech) with the same statement format and the same DCF. Tests whether the schema and tools generalize, and enables first comparisons.
   - **v2:** about 10 companies across 3–4 sectors, semi-automated data loading, and **sector-specific valuation** (banks and other financials do not fit a FCFF DCF; they need e.g. price-to-book or a residual income model; cyclicals and commodity companies also need different treatment).
   - **Later:** wider coverage only after automated loading (licensed provider or PDF parsing with validation) is in place.
   Rule of thumb: a few companies with verified numbers and a measured accuracy score beat many with unverified ones.
2. Earnings-call transcripts into the qualitative store.
3. Report generation from verified claims.
4. Price data and beta computation (licensing first).
5. Watchlists; voice I/O (Whisper STT, local TTS; to verify choices); live news.

---

## 12. README outline

1. Title + one-line pitch + **not investment advice** banner
2. What it does (3 bullets) and what it deliberately does not do
3. Demo: GIF/screenshots of a numeric, a qualitative, a DCF, and a refusal answer
4. Core principle: AI interprets, code calculates, sources prove
5. Architecture diagram + data flow
6. Data: sources, how facts were entered and verified, units/fiscal-year conventions, licensing notes
7. DCF: method, assumption register, golden test against the spreadsheet
8. Evaluation: question set design, metrics, baseline comparison, **results table with counts**, limitations (small n, one company)
9. Setup and run (fresh-clone instructions; model requirements)
10. Repo layout
11. Limitations and known risks
12. Roadmap
13. Disclaimer and licensing

---

## 13. Status log (keep updated)

| Date | Milestone | Notes |
|---|---|---|
| | P0.1 | |
