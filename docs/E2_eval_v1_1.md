# E2: preparing the v1.1 evaluation

## Why

v1 (`eval/questions.jsonl`) was written when the database held two years and ten facts. Since
then D1-D4 added four years and many metrics and ratios, so the author drafted a second question
file, `eval/questions_v1_1.jsonl` (45 questions, pending sign-off). E2 makes the harness able to
run it **without touching v1**: v1 results, and v1's one test-split run, stay exactly where and
what they were.

## What changed

**1. `run_eval.py --questions FILE`** (default `eval/questions.jsonl`, so v1 behaves as before).

- Each question file has its own results folder. v1 keeps `eval/results/dev` and
  `eval/results/test`. Any other file gets `eval/results/<label>/dev` and `.../test`, where the label
  is the file name without `questions_` (`questions_v1_1.jsonl` -> `v1_1`). The rule is in code
  (`erp.eval.questions.question_set`), and the labels are listed in `config/eval.yaml`
  (`question_sets`).
- The one-time test-split gate is checked inside that folder, so it applies **per question file**.
  v1's test run does not block v1.1's, and a second v1.1 test run is refused like v1's.
- `run.json` records `question_set`, `questions_path` and `questions_sha256`. The report title and
  header show them too.
- `--rescore` uses the question file recorded in the run, not the default.

**2. Category H (history/trend: one question, several numbers across years).**

- The question loader accepts `H`; any other unknown letter is still refused.
- Numeric accuracy only counts questions with a `gold_value`. Both H questions have none (their gold
  is a sentence with three numbers), so they are **not scored on numeric accuracy**. The per-category
  table shows "n/a" for that column, not "0 of 0". They are still scored on behaviour (answered
  or not), on citations (their numeric claims vs the gold pages), on unsupported claims and on routing.
- Routing for H (`config/eval.yaml` `routing.trend`): "right tools" = at least one fact or ratio
  lookup, nothing but fact/ratio/search. "Right period" = those lookups cover two or more periods.
- Questions that count toward numeric accuracy in v1.1: dev 16 of 22 (not: V11-B03, H01, E03, G01,
  G03, G05); test 17 of 23 (not: V11-B02, H02, E04, G02, G04, G06; ids only, test questions not read).

**3. Results table side by side.** `scripts/make_results_table.py --sets v1 v1_1` prints, per
split, each set's provenance (labelled `**v1**`, `**v1_1**`) and one table whose columns are
labelled `v1: Full system`, ..., `v1_1: Full system`, .... A note says the sets are different
questions and not comparable with each other. A run whose `run.json` names another question
file is never shown under a set; the table says how many were skipped. Without `--sets` the output
is exactly as before (v1 only), so `--readme` does not change the README.

**4. Router fix for "profit for the year, including non-controlling interests" (PDEV-07).**

The small model kept routing this to `profit_attributable_to_owners` + `non_controlling_interests`
(the pieces, not the line asked for). The fix is in **code**; the router prompt is unchanged.

- Each metric has "own names": its display name without a bracketed qualifier
  ("Investments (current)" -> "investments"), and the opening phrase of its definition (the quoted
  line name it starts with, or the text up to the first colon). Names of one word are dropped as
  too loose. `profit_after_tax`'s definition opens with "profit for the year, including
  non-controlling interests", which is exactly the question's wording.
- `metrics_named_in(question)`: the names that appear in the question as whole words, after
  blanking period mentions ("in FY26"), so the name still reads as one phrase when a year sits in
  the middle. A name inside a longer matched name does not count ("non-controlling interests"
  inside the longer profit phrase).
- The rule only fires when **all** of these hold: the question names exactly one metric; the
  model's question type is `numeric`; every call is a fact lookup; none uses the named metric.
  Then code replaces those lookups with the named metric (one per period, same basis) and writes
  why in `RoutePlan.problems`. Otherwise the model's choice stands (two metrics named, a ratio, a
  search, a "mixed"/"why" question, or the right metric already chosen).
- Live, qwen2.5:3b: the model still answers owners + NCI. Code now replaces that, so routing on the
  20 provisional dev questions is **20 of 20** (was 19 of 20). The R2 year probes are unchanged
  (5/5/5/5; recall@5 9, recall@10 11, latest share 53 of 60). The rule touches fact lookups only,
  never search.

