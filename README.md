# TCS research assistant

An AI-assisted equity research tool for one Indian company: it answers questions about Tata
Consultancy Services (TCS) with figures that carry a source page or a calculation path.

> **Not investment advice.** This is a learning and portfolio project. It gives no recommendations,
> no price targets and no valuation verdicts, and it should not be used to make investment
> decisions. DCF outputs are what a set of stated assumptions implies, not a
> prediction.
>
> **v1 covers TCS only** (consolidated Ind AS figures from the FY26 annual report, plus the Q1 FY27
> fact sheet as a document).
>
> **Design principle: AI interprets, code calculates, sources prove.**

---

## 1. What it does, and what it does not do

**Does**
- Looks up reported TCS figures from a SQLite database where every fact has a document and page.
- Computes ratios and a discounted cash flow (DCF) valuation in plain, tested Python, and shows the
  calculation path (inputs with their fact ids and pages, formula, result).
- Answers qualitative questions from the annual report text (vector search over page-tagged chunks),
  and refuses questions it should not answer (price predictions, advice, other companies, data it
  does not have).

**Does not**
- Predict prices, give recommendations or price targets, or pass a valuation verdict on the stock.
- Let the language model do arithmetic. A small local model only picks tools and writes the prose; a
  verifier rejects prose containing figures that the tools did not return.
- Scrape websites or read live market data. All data comes from files placed in `data/` by hand.
- Cover any company other than TCS.

## 2. Demo

A five-question walkthrough (fact lookup, ratio, DCF, qualitative, refusal) with what to look at for
each is in [docs/DEMO.md](docs/DEMO.md). It runs in `--demo` mode, which replays saved answers and
needs no model.

Screenshots: not included yet (see "What is not verified" below). They can be taken from `--demo`
mode once a dev eval run exists on your machine.

## 3. Core principle: AI interprets, code calculates, sources prove

| Part | Who does it | Where |
|---|---|---|
| Decide which tool answers the question | small local LLM (two-step router), with code checks around it | `src/erp/agent/router.py`, `guardrails.py` |
| Every figure and every calculation | deterministic Python | `src/erp/tools/`, `src/erp/dcf/` |
| Write the answer text | the LLM, from tool results only | `src/erp/agent/loop.py` |
| Check the text against the tool results | deterministic verifier; on failure a code-written template answer is shown instead | `src/erp/agent/verifier.py` |
| Prove each claim | document + page for facts and passages; fact ids + formula for calculations | evidence ids on every number |

## 4. Architecture and data flow

```
 question
    |
    v
 refusal pre-check (patterns: advice, price prediction, other companies, future periods)
    |
    v
 router (LLM, JSON schema) ---> tool calls, checked by code
    |
    +--> get_financial_fact --> SQLite (facts with source document + page)
    +--> compute_ratio      --> SQLite inputs -> Python formula -> computed_metric row
    +--> run_dcf            --> data/manual/dcf_inputs.yaml -> Python DCF engine -> dcf_run row
    +--> search_documents   --> ChromaDB (annual report chunks with page metadata)
    +--> explain_period     --> fiscal-year dates from config
    |
    v
 composer (LLM writes prose from tool results; numbers pre-formatted by code)
    |
    v
 verifier (every figure, date, page and comparison in the prose must match the tool results)
    |
    v
 Answer: text + numbers used + citations + calculation paths + limitations + disclaimer
    |
    v
 Streamlit UI (badges: Filing / Author's note; page numbers; expandable calculation paths)
```

Plain-language notes on each part, written after each milestone, are in `docs/M1_*.md` to
`docs/M9_*.md`.

## 5. Data

**Sources.** The TCS Integrated Annual Report 2025-26 and the TCS Q1 FY27 fact sheet (results for
the quarter ended June 2026), downloaded by hand from TCS's official publications. The PDFs are not
in this repository: they live in a separate private data repository checked out at `data/raw/`
(gitignored). `sources_hashes.txt` records their SHA-256 so a reader with their own copy can check it
is the same file. The download URLs were not recorded (TO VERIFY; `url: null` in
`config/companies/tcs.yaml`), so this README does not give links.

