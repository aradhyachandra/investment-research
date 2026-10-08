# D1: new facts for the author to verify

40 new facts (20 metrics x FY26 and FY25) in `data/manual/financials_tcs.csv`, all read by Claude
from `data/raw/tcs_annual_report_FY26.pdf` (consolidated, Ind AS) on 2026-10-08. Each row has
`entered_by = Claude` and blank `verified_by` / `verified_on`. The 12 rows you signed off on
2026-10-07 are unchanged.

**How to use this sheet (about 20 minutes).** Open the PDF at the page in each section heading and
go down the table, which follows the page from top to bottom. Each table row is two facts (FY26
and FY25 columns). Values are shown with the PDF's own digit grouping (1,82,372 = 182,372 in the
CSV). When a row matches, fill `verified_by` and `verified_on` for both of its CSV rows; the loader
checks that both are filled and that the verifier is not `Claude`.

**What was already checked by code or by me (not a substitute for your check).**
- Loader cross-foots, both years: profit before tax = profit before exceptional items and tax minus
  the three exceptional items; profit for the year (your signed-off figure) = profit before tax
  minus tax expense. A typo in any of those six figures would block the load.
- Totals I re-added by hand from the statement: total assets; total expenses; non-current
  liabilities (this is what settles the split "9 453" lease figure); the notes listed in the last
  column.
- Three figures appear only once in the report and have no independent cross-check: purchase of
  property, plant and equipment, purchase of intangible assets, and net cash from operating
  activities (only its own subtotal checks it). Look at these three with extra care.

**Sign conventions to confirm.**
- Exceptional items are stored as positive charges (they reduce profit). FY25 prints "-" for all
  three lines; I stored 0. If you would rather leave FY25 out, delete those three rows.
- The two capex lines are printed in brackets (outflows) and stored as positive amounts. The loader
  rejects a negative value for them.

### Consolidated Balance Sheet — PDF 166 (printed 196), "As at 31 March 2026 / 2025"

| # | Metric | Line on the page | FY26 | FY25 | Unit | PDF page (printed) | Cross-check done |
|---|---|---|---|---|---|---|---|
| 1 | `non_current_investments` | Non-current assets > Financial assets > Investments (note 8(a)) | 218 | 275 | INR crore | 166 (196) | Note 8(a), PDF 181: 132 + 86 = 218; FY25 8 + 186 + 81 = 275 |
| 2 | `current_investments` | Current assets > Financial assets > Investments (note 8(a)) | 33,770 | 30,689 | INR crore | 166 (196) | Note 8(a), PDF 181: six lines add to 33,770; FY25 30,689 |
| 3 | `other_balances_with_banks` | Current assets > Financial assets > Other balances with banks (note 8(d)) | 6,491 | 7,121 | INR crore | 166 (196) | Note 8(d), PDF 185: 609 + 5,882 = 6,491; FY25 906 + 6,215 = 7,121 |
| 4 | `total_assets` | TOTAL ASSETS | 1,82,372 | 1,59,629 | INR crore | 166 (196) | = total non-current 46,667 + total current 1,35,705; = TOTAL EQUITY AND LIABILITIES (1,08,478 + 12,980 + 60,914). FY25: 36,618 + 1,23,011 = 1,59,629 |
| 5 | `non_controlling_interests` | Equity > Non-controlling interests | 1,238 | 1,015 | INR crore | 166 (196) | Statement of changes in equity, PDF 169-170: 1,238 and 1,015 |
| 6 | `lease_liabilities_non_current` | Non-current liabilities > Financial liabilities > Lease liabilities | 9,453 | 7,838 | INR crore | 166 (196) | PDF text layer reads " 9 453" (split digits). Non-current liabilities add to 12,980 only with 9,453. Note 9, PDF 200: total 11,283 = 9,453 + 1,830 |
| 7 | `lease_liabilities_current` | Current liabilities > Financial liabilities > Lease liabilities | 1,830 | 1,554 | INR crore | 166 (196) | Note 9, PDF 200: total 11,283 (FY25 9,392 = 7,838 + 1,554) |

### Consolidated Statement of Profit and Loss — PDF 167 (printed 197)

