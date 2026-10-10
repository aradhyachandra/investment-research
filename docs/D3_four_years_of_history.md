# D3: four years of history (FY23 to FY26)

## What I built

**Two more annual reports.** The FY25 report (Integrated Annual Report 2024-25) and the FY24 report
(2023-24) are registered in `config/companies/tcs.yaml` with their period, accounting standard
(Ind AS) and printed page numbers, and their sha256 is in `sources_hashes.txt`. They are added at the
end of the list on purpose: the database numbers its documents in config order, and the existing
search index and the eval's gold sources refer to document 1 (the FY26 report) and 2 (the fact
sheet). Those numbers did not move; the new reports are documents 3 and 4. FY23 and FY24 are new
periods with their real dates.

**100 new facts.** The same metrics as before, for FY25 and FY24 from the FY25 report, and FY24
and FY23 from the FY24 report. Every row says which PDF page and printed page it came from, was
entered by Claude, and waits for the author's check (`docs/D3_facts_for_review.md`). The database
now holds 154 facts, FY23 to FY26.

**One new metric, because a line changed name.** The FY24 and FY25 reports print one exceptional
line, "Settlement of legal claim" (₹958 crore in FY24, the Epic Systems case). The FY26 report
prints three other lines, one of them "Provision towards legal claim" for a different case. They
are not the same thing, so the FY24 line is its own metric, `exceptional_legal_claim_settlement`.
The three FY26 lines simply have no rows for the earlier years: the report does not print them,
and storing a zero would be inventing a figure. A zero is stored only where the statement prints a
dash. A matching cross-foot check (profit before tax = profit before the exceptional item minus the
settlement) runs on the older reports' figures.

**A 3-year revenue CAGR.** A new ratio kind, `cagr`, in the ratio engine: (revenue at the end ÷
revenue three years earlier) to the power one third, minus one. It is configured as
`revenue_cagr_3y` in `config/ratios.yaml`. For FY26 it is 5.80% (FY23 ₹2,25,458 crore to FY26
₹2,67,021 crore); the test value was worked out by hand with `bc`. FY25 cannot be computed yet: it
would need FY22.

**Ratios over time.** Every ratio now computes for FY24, FY25 and FY26. For FY23, the ratios that
use one year compute (margins, tax rate, capex, cash conversion, D&A); growth rates and return on
equity refuse, because they need FY22, which we do not have. They say so instead of guessing.

**Search over three reports.** Both new PDFs are in the search index (926 and 966 chunks). Each
search result carries its document's year, so an answer can say which report a passage came from.

**A small trend on the Company snapshot.** Each card now shows a little line for FY23 to FY26 with
the four values written underneath, and names the years whose figures are not yet checked by a
human. The values come from the same tools as everything else. The line starts at zero, so a small
change does not look like a big one.

## Why it was built this way

**Which report wins when two print the same number?** The report *for* that year (the plan's
duplicate-fact rule). So FY25 now comes from the FY25 report, with the FY26 report's FY25 column
kept as a cross-check, and FY24 comes from the FY24 report with the FY25 report's FY24 column as a
cross-check. If the two had disagreed (a restatement), the loader would have stopped and shown both
figures; I would then have recorded the newer one as a restatement rather than overwriting the old
one. In this case every one of the 49 figures printed in two reports agreed, so there is nothing to restate.

**FY23 has only one source.** No FY23 report is loaded, so the FY23 figures come from the FY24
report's comparative column and nothing cross-checks them. The review sheet marks them "only source".

**Why the page-number check had to change.** The FY26 report prints page numbers at the bottom;
the FY25 and FY24 reports print them at the top. The ingest now reads both places. While doing that
I found that digits from the first line of body text could be glued onto the page number (a "5"
under "36" read as "536"), so digits are now only joined within one printed line. Result: on the
FY24 report all 334 numbered pages match the config; on the FY25 report 301 match and 28 are
unreadable (some digits are drawn as other symbols in that PDF's text layer), with no page
contradicting the config.

**Did more documents make search worse?** Measured, not tuned. On the 12 provisional probes,
recall@5 stayed 9 of 12 and recall@10 stayed 11 of 12. But the right FY26 page dropped in rank on 4
probes (one from 1st to 4th), and 32 of the 60 top-5 results now come from the older reports, which
repeat much of the same risk and strategy text. The probes only count the FY26 page as right, so an
older report's version of the same passage counts as a miss. Whether that is a problem depends on
the question: for "what are TCS's risks", an FY24 passage is out of date.

## What is still missing

- The author's check of the 100 new rows.
- FY22 and earlier (needed for FY23 growth and return on equity, and for a CAGR ending in FY25).
- Quarterly figures, dividends, borrowings, headcount (unchanged from D1).
- Search does not prefer the newest report; the agent does not filter by year. Not changed here.
