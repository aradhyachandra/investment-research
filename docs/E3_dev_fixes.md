# E3: fixing the v1.1 dev failures

## Why

The first v1.1 dev run (E2, `docs/E2_eval_v1_1.md`) had seven full-system failures. Five were
routing problems that come from a general pattern, not from one question, so they can be fixed
in code without tuning on the dev wording. E3 adds three router rules (code, not the prompt) and
tightens one scoring rule. Two failures stay as known limitations.

As in E2, **code decides, the model does not**: each rule only replaces or adds tool calls, writes
why in `RoutePlan.problems`, and leaves the model's plan alone whenever it is not sure. The router
prompt is unchanged. All rules live in `src/erp/agent/router.py`.

## What changed

**1. Named ratio (dev pattern V11-C05: "effective tax rate" -> two input facts).**
E2's named-metric rule, extended to ratios.

- A ratio's own names: its display name without a bracketed part ("Operating margin (EBIT margin)"
  -> "operating margin"), and the opening phrase of its definition **unless that phrase contains a
  metric's own name**. Ratio definitions open with the formula's input ("Total tax expense ...",
  "Profit attributable to shareholders of the Company ..."), and naming an input line must not
  switch a plan to the ratio. In practice, today, only display names count (all eleven openings
  name an input). `ratio_names()`.
- Metric and ratio names are now found together (`names_in()`), so a metric name inside a longer
  ratio name does not count separately.
- The rule fires only when **all** hold: the question names exactly one thing, and it is a ratio
  (no metric named as well); the model says `numeric` or `ratio`; every call is a fact or ratio
  lookup; none computes the named ratio. Then the plan becomes `compute_ratio` for that ratio, one
  call per period of the plan, keeping each period's basis.
- The E2 metric rule now also requires that no ratio is named (before, a question naming a metric
  and a ratio could have its plan replaced by the metric alone).

**2. Ratios that span years (dev pattern V11-C11: a 3-year CAGR asked for FY23, FY24, FY25, FY26).**

- `Catalog.ratio_spans` comes from `config/ratios.yaml`: `yoy_growth` spans 1 year, `cagr` its
  `years`. Quotient ratios do not span years and are never touched.
- For a numeric/ratio question, a spanning ratio is called **once**, for:
  - the only period the question names, or
  - when it names exactly two fiscal years that are the ratio's own span apart and the span is two
    or more years, the later one ("CAGR from FY23 to FY26" -> FY26).