**How facts were entered.** `data/sample/facts_sample.csv` holds 12 facts (revenue, profit after
tax, profit attributable to shareholders, basic EPS, cash and cash equivalents, total equity; FY25
and FY26) with the PDF page and printed page of each. They were read from the annual report by an AI
assistant and loaded with `entry_method = llm_extracted`; **none has been verified by a human yet**
(the loader prints "12 not yet verified by a human"). The fuller dataset the plan calls for (about 25
metrics, FY21 onwards, quarters, hand-keyed and double-checked) does not exist yet.

**Checks at load time** (`src/erp/db/validate.py`): unit must be the metric's canonical unit, value
must equal reported value times the conversion factor, every fact needs a source page, plausibility
bands per metric, duplicates and disagreeing duplicates rejected, source PDFs re-hashed when present,
one bad row blocks the whole load.

**Conventions.** Money in INR crore (1 crore = 10 million). Consolidated basis unless stated. Fiscal
year runs April to March: FY26 = 1 April 2025 to 31 March 2026, which is not calendar 2026; Q1 FY27 =
April to June 2026. Periods are resolved by tested code, never by the model. Display uses
international digit grouping (267,021); TCS prints Indian grouping (2,67,021); the verifier accepts
both.

**Licensing notes.** The filings are TCS's publications and are not redistributed here
(redistribution terms TO VERIFY before the data repo is ever made public). Whether even the small
facts CSV should sit in a public repo is an open decision in the plan (TO VERIFY).

## 6. DCF

**Method** (`src/erp/dcf/`): free cash flow to the firm over a 5-year explicit forecast, terminal
value by the Gordon growth formula, year-end discounting at WACC (CAPM cost of equity), then
enterprise value to equity value (add cash and investments, subtract debt, lease liabilities and
minority interest) and per share. Every intermediate (FCFF table, discount factors, terminal value and its
share of EV, the bridge, a WACC x terminal growth sensitivity grid) is returned and shown in the UI.

**Assumption register:** `data/manual/dcf_inputs.yaml`. Every assumption has a value, a rationale and
a source, and the engine refuses to run if any rationale is missing. Checks: terminal growth below
WACC (blocking), terminal growth below the risk-free rate (flagged), terminal value share of EV
inside a warning band (the band is a placeholder, TO VERIFY).

**Golden test against a hand-built spreadsheet: not done.** The plan's acceptance test for the DCF
is "Python reproduces the hand spreadsheet within 0.1%". That spreadsheet has not been built yet, so
the engine is tested only on small hand-computed cases (including the plan's toy case: cash flows 100,
110, 121; 12%; 4% growth; about 153.3 per share). Lease, stub-period and mid-year conventions are
open (NOTES.md, M3).

## 7. Evaluation

**Question set** (`eval/questions.jsonl`): 41 questions in seven categories (A fact lookup 9, B unit
and period traps 6, C ratios 5, D DCF 5, E qualitative 7, F mixed 3, G guardrails 6), split 20 dev /
21 test. The test split is frozen and is run once, behind a typed confirmation.

**Metrics** (all "k of n" counts; `config/eval.yaml`, `src/erp/eval/score.py`):
- Numeric accuracy: per question with a gold value, does the answer contain a claim matching the gold
  value, unit and period (exact for reported figures; ±0.5% relative for derived values).
- Numeric citation correctness: numeric claims whose cited (document, page) is in the gold sources.
  Qualitative citation support is labelled by hand on a ~20-claim sample (not yet labelled).
- Secondary: behaviour (answer / refuse / not available), guardrail refusals, over-refusal, routing,
  unsupported numeric claims, verifier rejections, advice words.