| # | Metric | Line on the page | FY26 | FY25 | Unit | PDF page (printed) | Cross-check done |
|---|---|---|---|---|---|---|---|
| 8 | `other_income` | Other income (note 13) | 4,402 | 3,962 | INR crore | 167 (197) | Note 13, PDF 211: lines add to 4,402 / 3,962; segment note PDF 225 |
| 9 | `finance_costs` | Expenses > Finance costs (note 16) | 1,227 | 796 | INR crore | 167 (197) | Note 16, PDF 220: 778 + 9 + 440 = 1,227; FY25 796. Cash flow PDF 172 add-back |
| 10 | `depreciation_amortisation` | Expenses > Depreciation and amortisation expense | 5,560 | 5,242 | INR crore | 167 (197) | Cash flow PDF 172 and segment note PDF 225: 5,560 / 5,242 |
| 11 | `profit_before_exceptional_items_and_tax` | PROFIT BEFORE EXCEPTIONAL ITEMS AND TAX | 70,013 | 65,331 | INR crore | 167 (197) | = TOTAL INCOME 2,71,423 - TOTAL EXPENSES 2,01,410 (FY25 2,59,286 - 1,93,955) |
| 12 | `exceptional_restructuring_expenses` | Exceptional items > Re-structuring expenses (note 25) | 1,388 | 0 | INR crore | 167 (197) | FY25 printed "-" (stored 0). Segment note footnote PDF 225: 1,388 |
| 13 | `exceptional_labour_codes_impact` | Exceptional items > Statutory impact of new Labour Codes (note 26) | 2,128 | 0 | INR crore | 167 (197) | FY25 printed "-" (stored 0). Segment note footnote PDF 225: 2,128 |
| 14 | `exceptional_legal_claim_provision` | Exceptional items > Provision towards legal claim (note 20) | 1,010 | 0 | INR crore | 167 (197) | FY25 printed "-" (stored 0). Segment note PDF 225 and cash flow add-back PDF 172: 1,010 |
| 15 | `profit_before_tax` | PROFIT BEFORE TAX | 65,487 | 65,331 | INR crore | 167 (197) | Loader cross-foot: 70,013 - 1,388 - 2,128 - 1,010 = 65,487. Tax note PDF 221 and segment note PDF 225 |
| 16 | `tax_expense` | TOTAL TAX EXPENSE (current 16,388 + deferred (355)) | 16,033 | 16,534 | INR crore | 167 (197) | Loader cross-foot: 65,487 - 16,033 = 49,454 (profit for the year). Tax note PDF 221; cash flow add-back PDF 172 |

### Consolidated Statement of Cash Flows — PDF 172 (printed 202)

| # | Metric | Line on the page | FY26 | FY25 | Unit | PDF page (printed) | Cross-check done |
|---|---|---|---|---|---|---|---|
| 17 | `cash_from_operations` | Net cash flows generated from operating activities | 52,094 | 48,908 | INR crore | 172 (202) | = cash generated from operations 66,478 - taxes paid 14,384 (FY25 64,494 - 15,586). Printed once only |
| 18 | `purchase_of_ppe` | Investing > Payment for purchase of property, plant and equipment (printed in brackets) | 3,670 | 2,917 | INR crore | 172 (202) | Stored positive. Printed once only |
| 19 | `purchase_of_intangibles` | Investing > Payment for purchase of intangible assets (printed in brackets) | 367 | 944 | INR crore | 172 (202) | Stored positive. Printed once only |

### Note 8(m) Equity instruments — PDF 196 (printed 226)

| # | Metric | Line on the page | FY26 | FY25 | Unit | PDF page (printed) | Cross-check done |
|---|---|---|---|---|---|---|---|
| 20 | `shares_outstanding` | Reconciliation of number of shares > Equity shares > Closing balance | 361,80,87,518 (as printed) | 361,80,87,518 | shares (stored in crore) | 196 (226) | Stored as 3,618,087,518 shares (= 361.81 crore). Same count under "Issued, Subscribed and Fully paid up" (PDF 196) and as weighted average on PDF 167 |

## Asked for but not stored (and why)

| Item | Why it is not a fact |
|---|---|
| Exceptional items (total) | The statement prints the three lines but no total; 4,526 appears nowhere in the report. Storing it would be storing a sum. The three lines are stored instead; code can add them. |
| Dividend per share declared for the year | The financial statements and notes do not state a per-year total. Note 27 (PDF 238, printed 268) gives the parts: FY26 interim incl. special INR 79.00 paid + final INR 31.00 proposed; FY25 interim incl. special INR 96.00 + final INR 30.00. A total (110.00 / 126.00) is printed only in the ten-year summary (PDF 70, outside the financial statements, basis not stated there). Skipped as instructed; your call whether to add it from PDF 70. |
| Share capital (INR crore) | You asked for share capital or share count; I chose the share count (`shares_outstanding`), which keeps full precision. Share capital is INR 362 crore both years (PDF 196). |

## Nothing left out for low confidence

Every requested line was read; the only text-layer problems were split digits (" 9 453", "1, 82, 37 2")
and the H glyph for the rupee sign, and each affected figure was settled by a total or a note.
