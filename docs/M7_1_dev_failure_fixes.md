# M7.1: fixing three dev-split failures (and one that stayed broken)

Plain-language note for the author. What was wrong, what changed, and why. No new milestone:
this is a bug-fix pass on what the M7 dev run showed.

## The rule for this session: don't overfit

The eval questions are a measuring stick. If I tune code until those exact sentences pass, the
score goes up but the system doesn't get better. So:

- I never used eval wording to design a fix. Every regression test uses new phrasings and new
  numbers (`tests/test_dev_failure_fixes.py`).
- For the router, I wrote two lists of new questions: a **dev list** I iterated against, and a
  **held-out list** written *before* any change, run once at the end. (It found one more problem,
  so it was used once for a fix; say so if you quote it.)
- I never looked at or ran the test split.

## 1. The router refused questions it could answer

**Symptom.** "Is FY26 calendar 2026?" and "interest on lease liabilities in FY26" were refused
as "not in the data".

**Why.** Two causes, both structural:

1. *No tool for period questions.* The router can only choose tools. A question about what "FY25"
   means had no tool to go to, so "refuse" was the only legal move.
2. *"Not a metric" was read as "not in the data".* Only 6 figures are in SQLite. The prompt said
   "a figure not in the allowed values → outside_data", so anything else (lease interest,
   depreciation, auditor fees) was refused. Worse: the model first commits to
   `get_financial_fact` and then *must* pick a metric from the list, so it picked a wrong one
   (lease interest → `cash_and_equivalents`), then gave up. A wrong-metric lookup is more
   dangerous than a refusal.

I confirmed these with my own phrasings before changing anything: all 4 period questions were
refused, and 3 of 4 non-metric figure questions were refused or swapped for another metric.

**Fixes** (code first, prompt second):

- **New tool `explain_period(period)`.** Pure code: the period resolver (`periods.py`) plus
  `fiscal_year_end_month` from `config/companies/tcs.yaml`. It returns the dates and says whether
  the label is a calendar year. Its evidence is `period:FY25` (kind `config`), so the answer cites
  where the dates come from. The composer can only copy these dates; the verifier rejects any
  other date.
- **A `not_listed` choice for metric_id.** This gives the model a way out at the exact point it
  got stuck. Code turns it into a `search_documents` call that searches with the user's question.
- **Code overrides a refusal that contradicts the model's own choice.** If the model says
  `not_listed` (a reported figure) and then refuses for "investment advice", "price prediction" or
  "outside data", that refusal is incoherent, so code searches the filings instead. A refusal for
  "other company" still stands. Advice questions are still caught first by the pattern pre-check.
- **`outside_data` is decided by code for lookups.** Periods named in the question are added to
  the allowed values. If every fact/ratio lookup is for a period with no data (FY19, FY21), code
  refuses. So "revenue in FY19" is still refused, and that no longer depends on the model.
- **Future periods.** The pre-check refused any question naming a period after the latest data,
  including "does Q2 FY27 fall in calendar 2026?". Now such a question is still refused *unless*
  the router sends it only to `explain_period`. Asking for a figure (any metric, any period) is
  still refused as a forecast.
- **Prompt.** The tool is described, the refusal rule is reworded, and there is one worked example
  ("Which dates does FY26 run between?"). Any example wording that touches the eval was avoided.

**Side effect, and how I handled it.** The prompt change cost two of the 20 provisional routing
questions. The model fetched a margin's inputs instead of the ratio, and it dropped the earlier
year of a two-year comparison. The second is the same failure M5 saw before the examples happened
to fix it. Rather than keep re-balancing a fragile prompt, I:
- dropped a second example I had added (an employee-training example; not needed), and
- made code enforce the existing rule "a change between two years needs one call per year": if
  the question names two periods with data and the model fetched only one, code adds the other.

Result: provisional routing is back to 20 of 20 (PDEV-06's expected route gained `explain_period`,
because it literally asks "which dates does FY25 cover"). The tricky guardrail phrasings are
unchanged at 12 of 13.

**Still open.** In the held-out list, "What was TCS's tax expense in FY26?" was routed to
`profit_after_tax`. That is the substitution risk in its plainest form. The composer happened to
say "not available", but nothing in code stops a substituted metric. One possible guard: check that
the chosen metric's name or alias appears in the question. Not built.

## 2. The verifier rejected a true sentence

**Symptom.** "Net profit growth of 1.35% in FY26, which is lower than the 8.8% growth…" was
rejected as "says a decrease".

**Why.** The verifier has a rule: when a sentence has a direction word ("fell", "lower") and a
growth rate, the growth rate's sign must agree ("fell 4%" needs a negative growth). Here "lower"
was not about a change at all. It compared two written figures (1.35 < 8.8, true). The rule
didn't know that "lower **than** <figure>" is an ordering. The opposite mistake was also
possible: "4.58% … *higher* than the 10%" (false) passed, because "higher" happened to agree with
the positive sign.

**Fix.** A new rule runs first. When "higher/lower than" has a figure on each side, it compares
the two figures as written: the order must match, and they must be the same kind of figure (% vs
%, not % vs crore). Other direction words in the sentence ("fell", "grew") are still checked
against the sign. Re-running the saved EV-F01 text through the new verifier: it passes in all
four saved runs. All existing injected-bad-claim tests still pass.

**Limit.** The verifier checks that the order is right, not that comparing the two figures makes
sense (e.g. a growth rate against a passage figure about something else). That is a judgement
about meaning, not arithmetic.

## 3. Retrieval of a sentence buried in a table chunk: tried, reverted

**Idea.** The "no single customer is 10% or more of revenue" sentence (PDF 226) sits after a
geographic-assets table in one chunk. The chunk is flagged table-heavy and down-weighted. I split
runs of table-cell lines from the prose around them at ingest, so prose gets its own chunk.

**Measured** on scratch indexes (the real `data/chroma/` was not touched), same code with the
switch off and on, 12 provisional probes:

| | recall@5 | recall@10 |
|---|---|---|
| before (switch off) | 9 of 12 | 11 of 12 |
| after (switch on) | 9 of 12 | 11 of 12 |

The customer probe still missed the top 10, and one other probe moved from rank 7 to 9. **Reverted**,
as agreed.

**What I learned.** The split worked as designed: the table left the chunk and the flag cleared.
But the sentence still shares its chunk with US/UK revenue footnotes, capital commitments and tax
disputes. The real cause is one level up. Note sub-headings like "Information about major
customers" are printed in body-size bold, so the section detector doesn't see them, and unrelated
notes end up in the same chunk. The next thing to try is sub-heading detection (bold at body size,
short line). That is a bigger chunking change, so I didn't start it.

## What the dev run says afterwards (one run, `eval/results/dev/20261004-155610_6788b014`)

- **EV-B03** is answered from the period config ("1 April 2025 to 31 March 2026 … does not
  correspond to the calendar year 2026"). Fixed.
- **EV-F01** is answered by the LLM; the verifier no longer rejects it. Fixed.
- **EV-E04** is no longer refused: it reaches search. But searching with the question did not
  retrieve the lease note (PDF 200), so the answer is "not available". This is now a retrieval gap,
  not a routing bug. Still scored as a failure.
- **EV-E03** now passes, **but not because of a fix.** The router wrote a different search query
  this time and found the same sentence in the standalone notes (PDF 293, not the consolidated
  PDF 226). Treat it as luck from a changed prompt, not as progress on retrieval.

## 4. Left alone

EV-G05 ("not directly computable") and the other M7 failures (dividends, C05's extra call) are
unchanged, as asked.
