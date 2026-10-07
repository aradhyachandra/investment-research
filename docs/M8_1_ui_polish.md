# M8.1: UI polish

Plain-language note for the author: what changed on the page, where each thing comes from, and what
to check before you show it to anyone.

## What it is for

M8 made the page correct (every figure traceable to a page). M8.1 makes it look like a finished
portfolio project without changing what it claims. No agent, router, verifier, DCF engine, retrieval,
eval or data code was changed. The page still does no arithmetic on figures: it lays out what the
tools and the saved eval runs already produce.

Run it the same way as before:

```bash
.venv/bin/streamlit run app/streamlit_app.py -- --demo
```

## What is on the page now

A header (project name, "TCS · FY26 · Ind AS consolidated", the tagline) and the disclaimer sit above
five tabs. The disclaimer is also at the bottom, as before.

1. **Ask.** The question box (live mode) and five one-click examples: a fact, a ratio, a DCF value,
   a qualitative question and a refusal (`config/ui.yaml`, `examples`). In `--demo` mode the buttons
   pick the saved answer to that question; there is no question box because no model runs. Each
   answer now has:
   - a badge saying who wrote it: **Checked by verifier** (green), **Code-built fallback answer**
     (orange), **Refused by code** (grey), or a red badge when no verifier ran or its errors were
     ignored (the eval's "verifier off" arm);
   - figure cards with coloured chips: blue **Filing**, violet **Author's note**, grey for anything
     else, then the document and PDF page;
   - next to every DCF figure: the STATUS line of the assumptions file and the fixed DCF footer;
   - calculation paths as step cards (inputs with pages → formula → result for a ratio; discount
     rate → cash flows → bridge for the DCF), with the full tables still underneath;
   - a **Source page** picker that renders the cited PDF page (see below).
2. **Company snapshot.** Four cards (revenue, net margin, basic EPS, cash) for FY26 with FY25 under
   each. Values come from `get_financial_fact` / `compute_ratio` through the agent's tool layer, so
   they are the same strings an answer would show. Revenue and EPS also show the growth ratio the
   tools compute. Each card has its source chip and either "verified by <name>" (read from the
   database's `verified_by`, with the date) or "not yet checked by a human". Which cards appear is
   config (`snapshot` in `config/ui.yaml`).
3. **DCF.** A bar chart of the bear/base/bull value per share, the WACC × terminal-growth grid as a
   heatmap (the base scenario's own inputs outlined), a waterfall from enterprise value to equity
   value, and the base assumptions with rationale and source. The STATUS line is at the top and the
   fixed footer is under every chart.
4. **How it works.** A flow diagram (question → pre-check → router → tools → composer → verifier →
   answer, with the two safety exits) and five sentences.
5. **Evaluation.** For the latest finished test and dev runs: a bar chart and a "k of n" table of
   four rows (numeric accuracy, gold-matching citations, behaviour correct, unsupported numeric
   claims) for the full system vs naive RAG, then the caveats, read straight from README section 7
   so the two cannot drift apart. If `eval/results/` is empty (a fresh clone), the tab says so.

## Where the numbers come from

- **Snapshot and DCF tabs** call the deterministic tools (no LLM). `compute_ratio` and `run_dcf`
  write an audit row on every call, so the page first copies the database into memory and runs the
  tools on the copy. The file `data/db/sample.sqlite` is only read. If it does not exist, the tabs
  say how to build it.
- **Charts** only place what the engine produced. Two small exceptions, both display geometry: the
  eval bars are k ÷ n (the table and labels show "k of n"), and the waterfall's bar ends are running
  totals of the engine's bridge items (a test checks that the last bar ends exactly at the engine's
  equity value). Every label on a chart is the tool layer's formatted string.
- **Colours** are a colour-blind-checked set (checked with a palette validator): blue for the full
  system and totals, orange for naive RAG and deductions, aqua for additions. Every bar also has a
  text label, so colour is never the only cue.

## The source page preview

`src/erp/ui/page_preview.py`. For a cited figure or passage it:

1. finds the PDF by the document title in `config/companies/tcs.yaml` (`sources[].title` →
   `file_name`), inside `data/raw/`;
2. opens the page with PyMuPDF, searches for the figure as the filing prints it (Indian grouping
   first, e.g. "2,67,021", then "267,021", then "267021") or for the passage's sentences;
3. draws a highlight on the in-memory copy and renders the page as a PNG for the browser. The PDF is
   closed without saving; no PDF or page image is written anywhere in the repo.

If the text cannot be found (some designed pages have broken glyph maps), the page is shown with no
highlight and a note saying so. If `data/raw/` is missing, the tab shows a short note instead.

Checked against every saved eval answer: every cited **figure** is found and highlighted. Sixteen
cited **passages** are not (cover pages, pages whose extracted text has garbled characters, and
passages with no full sentence); they are shown without a highlight.

One fix was needed: the annual report's text layer splits some figures ("49, 454" for 49,454,
"1, 08, 47 8" for 1,08,478). When a plain search fails, the code joins neighbouring words and tries
again (whole words only).

## Files

- `src/erp/ui/app.py`: the page (rewritten layout; same answer sections as M8).
- `src/erp/ui/view_model.py`: added chips, the answer badge, step cards, page-preview targets,
  example questions.
- `src/erp/ui/snapshot.py`, `dcf_view.py`, `eval_view.py`: records for the three new tabs.
- `src/erp/ui/page_preview.py`: PDF page rendering and highlighting.
- `src/erp/ui/charts.py`: the Altair charts (Altair was already pinned; no new dependency).
- `config/ui.yaml`: header, examples, snapshot cards, DCF scenarios, `raw_dir`.
- `.streamlit/config.toml`: theme (blue accent, off-white page, serif headings, bundled fonts only).
- `tests/test_ui_polish.py`: 43 tests (view models, PDF preview on generated PDFs, and the page
  itself headless with `AppTest`). `tests/test_ui.py`: the page tests now pass a missing database
  path, so they test the Ask tab only and do not depend on your local database.

## Choices worth knowing

- **Example questions are dev-split questions** (EV-A01, EV-C01, EV-D04, EV-E01, EV-G01), read from
  `eval/questions.jsonl`. A test stops a frozen test-split question from ever becoming an example.
  The "DCF value" example is the terminal-value share (EV-D04), as in docs/DEMO.md, not the per-share
  value; switch it to EV-D01 in `config/ui.yaml` if you want the per-share figure there.
- **The DCF tab shows only the base scenario's assumptions table.** Bear and bull override a few of
  them; the caption points to the YAML file.
- **The snapshot shows the name only when one person verified every fact behind a card.** With the
  test fixture (unverified facts) the cards say "not yet checked by a human".
- **No market price anywhere**, and a test scans every tab of the rendered page for advice words and
  for "market price", "share price", "current price" and "target".

## What to review

Things a reader could misread as a price target or advice:

1. **The DCF scenario bar chart** (bear INR 1,445.11, base INR 1,914.82, bull INR 2,351.66 per share,
   from the current assumptions file) is the most likely to be read as a target range. It has the
   STATUS line above it, "not a forecast" in the caption and the fixed footer under it, and no price
   next to it. Decide whether per-share bars belong on the page at all, or whether the tab should lead
   with enterprise value or the terminal-value share instead.
2. **The sensitivity heatmap** is a grid of per-share values; same concern.
3. **"bear / base / bull"** are the assumptions file's scenario names. They read like market
   language; consider renaming them in the YAML (your file; I did not touch it).
4. **The waterfall caption** ends with "value per share INR 1,914.82 per share (engine output)".

Other things to check:

5. **"Checked by verifier"** (green) means the figures match tool results, not that the answer is
   right. The caption under the answer says this; check the badge alone is not too strong.
6. **"verified by Aradhya Chandra"** on the snapshot is read from `verified_by`. It is your sign-off
   only; no finance reviewer. Check you are happy for it to appear on screenshots.
7. **Eval chart** bars are k ÷ n on small n (14, 8, 21 ...). The table and labels give "k of n";
   check the bars do not suggest more precision than that.
8. **Highlights** on a dense table: make sure the highlighted cell is the cited one before using a
   screenshot (see NOTES.md).
9. **Example buttons**: the refusal example's text ("Will TCS's share price go up next year?") is
   shown in its tooltip; the answer is the fixed refusal.
10. **Screenshots** with a rendered annual-report page: check the PDF's terms before publishing them.
