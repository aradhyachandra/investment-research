# PROGRESS

## 2026-10-04 — M6: verifier, refusal handling, DCF footer; retrieval investigated

**Done**
- `src/erp/agent/verifier.py`: `verify_answer(text, tool_results, cfg, listed_number_ids, cited_ids)
  -> VerifierReport` (ok, issues with check/severity/span/message, numbers_in_text). Deterministic,
  no LLM. Checks: every number is a tool number (formatting and rounding as displayed allowed; unit
  changes not); dates and page numbers must be in the tool results; passage-only numbers are warnings;
  cited ids exist and back the figure in their sentence; comparisons ("increased", "fell", "higher
  than", "from X to Y", "decreases to Y") need both values in the tool results and the right
  direction; DCF grid values must be the cell for the WACC/growth the sentence states; judgement
  words ("stable", "strong") with no figure are warnings.
- Loop (`loop.py`): verifier runs on the composed text; any error -> the code-written template
  answer, with the report in `Answer.verification`, a summary in `warnings`, and the rejected text in
  `Answer.rejected_text` (never shown). `numbers_used` is now the tool numbers the text actually says
  (fixes M5's "numbers_used lists figures the text never mentions").
- Fixed DCF footer, added by code to every answer that used `run_dcf` (LLM and template paths):
  "Illustrative value implied by the stated assumptions, which were drafted with AI assistance; not a
  prediction or investment advice." Text in `config/agent.yaml` (`dcf_footer`).
- Refusal pre-check (`src/erp/agent/guardrails.py`), before the router, no LLM: advice/verdict and
  price-prediction patterns (`config/agent.yaml` `guardrails`), other-company names
  (`config/companies/tcs.yaml` `guardrails.other_company_names`), and any period after the latest
  data (-> `outside_data`). Fixed refusal texts as before; the router's refusal stays as a second line.
- Tool numbers now carry `quantity`, `measures_change`, `variant`, `conditions` (for the verifier);
  the DCF sensitivity output also lists the grid's WACC and growth values as numbers.
- Runners: `tests/run_guardrail_phrasings.py` (pre-check vs router, live); `run_provisional_dev.py`
  prints the verifier result.
- Tests: 504 passing (118 new): `test_verifier.py`, `test_guardrails.py`, `test_m6_acceptance.py`.

**M6 acceptance (plan Section 9)**
- Injected bad numbers (typo, wrong unit, converted unit, LLM arithmetic), bad citations (unknown id
  in text or lists, citation to the wrong figure), unsupported and wrong-direction comparisons, the
  "decreases to 5.00%" slip and a grid value for the wrong conditions: all caught in tests, end to
  end through the loop (template answer shipped, report recorded).
- Guardrail questions (category G) on dev: PDEV-18/19/20 refused with the fixed texts, deterministic
  (even with a router scripted never to refuse) and live. "Dev" = the PROVISIONAL questions
  (`eval/questions.jsonl` still does not exist).
- Live, qwen2.5:3b, 20 PROVISIONAL dev questions, three runs: routing 20 of 20 each time; verifier
  passed 16 of 17 answered questions each time and rejected PDEV-13 each time, every rejection a real
  slip (run 1: "terminal growth decreases to 5.00%" = unchanged; runs 2-3: grid values quoted for the
  wrong WACC/growth, e.g. "decreasing terminal growth ... increases the value per share to INR
  1,973.62", which is the cell where WACC also fell). No false rejections seen. One run's PDEV-13
  composer call timed out (300 s; 20 s on re-run) -> template answer.
- Tricky phrasings live (`run_guardrail_phrasings.py`, 13 PROVISIONAL): 12 of 13 handled as intended.
  The router alone answered "Is TCS undervalued?", "TCS vs Infosys margins", "Does the DCF show TCS is
  undervalued?" and "Is the share price below the DCF value per share?"; the pre-check refused them.
  Legit-but-advice-sounding ("What does the DCF imply?", "Did TCS buy back shares?") pass. Miss:
  "compare with the industry average" (neither layer refuses).

**Retrieval (time-boxed, no code changed)**
- recall@5 on the 12 PROVISIONAL probes: before 9 of 12. Tried: strip the company name from the query
  -> 11 of 12; keyword-overlap re-rank -> 11-12 of 12 depending on two settings. Neither adopted (see
  NOTES.md: the agent's real queries come from the router and rarely contain "TCS", stripping hurt one
  live wording, and the re-rank settings would be tuned on the probes themselves). Learned: the
  client-concentration sentence (PDF 226) is buried in a table-heavy chunk (a chunking fix); for
  dividends the right page was retrieved at rank 3 but the composer still said "not available".

**Fallback router**: not built. Routing is 20 of 20 on the provisional dev questions (threshold ~90%).

**Decisions**
- The verifier is strict: any error -> template. Judgement words, passage-only numbers, missing
  `[id]` brackets and numbers_used corrections are warnings only.
- Added a deterministic refusal pre-check (not in the brief) because the live router alone answered
  4 of the tricky phrasings. Pre-check refusals carry a RoutePlan marked "refused by the pattern
  pre-check" so scoring still works.
- Added the "period after the latest data" refusal after the live run showed "revenue in FY28" being
  answered.
- Unknown ids in the composer's id lists are now errors (M5 dropped them with a warning).
- M5 tests changed where M6 changed behaviour: the scripted composer in `test_m5_acceptance.py` now
  writes the figures it lists (numbers_used comes from the text); the sensitivity tool test expects
  the grid's axis values as numbers.
- `dcf_footer` lives in config, so its wording can change after a finance-partner review.

**Known issues / flags for the author**
- All verifier rules, guardrail patterns and aliases were written against Claude's own phrasings and
  20 PROVISIONAL questions: TO VERIFY on the author's dev split (P0.4). See NOTES.md for the list.
- The live model never writes `[id]` citations, so the per-sentence citation check rarely bites live
  (citations are attached by code anyway).
- Answers with passage numbers (e.g. "ISO 27001") pass with a warning; decide if they should block.
- "Compare with the industry average" is not refused.
- PDEV-15/16 still answer "not available" (retrieval/composer, see above).

**Next**
- M7: eval harness + naive-RAG baseline + ablation (verifier on vs off). Not started. Needs
  `eval/questions.jsonl` (P0.4) for real numbers.

**How to run**
```
PYTHONPATH=src:tests .venv/bin/pytest -q
PYTHONPATH=src:tests .venv/bin/python tests/run_provisional_dev.py
PYTHONPATH=src:tests .venv/bin/python tests/run_guardrail_phrasings.py
PYTHONPATH=src:tests .venv/bin/python tests/run_provisional_probes.py
```

---

## 2026-10-04 — M5: tool layer, two-step router (v1), structured Answer; P0.6 model test

**Done**
- P0.6 model test (`tests/run_p06_model_test.py` + routing runs): llama3.2, qwen2.5:3b, phi4-mini
  (the last two pulled with the author's OK). **Chosen: qwen2.5:3b** (NOTES.md has the tables).
- `config/agent.yaml`: runtime model and Ollama settings, router/tool settings, number display
  formats, advice-language guard list.
- `src/erp/agent/llm.py`: `call_llm`, the one runtime LLM function (Ollama `/api/chat`, model
  from config, temperature 0, seed 0, optional JSON-schema `format`). No API key.
- `src/erp/agent/tools.py`: the four tools behind one interface, `run_tool(ToolCall, ToolEnv) ->
  ToolResult`. Typed inputs (`FactArgs`, `RatioArgs`, `DCFArgs`, `SearchArgs`); every result has
  `numbers` (value, unit, period, basis, code-formatted display, evidence_id), `evidence`
  (evidence_id, kind, source, page, printed page, period, basis, standard, verified, formula,
  input ids), `passages`, `notes`, `error`. Evidence ids: `fact:<id>`, `calc:<id>`, `dcf:<run_id>`,
  `chunk:<chunk_id>`. Expected tool errors become `ok=False` results; anything else raises.
- `src/erp/agent/router.py`: Router v1 step 1. Menus (metrics, ratios, periods with data, DCF
  scenario names, tools) come from config/DB and are enums in the JSON schema. `calls` first in
  the schema; worked examples in the prompt (filtered to ids the company has). Out-of-scope or a
  refusal reason -> refuse, no tools. Unreadable reply -> `routing_failed`, never a guess.
- `src/erp/agent/loop.py`: `answer_question(question, env, llm_fn)`: route -> tools in code ->
  compose (LLM picks used number ids / cited ids from enums) -> `Answer`. Fixed refusal texts;
  template answer (code-written) if the composer reply is unusable or has advice/verdict words;
  refusal "data_not_available" if every tool failed. CLI: `python -m erp.agent.loop "question"`.
- `src/erp/agent/answer_schema.py`: `Answer` (answer_text, numbers_used, citations, refused,
  refusal_reason, limitations, route, tool_results, composed_by, model, warnings, disclaimer).
- `src/erp/agent/route_score.py`: routing accuracy as its own metric (tools right / tools and
  arguments right / refusal reason), reported as counts.
- PROVISIONAL dev questions: `tests/provisional_dev_questions.jsonl` (20, Claude-written, expected
  route only, 10 marked `e2e`). Live runner: `tests/run_provisional_dev.py`.
- Tests: 386 passing (73 new): tool layer, router parsing/schema/prompt, route scoring, loop
  (refusals, failures, dropped ids, advice guard, template fallback), M5 acceptance (10 questions
  end to end with a scripted LLM; routing 20 of 20 with the gold route).
- Local `data/db/sample.sqlite` rebuilt with `load_facts --replace` (it predated the two
  `profit_attributable_to_owners` rows; source ids unchanged, Chroma still matches).

**M5 acceptance (plan Section 9)**
- Deterministic: 10 of 10 PROVISIONAL e2e questions answered (or correctly refused) with every
  number pointing at a citation that carries source, page, period and basis (DCF on the TOY
  fixture renamed to TCS inside the test only).
- Live, qwen2.5:3b, real DB + Chroma, all 20 questions (~166 s): 15 answered, every number pointing
  at a filled citation; 3 guardrail refusals correct; 2 DCF questions answered "assumptions file
  does not exist yet". Of the 10 e2e: 8 answered, 1 correct refusal, 1 DCF "not available".
- Routing accuracy (tools and arguments right): 16 of 20 live without a DCF file (misses: 2 DCF
  scenario names it had to guess, PDEV-06 added an extra search, PDEV-17 skipped the FY25 ratio);
  20 of 20 when scenario names are available. PROVISIONAL questions, prompt tuned on them.

**Decisions**
- Router v1 (two-step) is the only router built. Free-form tool calling (v0) was compared only in
  the P0.6 toy test. The plan's M5 row says "Router v0", Section 3.3 says build v1 first on 8 GB;
  followed 3.3 as asked.
- There was no existing runtime LLM function (only `embed_texts` for embeddings), so `call_llm`
  was created as the one function.
- The ticker is never chosen by the LLM (`default_ticker` in config).
- Search queries are free text; the router does not set search filters (doc_type, fiscal year).
- Numbers shown to the LLM are formatted by code; raw values never appear in the prompt.
- `numbers_used` = number ids the composer lists (unknown ids dropped); if none listed, all tool
  numbers attached with a warning. Citations = evidence of those numbers + calc inputs + cited
  chunks (all passages if none cited, with a warning).
- Refusal texts are fixed in code. The advice-language guard is a whole-word list in config.
- The plan's Answer schema (8.3) has `claims[]`; M5 uses `numbers_used` + `citations` as asked.
  `data_as_of` is not filled yet.

**Known issues / flags for the author**
- `eval/questions.jsonl` (P0.4) does not exist, so all questions are PROVISIONAL (tests/ only).
- `data/manual/dcf_inputs.yaml` now exists (AI-drafted, adopted by the author 2026-10-04, no finance-partner review; see its header). Live DCF questions can run once Ollama is up. (Earlier line said it did not exist.)
- Unsupported comparison seen live (PDEV-17, "net margin decreased" with no FY25 figure): M6.
- No check yet that numbers written in `answer_text` match tool numbers (verifier, M6).
- Unit-conversion questions ("in INR million") and pure period questions have no tool; the
  composer is told not to convert. Consider small `convert_units` / `resolve_period` tools.
- Retrieval misses (capital allocation, client concentration) carry over from M4.
- qwen2.5:3b licence TO VERIFY (see NOTES.md).

**Next**
- M6: verifier (numeric grounding, citation existence) + refusal handling (not started).

**How to run**
```
PYTHONPATH=src .venv/bin/python -m erp.agent.loop "What was TCS's net margin in FY26?"
PYTHONPATH=src:tests .venv/bin/python tests/run_provisional_dev.py --e2e-only
PYTHONPATH=src:tests .venv/bin/python tests/run_provisional_dev.py --route-only --model qwen2.5:3b --model llama3.2
PYTHONPATH=src .venv/bin/python tests/run_p06_model_test.py qwen2.5:3b phi4-mini llama3.2
```

---

## 2026-10-04 — M4: annual report PDF -> chunks -> ChromaDB; search_documents

**Done**
- `src/erp/ingest/pdf_to_chunks.py`: PyMuPDF text per page (PDF text order), running
  headers/footers dropped, two-page spreads split into halves, headings by font (bold and
  >= 1.5 pt above body size), chunks of <= ~1500 chars on line boundaries with 200-char overlap,
  kept within one page except a short page-end piece (< 200 chars) that joins the next page when
  no new heading starts there (then `page`..`page_end`). `is_table_heavy` flag. Printed page
  labels from config, with a footer cross-check that reports disagreements.
- `src/erp/ingest/embed.py`: `embed_texts(texts, purpose)`, the one embedding function (Ollama
  `/api/embed`, model and URL from `config/ingest.yaml`, task prefixes for nomic-embed-text);
  `ollama_status()` for checks and test skips.
- `src/erp/ingest/index_chroma.py`: `ChunkMetadata` (pydantic) validates every chunk before any
  write; `ingest_source` (registered in SQLite `source_document`, doc type in
  annual_report/fact_sheet/quarterly_results, not under `data/sample/generated/`, file sha256
  = registered sha256; skip if unchanged, re-index if hash or embedding model changed, never leave
  half a document); `ingest_registered`; CLI. Chroma under `data/chroma/` (gitignored), cosine,
  telemetry off, built-in embedder disabled.
- `src/erp/tools/search.py`: `search_documents(query, top_k=5, doc_type, fiscal_year, source_id)`
  -> `list[SearchResult]` (pydantic): text, source_id, doc_type, doc_title, fiscal_year, page,
  page_end, page_label, section, chunk_id, is_table_heavy, score. Sorted by score; table-heavy
  scores x 0.85; records without a valid page/source_id are dropped with a warning.
- Config: new `config/ingest.yaml`; `page_labels` for both sources in `config/companies/tcs.yaml`.
- Real run: AR FY26 -> 1118 chunks (229 table-heavy), fact sheet Q1 FY27 -> 20 chunks (15),
  ~60 s, ~245 MB peak. Re-run: both skipped in ~1 s.
- PROVISIONAL retrieval probes (12, `tests/provisional_retrieval_probes.jsonl`, runner
  `tests/run_provisional_probes.py`): recall@5 = 9 of 12, recall@10 = 11 of 12. Baseline only.
- Tests: 313 passing (61 new: chunking on built PDFs + real AR checks, metadata validation,
  idempotency/re-index/refusals, search filters/order/down-rank, probe-file format, 2 live Ollama
  tests that skip automatically when Ollama or the model is missing).
- Pinned `pymupdf==1.28.2`, `chromadb==1.5.9` and chromadb's dependencies.

**Decisions**
- Metadata uses `doc_type` (the `source_document` column) where plan 8.5 says `source_type`.
- `source_id` comes from SQLite, so `erp.db.load_facts` must have built the DB first; the
  Chroma ids are `src{source_id}-{sha[:12]}-p{page}-{n}` (stable for the same file and DB).
- Printed page labels come from config, not footers (footers drop digits in this PDF). Pages
  without a printed number get `page_label = ""` (Chroma metadata cannot hold None).
- Spread halves share the PDF page index but get their own printed label (PDF 4 -> "4" / "5").
- `fiscal_year` = fiscal year of the document's `period_covered` (Q1 FY27 fact sheet -> 2027).
- An unregistered or changed-but-not-re-registered file is refused rather than indexed.
- The probe runner lives in `tests/` but is not a pytest test (needs Ollama and the real index).

**Known issues / flags for the author**
- Plan M4 acceptance is recall@k on the dev category E questions with a target set after a
  first run. Those questions don't exist yet (P0.4), so only the provisional baseline is recorded.
- Extraction quality issues (letter-spacing, broken glyphs, mangled numbers, coarse sections):
  see NOTES.md. `page_labels` ranges need the author's check.
- Chroma downloaded its default ONNX model once during Claude's exploration (before the guard
  existed): ~80 MB in `~/.cache/chroma/onnx_models/`, outside the repo. Safe to delete.
- The plan's corpus includes the author's report (`analyst_note`); not indexed in M4 by request.

**Next**
- M5: tool layer + agent loop (Router v0) + structured Answer (not started). Run P0.6 model test first.

**How to run**
```
PYTHONPATH=src .venv/bin/python -m erp.db.load_facts --csv data/sample/facts_sample.csv --entry-method llm_extracted --replace
PYTHONPATH=src .venv/bin/python -m erp.ingest.index_chroma --db data/db/sample.sqlite
PYTHONPATH=src:tests .venv/bin/python tests/run_provisional_probes.py
```

---

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
