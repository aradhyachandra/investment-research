# Finance review sheet: TCS DCF (for Eshan)

**Reviewer:** ____________ **Date:** ____________ **Time needed:** about 45-60 minutes

## What this is

An AI equity-research assistant for TCS (Indian equities). Code does all the calculations and every
number cites its source page in the annual reports. The DCF's base-year figures come from 178 facts
(FY23-FY26) that Aradhya verified against the reports. The **judgement assumptions** below were
drafted with AI assistance and adopted by Aradhya. They have **not had a finance review**. That review
is what this sheet is for.

It is not investment advice. The output is "what these assumptions imply", with no target prices and
no comparison with the market price.

**How to look at it:** run `.venv/bin/streamlit run app/streamlit_app.py -- --demo` and open the DCF tab
(firm-level results, EV-to-equity waterfall, scenarios, sensitivity grid, "Assumptions vs history"
table). The assumptions file is `data/manual/dcf_inputs.yaml`.

**Current output (Central case):** enterprise value INR 6,37,758 crore, equity value
INR 6,80,392 crore, **INR 1,880.53 per share**, terminal value 69.96% of EV, WACC 12.92%.
Low growth INR 1,445.11; High growth INR 2,351.66.

For each item, tick one and write a reason if you change it.

---

## Part A: six methodology decisions

| # | Decision | Current choice and reason | Your view |
|---|---|---|---|
| A1 | **Leases** | Operating cost: right-of-use depreciation and lease interest stay inside EBIT; lease liabilities (INR 11,283 crore) are NOT deducted in the bridge. Doing both would double count. | ☐ Agree ☐ Treat as debt instead ☐ Other: |
| A2 | **Cash and treasury** | Other income excluded from cash flows; treasury added once in the bridge: cash + other bank balances + investments (46,896) minus earmarked balances (609) and TCS Foundation deposits (2,289) = 43,998. No borrowings. | ☐ Agree ☐ Change: |
| A3 | **Discount rate** | All-equity CAPM. Risk-free 5.34% = India 10Y G-sec 7.21% minus default spread 1.87% (Damodaran method, avoids double-counting country risk). ERP 7.08% (Damodaran total ERP for India). Beta 1.07. Cost of equity = WACC = 12.92%. | ☐ Agree ☐ Change: |
| A4 | **Horizon and terminal growth** | 5 explicit years; Gordon growth terminal value at 5% (below WACC and below the 5.34% risk-free rate). | ☐ Agree ☐ Change: |
| A5 | **Discounting timing** | Year-end discounting (mid-year would lift values by roughly 6%). | ☐ Agree ☐ Use mid-year |
| A6 | **Scenarios** | Central / Low growth / High growth, varying growth, margin, tax, beta and terminal growth (Part B). | ☐ Agree ☐ Change: |

## Part B: assumption values against TCS's own history

History is computed in code from the verified facts using the DCF's own definitions (shown in the app's
"Assumptions vs history" table, with page references).

| Assumption | FY23 | FY24 | FY25 | FY26 | Central | Low growth | High growth | Your view |
|---|---|---|---|---|---|---|---|---|
| Revenue growth | n/a | 6.85% | 5.99% | 4.58% | 6% every year | 3%, then 4% | 9%, 10%, 10%, 9%, 8% | ☐ OK ☐ Change: |
| EBIT margin (lease-adjusted) | 23.84% | 24.41% | 24.10% | 24.74% | 24.7% | 23.5% | 25.5% | ☐ OK ☐ Change: |
| Tax rate | eff. 25.66% | 25.64% | 25.31% | 24.48% | 25.17% statutory | 27% | 25.17% | ☐ OK ☐ Change: |
| D&A excl. right-of-use, % revenue | 1.50% | 1.36% | 1.34% | 1.38% | 1.38% | same | same | ☐ OK ☐ Change: |
| Capex, % revenue | 1.28% | 1.10% | 1.51% | 1.51% | 1.51% | same | same | ☐ OK ☐ Change: |
| Working capital, % of extra revenue | n/a | 44.59% | 23.28% | 18.89% | 19% | same | same | ☐ OK ☐ Change: |
| Beta | | | | | 1.07 | 1.13 | 1.00 | ☐ OK ☐ Change: |
| Terminal growth | | | | | 5.00% | 4.00% | 5.25% | ☐ OK ☐ Change: |

Revenue CAGR FY23-FY26: 5.80%. Central growth was lowered from 6/7/7/6.5/6% to a flat 6% on
2026-10-10 because the 7% years sat above every recent year.

## Part C: open questions (please give an answer for each)

1. **Market-input dates.** The G-sec yield is from 1 Oct 2026 but the default spread and ERP are from
   Damodaran's 5 Jan 2026 table. Use a newer Damodaran update if one exists? ____________
2. **Beta.** Two sources disagree: 1.07 (vs NIFTY 50, 4-year monthly) and 1.13 (3-year, benchmark
   unclear). Which, or compute one ourselves later from price data? ____________
3. **Debt-like items.** Income tax liabilities (INR 14,751 crore) are not deducted. Reverse repo (900) and
   inter-corporate deposits (1,500) are not added to cash. Right? ____________
4. **Working capital.** FY24's 44.6% is an outlier; is 19% (FY26 level) a fair steady state? ____________
5. **FY26 depreciation footnote.** The depreciation notes sum to INR 112 crore less than the P&L, close
   to the INR 113 crore of right-of-use depreciation the report says went to capital work-in-progress.
   If so, D&A excl. right-of-use is about 1.43% of revenue, not 1.38%. Adjust? ____________
6. **Terminal-value band.** The app warns if terminal value is outside 50-85% of EV (a placeholder, not a
   sourced rule). Keep, change, or drop? ____________
7. **Share count.** Year-end shares (361.8 crore) used as diluted shares; no dilutive securities in FY26.
   OK? ____________

## Part D: spot-check 10 evaluation answers

The project's evaluation has 41 questions with gold answers that Aradhya signed off. The plan asks a
finance reviewer to spot-check at least 10. Open `eval/questions.jsonl` and check these against the
annual report pages listed in each row's `gold_sources`:

EV-A01, EV-A05, EV-C01, EV-C03, EV-C05, EV-E02, EV-E07, EV-F01, EV-B01, EV-D01

For each: ☐ correct ☐ wrong (note): ____________

(EV-D01 is the DCF output under the assumptions at the time of the frozen v1 eval, INR 1,914.82; just
check it is reasonable as a definition, not that it equals today's value.)

---

## Sign-off

☐ I reviewed Parts A-D. Changes requested are written above.

Name: ____________ Date: ____________

After this review, Aradhya updates `dcf_inputs.yaml` with any changes (each with a rationale and
source), and the README's "no finance-partner review" note is replaced with what was reviewed.