- Left alone, on purpose: a range longer than the span (a trend: one value per year is the point,
  e.g. "growth from FY24 to FY26"); two adjacent years with a one-year growth ratio ("growth in
  FY25 and FY26" may ask for two growth rates); "why"/mixed questions.

**3. Groups of metrics (dev pattern V11-E01: "what was the exceptional item in FY24?" -> search only).**

General cause: the exceptional items are stored as several separate lines
(`exceptional_restructuring_expenses`, `..._labour_codes_impact`, `..._legal_claim_provision`,
`..._legal_claim_settlement`). A question about "the exceptional item(s)" names the family, not a
line, so the model saw no matching metric and searched.

- Groups come from display names of the form "<group> - <line>" in `config/metrics.yaml`
  ("Exceptional items - re-structuring expenses"), singular/plural ignored, two or more members.
  Today there is one group, "exceptional item". `metric_groups()`.
- The question asks about a group when the group name appears as whole words, **not** inside a
  metric's own name ("profit before exceptional items and tax"), **not** after a qualifier word
  (before, after, excluding, including, ex, net of: "profit before exceptional items"), and no
  single member is named (that is the named-metric rule's job).
- Then, for each period the question names that has data, code adds a fact lookup for each member
  stored for that period: the lines that are not zero, or, if every line is zero (FY23, FY25), the
  zero lines, so the answer can say so from the facts. `Catalog.fact_periods` (consolidated facts)
  tells the router which exist. The model's calls are kept (a search can explain the item); if the
  plan is then over `max_tool_calls` (4), the model's other lookups are dropped first, then its
  searches.
- No period named -> nothing is added (code does not pick a year).

**4. H routing: every year of the range (dev pattern V11-H01).**
`src/erp/eval/score.py` (`fiscal_years_in_range`) and `config/eval.yaml` `routing.trend`: a trend
question's "period right" now needs its fact/ratio calls to cover **every fiscal year from the
first to the last one the question names** ("from FY24 to FY26" -> FY24, FY25, FY26). A question
naming fewer than two fiscal years keeps the old rule (two or more periods).

**5. Known limitations, not changed.**

- **V11-B01** (FY24 revenue in INR million): no unit-conversion tool; the system answers in crore.
  Expected failure, listed in every report (`config/eval.yaml` `expected_failures`).
- **V11-G03** (operating margin vs the industry average): neither the pattern pre-check nor the
  router refuses an "industry average" comparison; it answers with TCS's own margin. The same miss
  is in the v1 guardrail phrasings (12 of 13).

## Tests

`tests/test_e3_dev_fixes.py`, 39 tests written before the code (the H-scoring tests were seen failing
before the scoring change; the router tests were first run after the router code), all with
new phrasings that are in neither question file (checked by exact text): the rule fires on the
failure pattern, keeps the basis and periods, and leaves alone every case listed above.

## Results

**Live checks (qwen2.5:3b):** provisional dev routing **20 of 20** (unchanged); R2 year probes
unchanged (5/5/5/5; recall@5 9, recall@10 11, latest share 53 of 60); v1 guardrail phrasings 12 of
13 (unchanged, the same "industry average" miss).

**v1.1 dev run** `eval/results/v1_1/dev/20261010-195652_3339daff` (full + naive RAG, uncommitted E3
code on top of 3339daf), compared with E2's `20261010-192232_8f34b9b5`:

| Metric (full system) | E2 (before) | E3 (after) |
|---|---|---|
| Numeric accuracy | 12 of 16 | **13 of 16** |
| Behaviour correct | 20 of 22 | **21 of 22** |
| Routing: right tools | 17 of 20 | 17 of 20 |
| Routing: right tools and period | 16 of 20 | 16 of 20 |
| Unsupported numeric claims | 0 of 32 | 0 of 31 |
| Verifier rejections (template shipped) | 3 of 20 | 2 of 20 |

Naive RAG unchanged: numeric 2 of 16, behaviour 14 of 22.

Per question:

- **V11-C05 fixed.** Model still picks tax expense + PAT; code computes `effective_tax_rate` FY24 ->
  25.64%.
- **V11-C11 fixed (routing).** One call, `revenue_cagr_3y` FY26 -> 5.80%.
- **V11-E01 fixed (answer).** Code added `exceptional_legal_claim_settlement` FY24; the answer is "a
  settlement of a legal claim, INR 958 crore". **But it now fails "routing: right tools"**: the E rule
  in `config/eval.yaml` expects exactly `{search_documents}`, and the plan is search + a fact.
- **V11-H01 now fails "routing period"**, as intended by the stricter rule: the model still asks for
  FY24 and FY26 only; FY25 is missing. Nothing in the router fills the middle years of a range.
- **V11-F01 still wrong.** It names no ratio (it names "profit before tax" and "profit before
  exceptional items"), so the named-ratio rule cannot apply, and "exceptional items" there follows
  "before", so the group rule does not fire either. The model routed `net_profit_growth_yoy` again,
  and the span rule (the model called it a `ratio` question) cut FY23, so the plan is now growth for
  FY24 only. Still the wrong figure; the template shipped it.
- **V11-D01 newly wrong, not caused by E3.** Same route (`run_dcf` base) and the same value
  (INR 1,880.53), but the composer this time wrote "a value per share of INR 1,880.53." without a
  unit after the number, so the scorer's unit check failed (E2's text had "INR 1,880.53 per share").
  E3 changes only the router; the DCF tool output is identical. Composer wording varies run to run
  even at temperature 0 (TO VERIFY why).
- **V11-B01, V11-G03**: unchanged known limitations.
