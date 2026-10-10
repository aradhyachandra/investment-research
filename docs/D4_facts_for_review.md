# D4: facts for review (lease note and cash-flow working-capital lines, FY23-FY26)

24 new rows at the end of `data/manual/financials_tcs.csv`, all `entered_by = Claude`, `verified_by`
and `verified_on` blank. Four new metrics, read from three annual reports. This sheet lists them in
the order you will meet them in the PDFs (by document, then page, then top to bottom), which is also
their order in the CSV. Values as printed, ₹ crore.

**Time:** about 15 minutes. Seven pages, three PDFs; each page holds two year columns.

**How to check a row:** open the PDF at the PDF page (printed page in brackets), find the line, check
the figure **and the column** (left = the report's own year, right = the year before). Then fill
`verified_by` and `verified_on` for that row in the CSV.

**What the machine already checked:**
- Every figure printed in two reports agrees (the loader stops on a disagreement): FY25 in the FY26
  and FY25 reports, FY24 in the FY25 and FY24 reports. **0 disagreements, 0 restatements.**
- The right-of-use depreciation totals equal the sum of their asset-class lines in every column
  (FY26 1,866; FY25 1,820; FY24 1,716; FY23 1,634), worked by hand.
- FY26 history reproduces the assumptions file's own FY26 hand figures: lease-adjusted EBIT 66,060
  (24.7%), D&A excluding right-of-use 3,694 (1.38%), working-capital outflow 2,210 (about 19%).
- Every value is inside its plausibility band. All three PDFs match `sources_hashes.txt`.

**What nothing checks:** the 8 FY23 rows (no FY23 report loaded); marked "only source".

## Decisions to look at first (5 minutes)

1. **Four new metrics** (`config/metrics.yaml`): `interest_on_lease_liabilities` and
   `depreciation_right_of_use_assets` (lease note, `statement: other`), and
   `operating_profit_before_wc_changes` and `cash_generated_from_operations` (cash flow statement
   subtotals). Working capital is stored as **two printed subtotals**, not the nine "Net change in"
   lines: their difference is exactly the working-capital movement, and each is a figure the report
   prints. Agree?
2. **Line name changed, same line:** "Cash flows generated from operations" (FY26 and FY25 reports)
   vs "Cash generated from operations" (FY24 report). One metric.
3. **FY26 right-of-use depreciation footnote.** The FY26 lease note marks the buildings line (1,709)
   with "#": ₹113 crore of directly attributable costs was transferred to capital work-in-progress.
   I stored the printed total (1,866). The DCF's D&A assumption (and D4's history) subtract 1,866
   from the P&L's 5,560. TO VERIFY whether only 1,753 reached the P&L. Related: in FY25 the notes tie
   exactly (PP&E depreciation 2,695 + amortisation 727 + right-of-use 1,820 = 5,242 on the P&L); in
   FY26 they do not (2,641 + 941 + 1,866 = 5,448 vs 5,560 on the P&L, a gap of 112). I have not
   resolved this; it does not change any stored figure.
4. **Lease interest is a sentence, not a table.** "Interest on lease liabilities is ₹X crore and ₹Y
   crore for the years ended ..." The first figure is the report's own year.

## The 24 rows

### AR FY26, PDF p.172 (printed p.202): consolidated Statement of Cash Flows

| # | Line as printed | Year | Value as printed | Cross-check | ✓ |
|---|---|---|---|---|---|
| 1 | Operating profit before working capital changes | FY26 (primary) | 68,688 | none (FY26: latest report) | [ ] |
| 2 | Operating profit before working capital changes | FY25 (cross-check) | 67,853 | agrees with AR FY25 p.184 | [ ] |
| 3 | Cash flows generated from operations | FY26 (primary) | 66,478 | none (FY26: latest report) | [ ] |
| 4 | Cash flows generated from operations | FY25 (cross-check) | 64,494 | agrees with AR FY25 p.184 | [ ] |

### AR FY26, PDF p.200 (printed p.230): lease note

