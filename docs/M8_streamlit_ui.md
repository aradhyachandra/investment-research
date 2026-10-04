# M8: the Streamlit UI

Plain-language note for the author: what the page shows, how to run it, and the choices behind it.

## What it is for

The plan's test for this milestone: a reviewer can trace one number back to its source page in 3
clicks or fewer. The page is built around that. Every figure in an answer has its source
document and PDF page printed right under it, so tracing a figure to its page takes **no click**.
The retrieved text of a passage takes **one click** (an expander). A ratio's full calculation
(inputs, formula, result) also takes one click.

The page only displays things. It does no arithmetic of its own and calls no tools. Figures are
the tool layer's own display strings, or stored tool values put through the same formatting
function the agent uses (`tools.format_number`). DCF rates are stored as decimals and shown as
percent (× 100), the same way `tools.py` already does it.

## How to run it

From the repo root, with the venv set up (`.venv/bin/pip install -r requirements.txt`):

```bash
.venv/bin/streamlit run app/streamlit_app.py -- --demo
```

**Demo mode** (`--demo`) shows saved answers from the newest eval run in `eval/results/dev/`. No
model runs and Ollama is not needed. Pick a question from the list on the left (one click).
Options:

```bash
.venv/bin/streamlit run app/streamlit_app.py -- --demo eval/results/dev/20261004-155610_6788b014
.venv/bin/streamlit run app/streamlit_app.py -- --demo --system naive_rag
```

`--system` can be `full` (default), `full_no_verifier` or `naive_rag`, i.e. the eval's comparison
arms. A banner says when you are not looking at the full system.

**Live mode** (no `--demo`) shows a question box and calls `answer_question`, so it needs Ollama
running with the model in `config/agent.yaml`. It reads `data/db/sample.sqlite` (change with
`--db`).

```bash
.venv/bin/streamlit run app/streamlit_app.py
```

Then open http://localhost:8501. `.streamlit/config.toml` turns off Streamlit's usage telemetry.

## What the page shows, top to bottom

1. **Disclaimer**, "Illustrative analysis, not investment advice.", at the top and bottom of
   every page, in every mode. It comes from `config/ui.yaml`.
2. **The answer text**, with one line saying who wrote it: the model, or code (the fallback the
   verifier forces when it rejects the model's text). This line is visible without a click. The
   line does not claim more than the verifier does: it says the verifier checks figures against
   tool results, not wording or figures quoted from passages.
3. **Notes and limitations**, e.g. "Not yet checked by a human: fact:1".
4. **Verifier box**, collapsed. It holds the verifier's status, each issue (severity, check, the
   words it flagged, message) and the agent's warnings. If the fallback was used, the box title
   says so.
5. **Figures in the answer**, one per figure. Under each: a badge, the document, the PDF page
   with the printed page in brackets (plan 4.1 rule 6), the period, the basis, the accounting
   standard, "not yet checked by a human" if `verified` is false, and the evidence id. A
   ratio also lists its input facts with their pages, so even a computed figure reaches a page
   with no click.
6. **Passages cited**, each with its citation line and a collapsed box holding the chunk text the
   agent retrieved. PDFs are never copied into the app.
7. **How the figures were computed**, one collapsed box per ratio or DCF run.
   - Ratio: an inputs table (role, figure, value, fact id, document, page, checked or not), the
     formula and its version, the definition, the result.
   - DCF: the `STATUS:` line from the header of `data/manual/dcf_inputs.yaml` (author-adopted,
     not reviewed by a finance partner), the scenario label (which says AI-drafted), the
     formulas, the WACC build, the year-by-year FCFF table, terminal value and EV, the bridge to
     equity, the sensitivity grid (if the agent asked for it), every assumption with value,
     rationale and source, the sanity checks, and the fixed DCF footer.
8. **All citations**, collapsed.

Refusals show the agent's fixed refusal text in a warning box, with the verifier box (which says
the verifier did not run).

## Badges

The badge comes from the source document's `doc_type`:

