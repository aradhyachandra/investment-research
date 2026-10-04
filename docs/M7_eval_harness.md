# M7: the eval harness, the naive-RAG baseline and the verifier ablation

## What it is for

Until now every "it works" was a handful of checks on questions Claude wrote. M7 is the
measuring tape: one command runs the whole system on the author's question set
(`eval/questions.jsonl`), scores every answer the same way, and saves the evidence. It also
runs two comparisons, so a score means something:

- **Naive RAG (baseline):** the "chat with a PDF" approach this project is meant to beat. Same
  local model (qwen2.5:3b), same Chroma index of the annual report, same questions. The question
  goes straight to the search, the top 5 passages go to the model, its text is taken as is. No
  SQLite, no tools, no refusal pre-check, no verifier.
- **Verifier off (ablation):** the full system, except an answer the verifier would reject is
  shipped anyway. The verifier still writes its report, so you can see what it would have caught.

## How a run works

`eval/run_eval.py` (code in `src/erp/eval/`):

1. Reads the questions for one split (dev by default). Never writes to the file.
2. For each system and question, gets an `Answer` (the same structured answer the app uses).
3. Reads claims out of the answer **text** with the verifier's number reader, the same way for
   all three systems (`claims.py`):
   - a numeric claim is a number written in the text, with its unit and the periods named in its
     sentence; page numbers, citation ids, dates and years are not claims;
   - a qualitative claim is a non-numeric sentence of an LLM-written answer.
4. Scores each answer against its question (`score.py`), adds the scores up as counts
   (`metrics.py`), and saves everything in `eval/results/dev/<time>_<git sha>/`.

## The metrics, in plain words

| Metric | Question it answers |
|---|---|
| Numeric accuracy | Of the questions that have a gold number, how many answers contain that number with the right unit and period? Reported facts must match exactly; ratios and DCF values may be off by the question's `tolerance` (0.5% relative). |
| Citation correctness (numeric) | Do the numeric claims point at the gold page? Shown twice: over all numeric claims, and over only the claims that matched the gold value. A ratio's citation is the pages of its input facts. |
| Citation correctness (qualitative) | Does the cited passage actually support the sentence? Code cannot judge this; `eval/sample_qualitative.py` samples ~20 claims into a CSV for you to label. |
| Routing | Did the router pick the tools the question's category needs (e.g. C needs `compute_ratio`), and, for A/B/C, the gold period? Coarse, because the question file has no gold routes. |
| Refusal correctness | Did each G question get the behaviour in `expected_behavior` (refuse, or say "not available")? Also "over-refusal": answerable questions that were declined. |
| Unsupported claims | Numbers in answers with no evidence: not a tool figure, not in any passage the model was given. |
| Verifier rejections | How often the verifier threw the model's text away (verifier on), or would have (verifier off). |
| Advice language | Answers containing a banned word (buy, sell, hold, undervalued ...). Mostly a baseline check. |

Everything is "k of n", never a percentage: with about 20 questions per split, one question
moves a percentage by 5 points, so decimals would suggest precision that is not there.

## How to read the results

Open `report.md` in the run folder.

1. **Header table:** git SHA and model (what produced it), the hash of the question file (which
   gold it was scored against), `facts_unverified` and `gold_pending_author_check`. While those
   last two are not "0 of ...", the numbers are plumbing results, not results to quote.
2. **Headline table:** one column per system. Read across a row: the full system vs the baseline
   is the main comparison; full vs full_no_verifier shows what the verifier changes.
3. **Per-category tables:** where each system wins or fails (e.g. the baseline should do well
   on E, qualitative, and badly on C and D, which need calculation).
4. **Known expected failures:** B questions asking for INR million or lakh crore. No tool
   converts units and the model may not do arithmetic, so the system cannot get these right
   yet. They are counted as failures, on purpose, rather than left out.
5. **Failures lists:** the question ids to look at. Each `<system>.jsonl` line has the full
   answer, its claims, citations, verifier report and score, so you can see why.

`run.json` records the timestamp, git SHA, model, split, file hashes and the exact command.

## The test split runs once

The test split is the honest number, so the harness makes it hard to use carelessly:
`--test` is needed, then you must type `RUN TEST SPLIT`; it always runs all three systems
together; results go to `eval/results/test/`; a second run is refused unless `--force` (and the
phrase again). Dev runs are unlimited. Nothing should be tuned after looking at test results.

## Decisions worth knowing (all in `config/eval.yaml`, all changeable)

- A claim's period: the period named in its sentence; if the sentence names none, any period
  named in the answer. A number with no period anywhere does not match a period-specific gold.
- A unit must be written: "INR 267,021" (no "crore") does not match a crore gold value.
- "Not available" questions (G04-G06) also accept a refusal or a partial answer that says
  what is missing, because "declined without guessing" is the point. Strict refusal questions
  accept only a refusal.
- The verifier-off arm keeps the refusal pre-check and the advice-word guard: those are not
  the verifier, so switching them off would mix two effects.
- Template answers (code-written, used when the verifier rejects) are scored like any answer.
  Their quoted passages are not counted as qualitative claims.
- `eval/results/` is gitignored: it holds annual-report excerpts and results computed on
  unverified facts. Decide at M9 what to publish.

## What this milestone did not do

No unit-conversion tool, no prompt or code changes after seeing scores, no test-split run
(that is the author's to start; see PROGRESS.md for why).