**Systems compared:** the full system; the full system with the verifier off (rejected text ships);
and a naive-RAG baseline (same model, same search, same top 5 passages, no database, no tools, no
verifier).

**Results.** The block below is generated from `eval/results/` by `scripts/make_results_table.py`;
nothing in it is typed by hand. Read it with these caveats:
- **Small sample, one company.** 20 dev and 21 test questions on TCS FY25/FY26 only, with 12 facts
  in the database. Gold answers and facts are signed off by the author only (no finance-partner
  review), and the DCF gold is the engine's own output. Read these as counts on a small, hand-built
  set, not as general accuracy figures.
- **The test split was run once**, on committed code (`eeaa196`), after all fixes were made on dev;
  nothing was tuned on it afterwards. The plan's full dataset and hand-built DCF do not exist yet.
- **Headline metrics** are numeric accuracy and gold-matching citations. The row "all numeric claims
  citing a gold page" swings with answer length and is not a headline (see Known weaknesses).
- **Scoring is strict about periods** (see Known weaknesses: EV-A04 on test is a correct figure
  scored wrong). Numbers are shown exactly as the harness produced them.
- `eval/results/` is gitignored (it holds annual-report excerpts). In a fresh clone, re-running the
  script prints "not yet run" until you run the eval yourself; the block below is what the author's
  machine produced.

<!-- results:start -->
_Generated by `scripts/make_results_table.py` from `eval/results/` (gitignored). Counts are "k of n"; n differs per row because each metric only counts the questions or claims it applies to. Do not edit by hand._

### Dev split

Latest finished run:

- Run `20261007-124758_d92bf9a4`, model `qwen2.5:3b`, temperature 0, seed 0, 20 questions.
- Code: git `d92bf9a` (committed code).
- Facts unverified by a human: 0 of 12. Gold answers pending author sign-off: 0 of 20.

| Metric | Full system | Verifier off | Naive RAG |
|---|---|---|---|
| Numeric accuracy (questions with a gold value) | 10 of 14 | 10 of 14 | 1 of 14 |
| Gold-matching numeric claims citing a gold page | 8 of 8 | 8 of 8 | 0 of 1 |
| All numeric claims citing a gold page | 21 of 51 | 15 of 20 | 1 of 16 |
| Behaviour correct (answer / refuse / not available) | 18 of 20 | 18 of 20 | 15 of 20 |
| Guardrail questions refused correctly (G) | 2 of 3 | 2 of 3 | 0 of 3 |
| Over-refusal (refused an answerable question) | 1 of 17 | 1 of 17 | 2 of 17 |
| Routing: right tools | 18 of 18 | 18 of 18 | n/a |
| Routing: right tools and period | 17 of 18 | 17 of 18 | n/a |
| Unsupported numeric claims | 0 of 56 | 1 of 25 | 5 of 20 |
| Verifier rejections (template answer shipped) | 2 of 18 | 0 of 18 | n/a |
| Answers with advice words | 0 of 20 | 0 of 20 | 0 of 20 |
| Errors | 0 of 20 | 0 of 20 | 0 of 20 |

All finished dev runs (the table shows the last one):

- `20261004-142147_9da27e58`: git `9da27e5`, dirty tree; full-system numeric accuracy 10 of 14
- `20261004-143418_9da27e58`: git `9da27e5`, dirty tree; full-system numeric accuracy 10 of 14
- `20261004-155610_6788b014`: git `6788b01`, dirty tree; full-system numeric accuracy 10 of 14
- `20261007-124758_d92bf9a4`: git `d92bf9a`, committed; full-system numeric accuracy 10 of 14

### Test split

Latest finished run:

- Run `20261007-132850_eeaa1965`, model `qwen2.5:3b`, temperature 0, seed 0, 21 questions.
- Code: git `eeaa196` (committed code).
- Facts unverified by a human: 0 of 12. Gold answers pending author sign-off: 0 of 21.

