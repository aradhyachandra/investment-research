# M1 — The facts database and its loader (plain-language note)

## What it is
A SQLite database that holds TCS's reported numbers, and a loader that moves numbers from a CSV
into it. Every later part of the project (ratios, DCF, the agent) reads numbers from here, so the
goal of M1 is simple: **a wrong number should be very hard to get in.**

## How a row travels
1. **You type a row in the CSV**: metric, period label (`FY26`), basis, the number as printed,
   the unit as printed, the PDF file, and the page.
2. **Config fills in what the CSV doesn't say.**
   - `config/metrics.yaml` says what each metric means and its *canonical unit*
     (e.g. revenue is always stored in ₹ crore).
   - `config/companies/tcs.yaml` lists the periods with real start/end dates
     (FY26 = 1 Apr 2025 – 31 Mar 2026), the source PDFs, and a sensible range for each metric.
   - `sources_hashes.txt` gives each PDF's fingerprint (sha256), so a citation points to one exact file.
3. **Code derives the stored value.** If you typed ₹ million, it multiplies by 0.1 to get ₹ crore,
   and stores both the number as printed and the factor used, so anyone can audit the conversion.
4. **Validation runs on every row** before anything is written. A row is rejected if: the metric,
   period, company or PDF is unknown; the unit can't convert to the canonical unit; the page is
   missing; the basis isn't consolidated/standalone; the row is a duplicate; or the value is
   outside the metric's plausible range.
5. **All or nothing.** If even one row fails, nothing is saved and every problem is listed with its
   CSV line number.

## Why these choices
- **Plausibility bands** catch the classic slip: typing a crore figure but labelling it million
  (10x off), or an extra "000" (1000x off). The value is technically a number, so only a range check
  can catch it.
- **Real dates, not labels**: "FY25" is easy to misread as calendar 2025. Storing actual dates means
  nothing downstream has to guess.
- **Two page numbers**: the PDF's page index (167) and the number printed on the page (197) differ.
  Storing both lets a reader find the page either way.
- **Config, not code**: adding Infosys later should mean new config and data, not code changes.
- **entry_method and verified_by**: the sample rows were typed by Claude, so they are stored as
  `llm_extracted` with `verified_by` empty. That flag stays visible until you check them yourself.

## What it does not do yet
Balance-sheet, cash-flow, quarterly-sum and two-source checks need data we don't have yet
(listed in NOTES.md). Period-label parsing and fact lookups are M2.
