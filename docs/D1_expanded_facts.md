# D1: more TCS facts from the annual report

## What I built

**More reported figures.** The database had 12 facts (six metrics, FY25 and FY26). It now has 52.
The 40 new ones are 20 more lines from the FY26 annual report's consolidated statements, for both
years the report prints:

- Profit and loss: other income, finance costs, depreciation and amortisation, profit before
  exceptional items and tax, the three exceptional items, profit before tax, tax expense.
- Balance sheet: total assets, current and non-current investments, other balances with banks,
  current and non-current lease liabilities, non-controlling interests.
- Share capital note: number of equity shares outstanding at year end.
- Cash flow: net cash from operating activities, cash paid for property, plant and equipment, cash
  paid for intangible assets.

Each metric has an exact definition in `config/metrics.yaml` (what the line includes and excludes),
and each row says which PDF page and printed page it came from. The new rows are marked as entered
by Claude and not yet verified; the author checks them with `docs/D1_facts_for_review.md`.

The data now lives in `data/manual/financials_tcs.csv`, the place the plan names. The build command
points there. The old `data/sample/facts_sample.csv` and the test fixture are untouched, so the
existing tests still test exactly what they tested before.

**Six new ratios** in `config/ratios.yaml`: operating (EBIT) margin, effective tax rate, return on
equity, capex to revenue, operating cash flow to profit, and D&A to revenue. All are computed by
code from stored facts; nothing calculated is stored as a fact.

**New checks when loading.**
- *Cross-foot identities*: the loader adds up the parts and compares them with the printed total.
  Profit before tax must equal profit before exceptional items minus the exceptional items, and
  profit for the year must equal profit before tax minus tax. A typo in any of those figures stops
  the load. The identities are listed in the company config, not in code.
- *Sign of cash outflows*: the cash flow statement prints payments in brackets. We store them as
  positive amounts, and the loader rejects a negative one, so the sign cannot be mixed up.
- *Plausibility bands* for every new metric, as before.

## Why it was built this way

**Why store the three exceptional items and not their total?** The report prints three lines
(re-structuring, Labour Codes, legal claim) but never their total. Storing 4,526 would mean storing
a number we added up ourselves, which breaks the rule that the facts table only holds what the
report prints. Code can always add the three.

**Why can some ratios not be a plain "A divided by B"?** Two needed something new:
- EBIT is not printed. It is profit before exceptional items and tax, minus other income, plus
  finance costs. So a ratio's top line can now be a *sum* of metrics with plus or minus signs.
  Capex (equipment plus intangibles) uses the same thing.
- Return on equity divides by *average* equity (this year end and last year end), because profit
  is earned over the year while equity is a snapshot. So a ratio's bottom line can now be an
  average. FY25 return on equity cannot be computed: it needs FY24 equity, which we do not have.
  The tool says so instead of guessing.

The computed EBIT, capex and average equity are shown next to the ratio, so an answer can quote
"EBIT of INR 66,838 crore" and the verifier can still check that number against the tool.

**Why EBIT excludes other income.** TCS earns a lot of interest on its treasury investments. That
is not operating profit, and the DCF counts those investments separately, so leaving it in would
count it twice (plan Section 5.1).

**Why the share count instead of share capital.** Share capital is printed as INR 362 crore, a
rounded figure. The share count (3,61,80,87,518 shares) is exact and is what per-share figures need.

**Why the router needed no change.** The router builds its menu of metrics and ratios from the
database and config each time. The new items appeared on their own. In a live check with the local
model, 10 new phrasings all went to the intended metric or ratio, including "TCS's tax expense in
FY26", which used to be answered with profit after tax because no tax metric existed.

## What is still missing

- Dividend per share: the statements give the parts (interim, special, final) but not a total for
  the year; only the ten-year summary page prints one. Not stored.
- Balance sheet check (assets = equity + liabilities) and cash roll-forward check: need liability
  and cash-movement metrics we have not keyed.
- The rest of the plan's metric list (borrowings, dividends paid, buybacks, headcount, quarters,
  FY21 onwards).