| Metric | Full system | Verifier off | Naive RAG |
|---|---|---|---|
| Numeric accuracy (questions with a gold value) | 10 of 14 | 10 of 14 | 0 of 14 |
| Gold-matching numeric claims citing a gold page | 8 of 8 | 8 of 8 | 0 of 0 |
| All numeric claims citing a gold page | 13 of 44 | 13 of 16 | 2 of 14 |
| Behaviour correct (answer / refuse / not available) | 21 of 21 | 21 of 21 | 18 of 21 |
| Guardrail questions refused correctly (G) | 3 of 3 | 3 of 3 | 1 of 3 |
| Over-refusal (refused an answerable question) | 0 of 18 | 0 of 18 | 1 of 18 |
| Routing: right tools | 17 of 18 | 17 of 18 | n/a |
| Routing: right tools and period | 17 of 18 | 17 of 18 | n/a |
| Unsupported numeric claims | 1 of 52 | 0 of 24 | 8 of 17 |
| Verifier rejections (template answer shipped) | 1 of 18 | 0 of 18 | n/a |
| Answers with advice words | 0 of 21 | 0 of 21 | 0 of 21 |
| Errors | 0 of 21 | 0 of 21 | 0 of 21 |
<!-- results:end -->

**Limitations of the evaluation:** small n (20 dev, 21 test), one company, one small model; the
gold answers were drafted with AI help (below); DCF gold is the engine's own output, so D questions
check consistency, not correctness; routing gold is coarse (expected tool per category); the
behaviour classifier depends on a phrase list; the router prompt was tuned on the dev split.

## 8. How this was built and what is not verified

This project was built with an AI coding assistant, milestone by milestone, from a written plan
(`PROJECT_PLAN.md`; progress log in `PROGRESS.md`; open questions in `NOTES.md`). Plainly:

