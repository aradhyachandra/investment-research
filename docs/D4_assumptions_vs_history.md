# D4: the DCF's assumptions next to TCS's own record

## What I built

Every DCF run now carries a small table: each **operating assumption** (revenue growth, EBIT margin,
tax rate, D&A, capex, working capital) beside **the same measure computed from TCS's filings for
FY23 to FY26**. Code does the arithmetic from facts in the database; the language model never sees
or computes these numbers.

The point is not to say an assumption is right or wrong. It is to make one thing visible: **is this
assumption in line with what TCS has actually done, or a deliberate departure from it?** A departure
can be perfectly reasonable (a forecast is allowed to differ from the past), but it should be a
choice someone can defend, not an accident.

### Same definition as the DCF, or it does not count

A comparison is only fair if both sides measure the same thing. So each history line uses the DCF's
own definition, written in `config/dcf.yaml`:

| Assumption | History, computed per year |
|---|---|
| Revenue growth | change in revenue from operations; also the FY23-FY26 compound growth (5.80% a year) |
| EBIT margin | (profit before exceptional items and tax - other income + finance costs - **interest on lease liabilities**) / revenue |
| Tax rate | tax expense / profit before tax (effective rate). **Only an approximate match**, see below |
| D&A | (D&A - **depreciation on right-of-use assets**) / revenue |
| Capex | (purchase of PP&E + purchase of intangibles) / revenue |
| Working capital | (operating profit before working capital changes - cash generated from operations) / increase in revenue |

The two bold items are why new facts were needed. The DCF treats leases as an ordinary operating
cost (D2), so its EBIT keeps lease interest as a cost and its D&A leaves out right-of-use
depreciation. Both figures sit in the lease note of each annual report; I added them for FY23-FY26.
For working capital, the cash flow statement prints two subtotals whose difference is exactly the
cash absorbed by working capital, so I stored those two instead of nine separate lines. 24 new facts
in all, waiting for your check (`docs/D4_facts_for_review.md`).

A good sign the definitions match: for FY26, the code gets the same figures the assumptions file
worked out by hand in its rationales (EBIT 66,060 = 24.7%, D&A 1.38%, capex 1.51%, working capital
about 19%). A test pins this.

**Tax is the exception.** The DCF applies a rate to EBIT and the file calls the base rate the Indian
statutory rate (25.17%). What the filings give us is the effective rate on profit before tax, which
includes prior-year adjustments and deferred tax. Close, but not the same thing, so the row is
labelled "approximate match".

### The check

For each assumption and each scenario: **pass** if every value (every forecast year, for growth) lies
within the FY23-FY26 minimum and maximum, otherwise **warn**. The tolerance around that range is in
`config/dcf.yaml`; it is 0 for now, a placeholder marked TO VERIFY. Four years is a short record.

These checks never stop a run and never change a value. They are kept apart from the engine's own
sanity checks (terminal growth below WACC and so on), so "all checks passed" still means what it
meant before. The three values per share are unchanged to the last digit (a test pins them).

## What the checks show (FY23-FY26)

| | FY23 | FY24 | FY25 | FY26 | Central (base) | Low growth (bear) | High growth (bull) |
|---|---|---|---|---|---|---|---|
| Revenue growth | n/a | 6.85% | 5.99% | 4.58% | 6-7%: **warn** | 3-4%: **warn** | 8-10%: **warn** |
| EBIT margin | 23.84% | 24.41% | 24.10% | 24.74% | 24.70%: pass | 23.50%: **warn** | 25.50%: **warn** |
| Tax rate (effective) | 25.66% | 25.64% | 25.31% | 24.48% | 25.17%: pass | 27.00%: **warn** | 25.17%: pass |
| D&A excl. right-of-use | 1.50% | 1.36% | 1.34% | 1.38% | 1.38%: pass | same | same |
| Capex | 1.28% | 1.10% | 1.51% | 1.51% | 1.51%: pass | same | same |
| Working capital / extra revenue | n/a | 44.59% | 23.28% | 18.89% | 19%: pass | same | same |

FY23 growth and working capital need FY22 revenue, which is not in the database, so they are n/a.

**Inside history.** D&A, capex and working capital sit inside the four-year range in every scenario,
and the central EBIT margin and tax rate do too. For margin, capex and working capital the central
case uses the FY26 level, which is at one end of the range in each case: the highest margin of the
four years, the highest capex share (level with FY25), and the lowest working-capital need per
rupee of extra revenue. The tax rate sits inside the effective-rate range, with the caveat above.

**Departures from history.**
- **Revenue growth, all three scenarios.** The central case's 7% in years 2 and 3 is just above the
  best year in the record (6.85%, FY24). The low-growth case (3-4%) is below the slowest year (4.58%,
  FY26) throughout, and the high-growth case (8-10%) is above the fastest year throughout. The
  record itself falls each year, from 6.85% to 4.58%.
- **EBIT margin, low and high growth.** 23.5% is below the lowest year (23.84%, FY23); 25.5% is above
  the highest (24.74%, FY26).
- **Tax rate, low growth.** 27% is above any effective rate in the record (highest 25.66%, FY23).

These are statements about distance from the past, not about which scenario is more likely. The
low- and high-growth scenarios are meant to sit outside the central path; the checks simply make the
size of each departure visible so its rationale can be read against it.

## Where you see it

- **DCF tab:** a new "Assumptions vs history" table (assumption, value per scenario, FY23-FY26,
  range, status), with an expander for how each row is computed, each scenario's check detail, and
  page chips for every filing page used.
- **The `dcf_run` record:** `outputs_json["history"]` stores the table, the checks, and every fact id
  and page used.
- **The run_dcf tool:** the history is in the tool's detail. Each warning adds a short note
  ("the assumption sits outside TCS's own record for FY23-FY26") with no figures in it, so the
  answer writer has nothing to quote that the verifier could not trace.

## What it does not do

- It does not judge an assumption, and it changes none. All values in `dcf_inputs.yaml` are as they were.
- It does not compare the WACC inputs or terminal growth; they have no "TCS history" in the filings.
- Four years, one company: a narrow base for "normal". The tolerance rule is a placeholder.