| # | Line as printed | Year | Value as printed | Cross-check | ✓ |
|---|---|---|---|---|---|
| 5 | Depreciation on right-of-use assets: total | FY26 (primary) | 1,866 | sum of lines (incl. footnote #, see decision 3) | [ ] |
| 6 | Depreciation on right-of-use assets: total | FY25 (cross-check) | 1,820 | agrees with AR FY25 p.205 | [ ] |
| 7 | Interest on lease liabilities (sentence below "Changes in lease liabilities") | FY26 (primary) | 778 | equals the 778 in the DCF's ebit_margin rationale | [ ] |
| 8 | Interest on lease liabilities | FY25 (cross-check) | 631 | agrees with AR FY25 p.206 | [ ] |

### AR FY25, PDF p.184 (printed p.182): consolidated Statement of Cash Flows

| # | Line as printed | Year | Value as printed | Cross-check | ✓ |
|---|---|---|---|---|---|
| 9 | Operating profit before working capital changes | FY25 (primary) | 67,853 | agrees with AR FY26 p.172 | [ ] |
| 10 | Operating profit before working capital changes | FY24 (cross-check) | 63,709 | agrees with AR FY24 p.184 | [ ] |
| 11 | Cash flows generated from operations | FY25 (primary) | 64,494 | agrees with AR FY26 p.172 | [ ] |
| 12 | Cash flows generated from operations | FY24 (cross-check) | 56,827 | agrees with AR FY24 p.184 | [ ] |

### AR FY25, PDF p.205 (printed p.203): lease note, depreciation table

| # | Line as printed | Year | Value as printed | Cross-check | ✓ |
|---|---|---|---|---|---|
| 13 | Depreciation on right-of-use assets: total | FY25 (primary) | 1,820 | agrees with AR FY26 p.200 | [ ] |
| 14 | Depreciation on right-of-use assets: total | FY24 (cross-check) | 1,716 | agrees with AR FY24 p.206 | [ ] |

### AR FY25, PDF p.206 (printed p.204): lease note, interest sentence

| # | Line as printed | Year | Value as printed | Cross-check | ✓ |
|---|---|---|---|---|---|
| 15 | Interest on lease liabilities | FY25 (primary) | 631 | agrees with AR FY26 p.200 | [ ] |
| 16 | Interest on lease liabilities | FY24 (cross-check) | 518 | agrees with AR FY24 p.206 | [ ] |

### AR FY24, PDF p.184 (printed p.184): consolidated Statement of Cash Flows

| # | Line as printed | Year | Value as printed | Cross-check | ✓ |
|---|---|---|---|---|---|
| 17 | Operating profit before working capital changes | FY24 (primary) | 63,709 | agrees with AR FY25 p.184 | [ ] |
| 18 | Operating profit before working capital changes | FY23 (only source) | 59,148 | none (FY23: no FY23 report loaded) | [ ] |
| 19 | Cash generated from operations | FY24 (primary) | 56,827 | agrees with AR FY25 p.184 | [ ] |
| 20 | Cash generated from operations | FY23 (only source) | 54,931 | none (FY23: no FY23 report loaded) | [ ] |

### AR FY24, PDF p.206 (printed p.206): lease note

| # | Line as printed | Year | Value as printed | Cross-check | ✓ |
|---|---|---|---|---|---|
| 21 | Depreciation on right-of-use assets: total | FY24 (primary) | 1,716 | agrees with AR FY25 p.205 | [ ] |
| 22 | Depreciation on right-of-use assets: total | FY23 (only source) | 1,634 | sum of lines only | [ ] |
| 23 | Interest on lease liabilities | FY24 (primary) | 518 | agrees with AR FY25 p.206 | [ ] |
| 24 | Interest on lease liabilities | FY23 (only source) | 492 | none (FY23: no FY23 report loaded) | [ ] |

## After you sign off

Rebuild the database so lookups pick up the sign-off:

```
PYTHONPATH=src .venv/bin/python -m erp.db.load_facts --csv data/manual/financials_tcs.csv --entry-method llm_extracted --replace --raw-dir data/raw
```

Then `PYTHONPATH=src:tests .venv/bin/pytest -q tests/test_d4_history_checks.py`:
`test_d4_rows_are_claude_entries_not_yet_verified_with_both_pages` and
`test_unverified_history_facts_are_listed` pin "not verified" for these rows and will need updating,
as after the D1 and D3 sign-offs.

**Status:** all 24 facts reviewed and signed off by Aradhya Chandra on 2026-10-10.