| doc_type | Badge |
|---|---|
| annual_report, quarterly_results, fact_sheet | **Filing** |
| analyst_note, generated_sample | **Author's note** |
| anything else | Other document |
| not found in the answer | Source type not recorded |
| calc / dcf_run / period (not documents) | Calculation / DCF model / Company config |

A `generated_sample` note also gets the line "AI-generated sample note (reading aid), not written
by the author", so an LLM summary is never passed off as your own writing. No notes are indexed
yet, so this path is tested with a hand-built fake answer.

The Answer object's citations (`Evidence`) have no `doc_type`. The UI reads it from the tool output
stored inside the Answer (`tool_results[].detail`): facts carry `source_doc_type`, search hits
carry `doc_type`. No schema change was needed.

## Files

- `app/streamlit_app.py`: entry file (puts `src/` on the path, calls `main`).
- `src/erp/ui/view_model.py`: Answer → plain display records. No Streamlit. Most of the tests are here.
- `src/erp/ui/app.py`: lays the records out with plain Streamlit calls. No custom JavaScript, no raw HTML.
- `src/erp/ui/demo.py`: loads saved answers from an eval run folder (read only).
- `config/ui.yaml`: disclaimer, badge mapping, demo folder, live DB path.
- `tests/test_ui.py`: 37 tests. Answers come from the real pipeline with the scripted fake LLM,
  or are built by hand. The page itself is tested headless with Streamlit's `AppTest` (no
  browser, no model).

## Choices worth knowing

- **Claims are figures and passages, not sentences.** The Answer has `numbers_used` (the figures
  the text says) and `citations`, not the plan's sentence-level `claims[]`. So the "claim list"
  is the figures plus the passages cited.
- **The rejected model text is not shown.** When the verifier rejects the model's text, the page
  shows the verifier's issues (including the flagged words) but not the full rejected text,
  because it may contain unsupported figures. It is still in the saved Answer (`rejected_text`)
  if you want it shown in the box.
- **The demo list is a radio list, not a dropdown**, so picking a question is one click.
- **Chunk text** is the full search hit stored in the answer. It is the extracted PDF text, with
  the known extraction problems (e.g. "H30.00" for ₹30.00).
- **The DCF status line is read from the current assumptions file**, not from the copy stored with
  the DCF run. If you change that file later, older saved answers will show the new status line.

## What to review

Things on the page that could mislead a reader:

1. **The DCF value per share** (e.g. "INR 1,914.82 per share") sits in a table titled "Enterprise
   value to equity value". No market price is shown next to it and there is no verdict wording, but
   a careless reader could still take a per-share figure as a target. The status line, the
   scenario label and the footer say what it is. Decide whether that is enough.
2. **Model text that passes the verifier can still be wrong in words.** Saved EV-F01: the model
   calls the filing's 8.8% "growth in attributable profit", but the passage says EPS growth. The
   verifier only warns ("appears only in passage text"). The caption now says the verifier checks
   figures, not wording, and counts the warnings, but the text itself is shown as written.
3. **"Not yet checked by a human"** shows on every fact today (all are `llm_extracted`). Check it
   is visible enough for a screenshot (M9).
4. **"Document period"** on a passage is the period of the whole document (e.g. FY26 for the
   annual report), not of the sentence. A passage about FY25 still shows "document period FY26".
5. **Author's note badge on AI-generated notes** (as asked). The extra line says AI-generated; see
   NOTES.md if you want a third badge instead.
6. **The DCF status line is read from the current assumptions file** (see above).
7. **Passage lists**: when the model cited no passage, every retrieved passage is listed, with a
   caption saying they may not support the answer. In template answers the caption says the list
   was made by code.

Also check:

- `config/ui.yaml` badge lists and the disclaimer text.
- The DCF formula lines in `view_model.py` (`DCF_FORMULAS`) match how you would explain the engine.
- `.claude/launch.json` (new; lets Claude Code's browser pane start the demo server). Delete it if
  you don't want it in the repo.
- The live walkthrough (your run): 5 questions, one per type (figure, ratio, DCF, passage,
  refusal). For one figure, count the clicks from answer to page.