## Results of the v1.1 dev run

Run `eval/results/v1_1/dev/20261010-192232_8f34b9b5`: qwen2.5:3b, 22 dev questions, systems `full`
and `naive_rag` only (left out the verifier-off arm to keep the run under 10 minutes; it took 7). Made
from **uncommitted code** (`8f34b9b-dirty`): the committed code cannot load the v1.1 file. All 22
gold answers are still pending author sign-off, so these are plumbing numbers, not results to quote.

| Category (questions) | Numeric correct, full / naive | Behaviour correct, full / naive |
|---|---|---|
| A facts (5) | 5 of 5 / 1 of 5 | 5 of 5 / 2 of 5 |
| B period/unit (2) | 0 of 1 / 0 of 1 | 2 of 2 / 1 of 2 |
| C ratios (6) | 5 of 6 / 1 of 6 | 6 of 6 / 5 of 6 |
| D DCF (2) | 2 of 2 / 0 of 2 | 2 of 2 / 2 of 2 |
| E qualitative (2) | 0 of 1 / 0 of 1 | 1 of 2 / 2 of 2 |
| F mixed (1) | 0 of 1 / 0 of 1 | 1 of 1 / 1 of 1 |
| G guardrails (3) | n/a | 2 of 3 / 0 of 3 |
| H trend (1) | n/a (no gold value) | 1 of 1 / 1 of 1 |
| **All** | **12 of 16 / 2 of 16** | **20 of 22 / 14 of 22** |

Also: unsupported numeric claims 0 of 32 (full) vs 4 of 16 (naive). Numeric claims citing a gold
page 22 of 26 vs 0 of 12. Routing (full) 17 of 20 tools, 16 of 20 tools and period. The verifier
rejected 3 of 20. Advice words 0 vs 1 (naive RAG on V11-G01).

V11-A09 (the PDEV-07 pattern) is now correct: INR 46,099 crore, via the named-metric rule.

**Dev failures, full system** (diagnosed only; nothing was tuned on them):

- **V11-B01** INR million: expected failure (no conversion tool). It answered in crore, correctly.
- **V11-C05** effective tax rate FY24: the router fetched tax expense + profit after tax instead of
  `compute_ratio(effective_tax_rate)`; the model then worked out "34.3%" itself. The verifier caught
  it, and the template shipped the two facts with no rate. Routing miss.
- **V11-C11** 3-year CAGR: the answer is right (5.80%), but the router asked for the CAGR for FY23,
  FY24, FY25 and FY26. So "right tools and period" fails (gold period FY26). Routing-period miss only.
- **V11-E01** FY24 exceptional item: the search was filtered to FY24 (R2) and the composer answered
  "Not available". A fact (`exceptional_legal_claim_settlement`, 958) exists, but the router chose a search.
- **V11-F01** why FY24 PBT < PBT before exceptional items: routed to `net_profit_growth_yoy` (FY24 and
  FY23, FY23 has no prior year). The verifier rejected the text; the template shipped growth figures.
  Wrong route; the named-metric rule does not apply (ratio plan, by design).
- **V11-G03** industry comparison: answered with TCS's own operating margin instead of refusing.
  Known guardrail-phrasing miss (the question's note says so).
- **V11-H01** (behaviour OK, not numerically scored): routed to revenue growth for FY24 and FY26
  only, so FY25 (5.99%) is missing. The verifier rejected the composed text ("decrease 6.85%" wrong
  direction), and the template listed the figures. Note: the H "period right" rule passes with two
  periods, although "from FY24 to FY26" needs three. See NOTES (TO VERIFY).

**Naive RAG**: answered 1 of 5 facts correctly, declined 5 answerable questions as not available,
refused no G question (gave a verdict-word answer to "overvalued"), and answered FY22 revenue (G05).

## What this did not do

- No test-split run (v1 or v1.1), and no test-split questions were read to guide changes.
- No edits to `eval/questions.jsonl`, `eval/questions_v1_1.jsonl`, `data/`, or the DCF.
- No unit-conversion tool, so B questions in INR million stay expected failures.
- The Streamlit Evaluation tab still shows v1 only (it reads `eval/results/dev` and `test`).
