# M2: Periods, fact lookup and ratios (plain-language note)

## What it is
Three small pieces that sit on top of the M1 database:
1. **A period resolver** that turns a label like `FY26` into real dates, and back again.
2. **`get_financial_fact`**, which fetches one stored number together with its proof.
3. **`compute_ratio`**, which calculates a ratio from stored numbers and records how it did it.

None of them use an LLM. Later (M5) the LLM will *call* these functions; it will never do
their work itself.

## 1. Periods: why a resolver at all
"FY25" is easy to misread as calendar 2025. For TCS it means 1 April 2024 to 31 March 2025.
The resolver does this in one tested place:
- `FY26` → 1 Apr 2025 to 31 Mar 2026
- `Q2 FY27` → 1 Jul 2026 to 30 Sep 2026 (Q1 = Apr–Jun, Q2 = Jul–Sep, Q3 = Oct–Dec, Q4 = Jan–Mar)
- the year before `Q2 FY27` is `Q2 FY26` (used for year-on-year growth)

The month a fiscal year ends in (March for TCS) comes from the company config, not the code.
Only two spellings are accepted (`FY26` and `Q2 FY27`). Anything else, like `fy26`, `FY2026`
or `CY25`, gives a clear error. Being strict here stops a mistyped label from quietly matching
the wrong year.

The dates of each period in `config/companies/tcs.yaml` are still typed out by hand. The loader
now checks them against the resolver, so a hand-typed date and the rule can't disagree.

## 2. `get_financial_fact`: a number never travels without its source
You ask for a metric, a period and a basis (consolidated by default). You get back:
- the value in its standard unit (e.g. ₹ crore) **and** exactly as printed (e.g. ₹ million),
- the fact's ID in the database,
- which document it came from, the PDF page and the page number printed on the paper,
- who entered it, how (by hand or read by an LLM), and whether a person has verified it.

If the number isn't there, it **raises an error**. It never falls back to a nearby year,
the other basis or an estimate. If two documents both give the same figure, it also refuses,
because we haven't yet decided which source should win.

## 3. `compute_ratio`: code calculates, and keeps the receipt
The four ratios are PAT margin and year-on-year growth in revenue, PAT and EPS. **Which numbers
go into each ratio is written in `config/ratios.yaml`**, not in the code. The code knows two
kinds of sum: "A divided by B" and "this year compared with the same period last year".

Every result is saved as a row in `computed_metric` with:
- the formula with the real periods filled in, e.g.
  `profit_after_tax[FY26] / revenue_from_operations[FY26] * 100`
- the IDs of the facts it used, so anyone can trace the result back to the PDF pages,
- the git commit of the code that produced it.

**Verified follows the inputs.** A ratio is marked verified only if every number it used has
been verified by a person. Today all sample numbers were entered by Claude and are unverified,
so every ratio says `verified = False`. That's correct behaviour, not a bug.

Growth on a zero or negative base (e.g. growth from a loss) gives an error instead of a
misleading percentage.

## The verified columns
The facts CSV can now have two extra columns, `verified_by` and `verified_on`. Leave them blank
and the row stays unverified. Fill them in after you've checked the number against the PDF
yourself. Both must be filled together, and the verifier can't be the same person who entered
the row.

## How the tests prove it
The expected ratio values in `tests/test_ratios.py` are numbers worked out by hand (with the
arithmetic in the comments and a `bc` cross-check), not numbers taken from the code. If the
code and the hand calculation disagree, the test fails.