- **Eval questions and gold answers** were drafted with AI assistance and the figures were
  cross-checked against the annual report pages by the AI assistant. The author reviewed and signed
  off all 41 on 2026-10-07 (recorded in each question's `entered_by` field). **No finance reviewer
  has spot-checked them**, which the plan asks for on at least 10 gold answers.
- **DCF assumptions** in `data/manual/dcf_inputs.yaml` were drafted by an AI assistant and adopted
  by the author as the working file on 2026-10-04. They **have not been reviewed by a finance
  partner**. DCF eval gold is the engine's own output on those assumptions, so it is a regression
  check, not independent truth.
- **Facts** (12 in `data/sample/facts_sample.csv`) were read from the annual report by an AI
  assistant; the author verified all 12 against the report pages on 2026-10-07 (`verified_by` and
  `verified_on` in the CSV). No finance reviewer has checked them.
- **Runtime model:** `qwen2.5:3b` running locally through Ollama (chosen in a small test on an 8 GB
  MacBook Air; NOTES.md, P0.6). TO VERIFY: its licence. As far as known, the 3B size is under the
  "Qwen Research License" rather than Apache 2.0; fine for local personal use, to be checked before
  any other use.
- **No author-written qualitative notes** are in the index or the eval yet. The plan's "Author's
  note" badge exists and is tested, but no category E question is answerable only from the author's
  own report, because that report has not been written.
- **Known weaknesses** (details in NOTES.md):
  - Retrieval misses some qualitative questions (e.g. lease interest, dividends; the client
    concentration sentence sits inside a table-heavy chunk). The system then says "not available"
    rather than inventing, but it is still a miss.
  - Metric substitution is not guarded: the router can map a figure the database does not store to a
    different metric (seen: "tax expense" answered with profit after tax). Nothing in code checks
    that the chosen metric matches the figure asked about.
  - Unit conversion has no tool: questions asking for INR million or lakh crore are answered in
    crore (known failures EV-B02, EV-B06).
  - The verifier does not read figures glued to a garbled currency symbol (PDF text extraction
    sometimes renders ₹ as "H", e.g. "H1,761 crore"), so such figures are neither grounded nor
    flagged.
  - The router prompt is fragile with a 3B model; small wording changes move routing results.
  - When the verifier rejects the model's text, the code-built fallback answer can quote passages
    that are irrelevant or garbled (seen on EV-F01 dev and EV-F02 test: a CSR "average net profit"
    paragraph). Every number in it is sourced, but it does not answer the question.
  - The verifier can misread a comparison that spans two sentences (the rejection was right, the
    stated reason was wrong), and plain constants such as "100" pass unchecked.
  - The scorer is strict about periods: a claim must name the period as a label (e.g. "FY25"). On the
    test split, EV-A04 states the correct figure (INR 48,797 crore) but writes "fiscal year ending
    March 2025", so it is scored wrong. The test numbers are reported as the harness produced them,
    not re-scored.
  - The row "all numeric claims citing a gold page" depends on how verbose an answer is (a fallback
    answer that quotes passages adds dozens of claims). It is not a headline metric.
  - PDF extraction issues: letter-spaced text on designed pages, broken glyph maps on some pages,
    coarse section detection.
- **Licences of dependencies:** PyMuPDF is AGPL-3.0 (or commercial). TO VERIFY that this is
  acceptable for a public repository and its intended use.
- **Not verified in this repo:** the 5-question live walkthrough in the UI (M8) with a live model;
  the qualitative citation labels; the test split run.

## 9. Setup and run

Tested from a clean copy with `scripts/clean_clone_check.sh` (Python 3.13.5, macOS; the plan asks for
Python 3.11+, other versions TO VERIFY).

**What you can and cannot reproduce from this public repo alone**

| Step | Without the PDFs and Ollama | Needs |
|---|---|---|
| Install, run the test suite | yes (tests use fakes; tests needing the PDFs or Ollama skip) | nothing |
| Build the sample database from `data/sample/facts_sample.csv` | yes | nothing |
| DCF engine on the assumptions file (`erp.dcf.run.run_dcf`, from Python; no CLI) | yes | the sample database |
| UI in `--demo` mode | starts, but shows "no saved eval runs" | a saved eval run in `eval/results/dev/` |
| Index the annual report into ChromaDB | no | the PDFs in `data/raw/` + Ollama with `nomic-embed-text` |
| Ask live questions (CLI or UI) | no | the index above + Ollama with `qwen2.5:3b` |
| Run the eval (and so fill the results table) | no | all of the above |

**1. Install**

```bash
git clone <this repo> && cd <repo>
```

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

**2. Tests** (no model, no PDFs needed)

```bash
.venv/bin/python -m pytest -q
```

**3. Sample database** (writes `data/db/sample.sqlite`, gitignored)

```bash
PYTHONPATH=src .venv/bin/python -m erp.db.load_facts --csv data/sample/facts_sample.csv --entry-method llm_extracted --replace
```

**4. Documents and models** (needs the PDFs and Ollama)

Put `tcs_annual_report_FY26.pdf` and `tcs_factsheet_Q1_FY27.pdf` in `data/raw/` (the author checks
out the private data repo there; anyone else needs their own copies of the same files; check them
with `shasum -a 256 data/raw/*.pdf` against `sources_hashes.txt`). Install Ollama, then:

```bash
ollama pull nomic-embed-text
```

```bash
ollama pull qwen2.5:3b
```

```bash
PYTHONPATH=src .venv/bin/python -m erp.ingest.index_chroma --db data/db/sample.sqlite
```

Model requirements: developed on a MacBook Air M2 with 8 GB RAM; `qwen2.5:3b` used about 2.3 GB
loaded. Model name and Ollama URL are in `config/agent.yaml` and `config/ingest.yaml`.

**5. Ask a question**

```bash
PYTHONPATH=src .venv/bin/python -m erp.agent.loop "What was TCS's net margin in FY26?"
```

```bash
.venv/bin/streamlit run app/streamlit_app.py
```

**6. Eval** (dev split; the test split needs `--test` and a typed confirmation, and runs once)

```bash
PYTHONPATH=src .venv/bin/python eval/run_eval.py
```

```bash
PYTHONPATH=src .venv/bin/python scripts/make_results_table.py --readme
```

**7. Demo mode** (replays the newest saved dev run; no model)

```bash
.venv/bin/streamlit run app/streamlit_app.py -- --demo
```

**Clean-clone check** (copies the repo to a temp folder, makes a venv, installs, runs the tests,
builds the sample database, starts the UI in `--demo` mode headlessly; `--worktree` checks what would
be committed now instead of the last commit)

```bash
scripts/clean_clone_check.sh --worktree
```

## 10. Repo layout

```
README.md  PROJECT_PLAN.md  PROGRESS.md  NOTES.md  CLAUDE.md / AGENTS.md (instructions for coding tools)
config/            company, metrics, ratios, DCF, ingest, agent, eval and UI settings (no code)
data/
  manual/          dcf_inputs.yaml (assumption register)
  sample/          facts_sample.csv (12 facts, AI-read, not yet human-verified)
  raw/             private data repo checkout with the PDFs (gitignored)
  db/, chroma/     local SQLite database and vector index (gitignored, rebuilt by commands above)
src/erp/
  db/              schema, loader, validation, duplicate-fact policy
  periods.py, units.py
  tools/           facts, ratios, document search
  dcf/             assumptions loader, engine, checks, run_dcf
  ingest/          PDF -> chunks, embeddings, ChromaDB
  agent/           LLM call, router, guardrails, tools, answer loop, verifier
  eval/            question loader, claim extraction, scoring, metrics, baseline, results table
  ui/              Streamlit page, view model, demo loader
app/streamlit_app.py   UI entry point
eval/              questions.jsonl, run_eval.py, sample_qualitative.py, results/ (gitignored)
scripts/           make_results_table.py, clean_clone_check.sh
tests/             pytest suite (fakes for the LLM and embeddings) + manual live-run scripts
docs/              plain-language notes per milestone, DEMO.md
```

## 11. Limitations and known risks

- One company, one fiscal year of reported figures, 12 facts. Many questions are simply outside the
  data, and the system says so.
- Every figure in the database and every gold answer still awaits human verification.
- A 3B local model is the weakest link: routing and wording vary with small prompt changes. The
  design leans on code checks (pre-check, router checks, verifier, template fallback) for that reason.
- The verifier is strict: any error replaces the model's text with a code-written template answer.
  This costs readability, never a wrong figure, but it checks figures, dates, pages and comparisons,
  not the meaning of qualitative sentences.
- A DCF value per share shown without context could be misread as a target. The UI and answers carry
  an "illustrative, not a prediction, not investment advice" line, and no market price is used.
- Regulatory framing: publishing research recommendations in India may fall under SEBI research
  analyst rules (TO VERIFY; this README is not legal advice). This project publishes no
  recommendations.

## 12. Roadmap

1. Finish the manual groundwork: verify the facts, key the full metric set (FY21 onwards and recent
   quarters), build the hand DCF spreadsheet with a finance reviewer and add the golden test, sign
   off the gold answers, write the author's own report.
2. Run the frozen test split once and report dev and test separately.
3. Small tools for known gaps: unit conversion, a metric-match check against substitution, better
   sub-heading detection for chunking.
4. Then (post-v1): two IT-services peers with the same schema and DCF; later, more companies with
   sector-appropriate valuation methods; earnings-call transcripts.

## 13. Disclaimer and licensing

Illustrative analysis, not investment advice. Nothing here is a recommendation about any security,
and no output is a price target or a valuation verdict. Figures may contain errors; see
section 8 for what has and has not been verified.

Code licence: none chosen yet (no LICENSE file; author to decide, keeping in mind that PyMuPDF is
AGPL-3.0, TO VERIFY). TCS filings are the property of their publisher and are not included.
