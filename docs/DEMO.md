# Demo script (5 questions, about 5 minutes)

Runs in `--demo` mode: the page replays answers saved by a dev eval run, so no model is called and
the result is the same every time.

```bash
.venv/bin/streamlit run app/streamlit_app.py -- --demo
```

Needs a saved dev run in `eval/results/dev/` (made by `eval/run_eval.py` on a machine with the PDFs
and Ollama). `eval/results/` is gitignored, so a fresh clone shows "no saved eval runs" instead.
The left sidebar lists the saved questions; one click picks one.

Before you start, say three things:
- Not investment advice; v1 is TCS only.
- "AI interprets, code calculates, sources prove": the small local model picks tools and writes
  prose, Python does every calculation, and every figure carries a page or a calculation path.
- The facts and gold answers are still waiting for human verification (README section 8).

---

## 1. Fact lookup: EV-A01 "What was TCS's consolidated revenue from operations in FY26?"

Point out:
- The figure under "Figures in the answer" has a **Filing** badge, the document title, the PDF page
  and the printed page, the period, the basis (consolidated) and the standard (Ind AS). That is the
  trace from answer to source page with no clicks.
- "Not yet checked by a human" next to the figure: the fact was loaded as `llm_extracted`. The UI
  does not hide this.
- The note that FY26 runs April 2025 to March 2026: periods come from code, not the model.
- The line under the answer says what the verifier checked (figures against tool results) and what
  it does not check (wording, figures quoted from passages).

## 2. Ratio: EV-C01 "What was TCS's net margin in FY26 ...?"

Point out:
- Open "How the figures were computed": the calculation path lists both inputs (profit attributable
  to shareholders, revenue) with their fact ids and pages, the formula, and the result.
- The model never divided anything. `compute_ratio` did, and stored the result with the code
  version that produced it.
- Net margin here is statutory (after exceptional items). Compare with EV-F01 if asked why TCS's own
  headline growth figure differs.

## 3. DCF: EV-D04 "In the base-case DCF, what share of enterprise value comes from the terminal value?"

Point out:
- The scenario label says the assumptions are AI-drafted, author-adopted and not reviewed by a
  finance partner. Say this out loud.
- Open the calculation path: the WACC build, the FCFF table, terminal value and enterprise value, the
  bridge to equity, the sensitivity grid, and each assumption with its rationale and source.
- Why this question and not the per-share value (EV-D01): terminal value share is the first sanity
  check of any DCF, and it avoids putting a per-share number on screen that a viewer could mistake
  for a target. If you do show EV-D01, repeat that it is what the stated assumptions imply, not a
  prediction, and that no market price is used anywhere.
- The DCF eval gold is the engine's own output, so a "correct" mark here means consistent, not
  independently right. The golden test against a hand spreadsheet is not done yet.

## 4. Qualitative: EV-E01 "How does TCS say it manages cyber-attack risk?"

Point out:
- The router chose `search_documents`; the answer is written from annual-report passages, and the
  passage list shows each one's page (open a passage to read the chunk text).
- Passages are badged **Filing**. An author's own note would be badged **Author's note** and labelled
  as interpretation, not evidence; none is indexed yet.
- Be honest about the limits: the verifier checks figures, not whether a passage supports a sentence.
  In the saved run, one cited passage is from the back cover page, which is unlikely to support the
  claim. Qualitative citation support is meant to be labelled by hand (not done yet).

## 5. Refusal: EV-G01 "Will TCS's share price go up next year?"

Point out:
- The refusal is a fixed text written in code. It came from the pattern pre-check, before the model
  was called (the page does not show the route; the saved answer's `route.problems` says so). In
  testing, the 3B router alone answered several such questions, which is why the pre-check exists.
- The refusal says what the tool can do instead (reported figures, ratios, what DCF assumptions
  imply, what the filings say).
- Optional: EV-G03 (compare with Infosys) shows the "TCS only" refusal.

---

## Optional: show a failure

EV-E04 ("interest on lease liabilities") answers "not available": the router now searches, but
retrieval misses the lease note. Showing one honest miss next to the passes makes the rest more
credible, and it is listed in the README's known weaknesses.

## Screenshots

None are committed. Taking them needs a browser and a saved dev run; an automated headless Chrome
capture only caught the loading skeleton of the Streamlit page. If you add them, take them from
`--demo` mode, keep passages collapsed (they contain annual-report text), and prefer the DCF
terminal-value question over the per-share one.
