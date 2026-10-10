# D3: facts for review (FY25 and FY24 annual reports)

100 new rows in `data/manual/financials_tcs.csv`, all `entered_by = Claude`, `verified_by` and
`verified_on` blank. This sheet lists them in the order you will meet them in the PDFs: by
document, then by page, then top to bottom. Values are written as the report prints them (Indian
digit grouping, ₹ crore unless stated; EPS in ₹; share counts as printed in note 8(m)).

**Time:** about 30-40 minutes. Eight pages, two PDFs. Each page holds two year columns, so each
page is one sitting.

**How to check a row:** open the PDF at the PDF page (the printed page is in brackets), find the
line, check the figure **and the column** (the left column is the report's own year, the right
column is the year before). Then fill `verified_by` and `verified_on` for that row in the CSV.
Rows are in the CSV in the same order as here (after the 54 signed-off FY26-report rows).

**What the machine already checked** (so your job is mainly "right line, right column, right
page"):
- Every FY25 figure in the FY25 report equals the FY26 report's FY25 comparative, which you
  already signed off. Every FY24 figure in the FY24 report equals the FY25 report's FY24
  comparative. **0 disagreements, so 0 restatements** (column "Cross-check").
- Profit before tax = profit before exceptional item and tax - settlement of legal claim; profit
  for the year = profit before tax - total tax expense; total equity = equity attributable to
  shareholders + non-controlling interests. All hold for FY25, FY24 and FY23, in both reports.
- Every value is inside its plausibility band (no band was widened). Cash outflows are stored as
  positive amounts.
- Both PDFs match the sha256 in `sources_hashes.txt`.

**What nothing checks:** FY23 has no second source (there is no FY23 report loaded), so the 25
FY23 rows rest on your check alone. They are marked "only source" below.

## Decisions to look at first (5 minutes)

1. **New metric `exceptional_legal_claim_settlement`.** The FY25 and FY24 reports print one
   exceptional line, "Settlement of legal claim" (note 20): ₹958 crore in FY24, "-" in FY25 and
   FY23. The FY26 report prints three different lines ("Re-structuring expenses", "Statutory
   impact of new Labour Codes", "Provision towards legal claim"). The FY24 charge is the Epic
   Systems case (FY24 report PDF p.231, the balance of punitive damages); the FY26 legal claim is
   the CSC case. Different claim, different wording, so I made it its own metric rather than a
   year of `exceptional_legal_claim_provision`. Agree?
2. **No rows invented for missing lines.** The FY26 report's three exceptional lines do not exist
   in the FY25 or FY24 report, so they have no FY24/FY23 rows (and no FY25 row from the FY25
   report). Zeros are stored only where the statement prints "-": settlement FY25 (FY25 report)
   and FY23 (FY24 report).
3. **Primary source for FY25 moves.** FY25 lookups now return the FY25 report (PDF p.180/181/184/
   202) and list the FY26 report's comparative as a cross-check. Until you sign off these rows,
   FY25 answers, ratios and the snapshot show "not yet checked by a human" even though the same
   figure was signed off in the FY26 report. See the session summary for the eval effect.
4. **Line names that changed** (same metric, wording only): "Net cash flows generated from
   operating activities" (FY25 report) vs "Net cash generated from operating activities" (FY24
   report); FY24 report prints "Purchase of investments" as (141,011) with international grouping.
   Neither changes a stored figure.
5. **Printed page numbers.** Both reports print the page number in the page **header** (top
   corner), not the footer. FY25 report: PDF 4-332 print 2-330 (PDF minus 2); FY24 report: PDF
   3-336 print 3-336. Checked on every page by the ingest: FY24 334 of 334 exact; FY25 301 of 329
   exact, 28 unreadable (digits drawn as other glyphs, e.g. "1Ϭ3"), 0 contradictions.

## The 100 rows

### AR FY25, PDF p.180 (printed p.178): consolidated Balance Sheet

| # | Line as printed | Year | Value as printed | Cross-check | ✓ |
|---|---|---|---|---|---|
| 1 | TOTAL ASSETS | FY25 (primary) | 1,59,629 | agrees with AR FY26 p.166 (signed off) | [ ] |
| 2 | TOTAL ASSETS | FY24 (cross-check) | 1,46,449 | agrees with AR FY24 p.180 | [ ] |
| 3 | Non-current assets > Financial assets > Investments | FY25 (primary) | 275 | agrees with AR FY26 p.166 (signed off) | [ ] |
| 4 | Non-current assets > Financial assets > Investments | FY24 (cross-check) | 281 | agrees with AR FY24 p.180 | [ ] |
| 5 | Current assets > Financial assets > Investments | FY25 (primary) | 30,689 | agrees with AR FY26 p.166 (signed off) | [ ] |
| 6 | Current assets > Financial assets > Investments | FY24 (cross-check) | 31,481 | agrees with AR FY24 p.180 | [ ] |
| 7 | Cash and cash equivalents | FY25 (primary) | 8,342 | agrees with AR FY26 p.166 (signed off) | [ ] |
| 8 | Cash and cash equivalents | FY24 (cross-check) | 9,016 | agrees with AR FY24 p.180 | [ ] |
| 9 | Other balances with banks | FY25 (primary) | 7,121 | agrees with AR FY26 p.166 (signed off) | [ ] |
| 10 | Other balances with banks | FY24 (cross-check) | 4,270 | agrees with AR FY24 p.180 | [ ] |
| 11 | Equity attributable to shareholders of the Company | FY25 (primary) | 94,756 | agrees with AR FY26 p.166 (signed off) | [ ] |
| 12 | Equity attributable to shareholders of the Company | FY24 (cross-check) | 90,489 | agrees with AR FY24 p.180 | [ ] |
| 13 | Non-controlling interests (equity) | FY25 (primary) | 1,015 | agrees with AR FY26 p.166 (signed off) | [ ] |
| 14 | Non-controlling interests (equity) | FY24 (cross-check) | 830 | agrees with AR FY24 p.180 | [ ] |
| 15 | Total equity | FY25 (primary) | 95,771 | agrees with AR FY26 p.166 (signed off) | [ ] |
| 16 | Total equity | FY24 (cross-check) | 91,319 | agrees with AR FY24 p.180 | [ ] |
| 17 | Non-current liabilities > Lease liabilities | FY25 (primary) | 7,838 | agrees with AR FY26 p.166 (signed off) | [ ] |
| 18 | Non-current liabilities > Lease liabilities | FY24 (cross-check) | 6,516 | agrees with AR FY24 p.180 | [ ] |
| 19 | Current liabilities > Lease liabilities | FY25 (primary) | 1,554 | agrees with AR FY26 p.166 (signed off) | [ ] |
| 20 | Current liabilities > Lease liabilities | FY24 (cross-check) | 1,505 | agrees with AR FY24 p.180 | [ ] |

### AR FY25, PDF p.181 (printed p.179): consolidated Statement of Profit and Loss

| # | Line as printed | Year | Value as printed | Cross-check | ✓ |
|---|---|---|---|---|---|
| 21 | Revenue from operations | FY25 (primary) | 2,55,324 | agrees with AR FY26 p.167 (signed off) | [ ] |
| 22 | Revenue from operations | FY24 (cross-check) | 2,40,893 | agrees with AR FY24 p.181 | [ ] |
| 23 | Other income | FY25 (primary) | 3,962 | agrees with AR FY26 p.167 (signed off) | [ ] |
| 24 | Other income | FY24 (cross-check) | 4,422 | agrees with AR FY24 p.181 | [ ] |
| 25 | Finance costs | FY25 (primary) | 796 | agrees with AR FY26 p.167 (signed off) | [ ] |
| 26 | Finance costs | FY24 (cross-check) | 778 | agrees with AR FY24 p.181 | [ ] |
| 27 | Depreciation and amortisation expense | FY25 (primary) | 5,242 | agrees with AR FY26 p.167 (signed off) | [ ] |
| 28 | Depreciation and amortisation expense | FY24 (cross-check) | 4,985 | agrees with AR FY24 p.181 | [ ] |
| 29 | PROFIT BEFORE EXCEPTIONAL ITEM AND TAX | FY25 (primary) | 65,331 | agrees with AR FY26 p.167 (signed off) | [ ] |
| 30 | PROFIT BEFORE EXCEPTIONAL ITEM AND TAX | FY24 (cross-check) | 62,955 | agrees with AR FY24 p.181 | [ ] |
| 31 | Exceptional item: Settlement of legal claim | FY25 (primary) | - (stored 0) | none (line not printed in AR FY26) | [ ] |
| 32 | Exceptional item: Settlement of legal claim | FY24 (cross-check) | 958 | agrees with AR FY24 p.181 | [ ] |
| 33 | PROFIT BEFORE TAX | FY25 (primary) | 65,331 | agrees with AR FY26 p.167 (signed off) | [ ] |
| 34 | PROFIT BEFORE TAX | FY24 (cross-check) | 61,997 | agrees with AR FY24 p.181 | [ ] |
| 35 | TOTAL TAX EXPENSE | FY25 (primary) | 16,534 | agrees with AR FY26 p.167 (signed off) | [ ] |
| 36 | TOTAL TAX EXPENSE | FY24 (cross-check) | 15,898 | agrees with AR FY24 p.181 | [ ] |
| 37 | PROFIT FOR THE YEAR | FY25 (primary) | 48,797 | agrees with AR FY26 p.167 (signed off) | [ ] |
| 38 | PROFIT FOR THE YEAR | FY24 (cross-check) | 46,099 | agrees with AR FY24 p.181 | [ ] |
| 39 | Profit for the year attributable to: Shareholders of the Company | FY25 (primary) | 48,553 | agrees with AR FY26 p.167 (signed off) | [ ] |
| 40 | Profit for the year attributable to: Shareholders of the Company | FY24 (cross-check) | 45,908 | agrees with AR FY24 p.181 | [ ] |
| 41 | Earnings per equity share: Basic and diluted (₹) | FY25 (primary) | 134.19 | agrees with AR FY26 p.167 (signed off) | [ ] |
| 42 | Earnings per equity share: Basic and diluted (₹) | FY24 (cross-check) | 125.88 | agrees with AR FY24 p.181 | [ ] |

### AR FY25, PDF p.184 (printed p.182): consolidated Statement of Cash Flows

| # | Line as printed | Year | Value as printed | Cross-check | ✓ |
|---|---|---|---|---|---|
| 43 | Net cash (flows) generated from operating activities | FY25 (primary) | 48,908 | agrees with AR FY26 p.172 (signed off) | [ ] |
| 44 | Net cash (flows) generated from operating activities | FY24 (cross-check) | 44,338 | agrees with AR FY24 p.184 | [ ] |
| 45 | Payment for purchase of property, plant and equipment (in brackets) | FY25 (primary) | 2,917 | agrees with AR FY26 p.172 (signed off) | [ ] |
| 46 | Payment for purchase of property, plant and equipment (in brackets) | FY24 (cross-check) | 2,202 | agrees with AR FY24 p.184 | [ ] |
| 47 | Payment for purchase of intangible assets (in brackets) | FY25 (primary) | 944 | agrees with AR FY26 p.172 (signed off) | [ ] |
| 48 | Payment for purchase of intangible assets (in brackets) | FY24 (cross-check) | 442 | agrees with AR FY24 p.184 | [ ] |

### AR FY25, PDF p.202 (printed p.200): consolidated Note 8(m)

| # | Line as printed | Year | Value as printed | Cross-check | ✓ |
|---|---|---|---|---|---|
| 49 | Note 8(m) Reconciliation of number of shares: Closing balance | FY25 (primary) | 361,80,87,518 | agrees with AR FY26 p.196 (signed off) | [ ] |
| 50 | Note 8(m) Reconciliation of number of shares: Closing balance | FY24 (cross-check) | 361,80,87,518 | agrees with AR FY24 p.203 | [ ] |

### AR FY24, PDF p.180 (printed p.180): consolidated Balance Sheet

| # | Line as printed | Year | Value as printed | Cross-check | ✓ |
|---|---|---|---|---|---|
| 51 | TOTAL ASSETS | FY24 (primary) | 1,46,449 | agrees with AR FY25 p.180 | [ ] |
| 52 | TOTAL ASSETS | FY23 (only source) | 1,43,651 | none (FY23: no FY23 report loaded) | [ ] |
| 53 | Non-current assets > Financial assets > Investments | FY24 (primary) | 281 | agrees with AR FY25 p.180 | [ ] |
| 54 | Non-current assets > Financial assets > Investments | FY23 (only source) | 266 | none (FY23: no FY23 report loaded) | [ ] |
| 55 | Current assets > Financial assets > Investments | FY24 (primary) | 31,481 | agrees with AR FY25 p.180 | [ ] |
| 56 | Current assets > Financial assets > Investments | FY23 (only source) | 36,897 | none (FY23: no FY23 report loaded) | [ ] |
| 57 | Cash and cash equivalents | FY24 (primary) | 9,016 | agrees with AR FY25 p.180 | [ ] |
| 58 | Cash and cash equivalents | FY23 (only source) | 7,123 | none (FY23: no FY23 report loaded) | [ ] |
| 59 | Other balances with banks | FY24 (primary) | 4,270 | agrees with AR FY25 p.180 | [ ] |
| 60 | Other balances with banks | FY23 (only source) | 3,909 | none (FY23: no FY23 report loaded) | [ ] |
| 61 | Equity attributable to shareholders of the Company | FY24 (primary) | 90,489 | agrees with AR FY25 p.180 | [ ] |
| 62 | Equity attributable to shareholders of the Company | FY23 (only source) | 90,424 | none (FY23: no FY23 report loaded) | [ ] |
| 63 | Non-controlling interests (equity) | FY24 (primary) | 830 | agrees with AR FY25 p.180 | [ ] |
| 64 | Non-controlling interests (equity) | FY23 (only source) | 782 | none (FY23: no FY23 report loaded) | [ ] |
| 65 | Total equity | FY24 (primary) | 91,319 | agrees with AR FY25 p.180 | [ ] |
| 66 | Total equity | FY23 (only source) | 91,206 | none (FY23: no FY23 report loaded) | [ ] |
| 67 | Non-current liabilities > Lease liabilities | FY24 (primary) | 6,516 | agrees with AR FY25 p.180 | [ ] |
| 68 | Non-current liabilities > Lease liabilities | FY23 (only source) | 6,203 | none (FY23: no FY23 report loaded) | [ ] |
| 69 | Current liabilities > Lease liabilities | FY24 (primary) | 1,505 | agrees with AR FY25 p.180 | [ ] |
| 70 | Current liabilities > Lease liabilities | FY23 (only source) | 1,485 | none (FY23: no FY23 report loaded) | [ ] |

### AR FY24, PDF p.181 (printed p.181): consolidated Statement of Profit and Loss

| # | Line as printed | Year | Value as printed | Cross-check | ✓ |
|---|---|---|---|---|---|
| 71 | Revenue from operations | FY24 (primary) | 2,40,893 | agrees with AR FY25 p.181 | [ ] |
| 72 | Revenue from operations | FY23 (only source) | 2,25,458 | none (FY23: no FY23 report loaded) | [ ] |
| 73 | Other income | FY24 (primary) | 4,422 | agrees with AR FY25 p.181 | [ ] |
| 74 | Other income | FY23 (only source) | 3,449 | none (FY23: no FY23 report loaded) | [ ] |
| 75 | Finance costs | FY24 (primary) | 778 | agrees with AR FY25 p.181 | [ ] |
| 76 | Finance costs | FY23 (only source) | 779 | none (FY23: no FY23 report loaded) | [ ] |
| 77 | Depreciation and amortisation expense | FY24 (primary) | 4,985 | agrees with AR FY25 p.181 | [ ] |
| 78 | Depreciation and amortisation expense | FY23 (only source) | 5,022 | none (FY23: no FY23 report loaded) | [ ] |
| 79 | PROFIT BEFORE EXCEPTIONAL ITEM AND TAX | FY24 (primary) | 62,955 | agrees with AR FY25 p.181 | [ ] |
| 80 | PROFIT BEFORE EXCEPTIONAL ITEM AND TAX | FY23 (only source) | 56,907 | none (FY23: no FY23 report loaded) | [ ] |
| 81 | Exceptional item: Settlement of legal claim | FY24 (primary) | 958 | agrees with AR FY25 p.181 | [ ] |
| 82 | Exceptional item: Settlement of legal claim | FY23 (only source) | - (stored 0) | none (FY23: no FY23 report loaded) | [ ] |
| 83 | PROFIT BEFORE TAX | FY24 (primary) | 61,997 | agrees with AR FY25 p.181 | [ ] |
| 84 | PROFIT BEFORE TAX | FY23 (only source) | 56,907 | none (FY23: no FY23 report loaded) | [ ] |
| 85 | TOTAL TAX EXPENSE | FY24 (primary) | 15,898 | agrees with AR FY25 p.181 | [ ] |
| 86 | TOTAL TAX EXPENSE | FY23 (only source) | 14,604 | none (FY23: no FY23 report loaded) | [ ] |
| 87 | PROFIT FOR THE YEAR | FY24 (primary) | 46,099 | agrees with AR FY25 p.181 | [ ] |
| 88 | PROFIT FOR THE YEAR | FY23 (only source) | 42,303 | none (FY23: no FY23 report loaded) | [ ] |
| 89 | Profit for the year attributable to: Shareholders of the Company | FY24 (primary) | 45,908 | agrees with AR FY25 p.181 | [ ] |
| 90 | Profit for the year attributable to: Shareholders of the Company | FY23 (only source) | 42,147 | none (FY23: no FY23 report loaded) | [ ] |
| 91 | Earnings per equity share: Basic and diluted (₹) | FY24 (primary) | 125.88 | agrees with AR FY25 p.181 | [ ] |
| 92 | Earnings per equity share: Basic and diluted (₹) | FY23 (only source) | 115.19 | none (FY23: no FY23 report loaded) | [ ] |

### AR FY24, PDF p.184 (printed p.184): consolidated Statement of Cash Flows

| # | Line as printed | Year | Value as printed | Cross-check | ✓ |
|---|---|---|---|---|---|
| 93 | Net cash (flows) generated from operating activities | FY24 (primary) | 44,338 | agrees with AR FY25 p.184 | [ ] |
| 94 | Net cash (flows) generated from operating activities | FY23 (only source) | 41,965 | none (FY23: no FY23 report loaded) | [ ] |
| 95 | Payment for purchase of property, plant and equipment (in brackets) | FY24 (primary) | 2,202 | agrees with AR FY25 p.184 | [ ] |
| 96 | Payment for purchase of property, plant and equipment (in brackets) | FY23 (only source) | 2,532 | none (FY23: no FY23 report loaded) | [ ] |
| 97 | Payment for purchase of intangible assets (in brackets) | FY24 (primary) | 442 | agrees with AR FY25 p.184 | [ ] |
| 98 | Payment for purchase of intangible assets (in brackets) | FY23 (only source) | 355 | none (FY23: no FY23 report loaded) | [ ] |

### AR FY24, PDF p.203 (printed p.203): consolidated Note 8(m)

| # | Line as printed | Year | Value as printed | Cross-check | ✓ |
|---|---|---|---|---|---|
| 99 | Note 8(m) Reconciliation of number of shares: Closing balance | FY24 (primary) | 361,80,87,518 | agrees with AR FY25 p.202 | [ ] |
| 100 | Note 8(m) Reconciliation of number of shares: Closing balance | FY23 (only source) | 365,90,51,373 | none (FY23: no FY23 report loaded) | [ ] |

## After you sign off

Rebuild the database so lookups pick up the sign-off:

```
PYTHONPATH=src .venv/bin/python -m erp.db.load_facts --csv data/manual/financials_tcs.csv --entry-method llm_extracted --replace --raw-dir data/raw
```

Then `PYTHONPATH=src:tests .venv/bin/pytest -q tests/test_d3_history.py`: three tests pin "not
verified" for these rows (`test_new_rows_are_claude_entries_not_yet_verified_with_both_pages`,
`test_whole_csv_loads_with_all_checks`, and the `verified is False` checks in the ratio and
snapshot tests) and will need their expectations updated, as was done after the D1 sign-off.
