# M2.1: Net margin and the duplicate-fact policy (plain-language note)

## 1. Net margin instead of PAT margin
TCS's "profit for the year" includes a small slice that belongs to minority (non-controlling)
shareholders of its subsidiaries. **Net margin** uses only the profit that belongs to TCS's own
shareholders: *profit attributable to shareholders of the Company ÷ revenue from operations*.
Net profit growth uses the same profit line. The old PAT figure is still stored, with a clearer
definition, but no ratio uses it now.

All ratios are **statutory, after exceptional items**: they use the figures exactly as printed in
the financial statements. TCS's own headline margins in its fact sheets *exclude* exceptional
items, so our number can legitimately differ from the one TCS quotes. Each ratio's definition
says this, so nobody mistakes one for the other.

## 2. Why duplicates happen at all
The same number gets printed more than once. FY26 revenue is in the FY26 annual report, and
again next year as last year's comparison figure, and maybe in a fact sheet. That's useful,
because a second copy is a free cross-check. It's also risky, because if the copies disagree we
must not quietly pick one.

## 3. The rules
**Which copy is the main one?** Each document in the config says which period it is *for*
(`period_covered`). The FY26 annual report is the primary source for FY26 figures. Other
documents printing the same figure are listed as `cross_checked_by`. If no document is for that
period (e.g. FY25 figures that so far only appear as comparatives in the FY26 report), the first
one loaded is returned and `primary_source` says False.

**When do two copies "agree"?** Documents round differently. The annual report prints whole
₹ crore; the fact sheet prints whole ₹ million (a tenth of a crore). So 267,021 crore and
2,670,212 million (= 267,021.2 crore) are the same figure printed two ways. Two figures agree if
the gap is no more than half of each one's rounding step added together (0.5 + 0.05 crore here).
The steps are in the company config.

**If they disagree**, the whole load is rejected and the message shows both numbers, both
documents and both pages, so you can open the PDFs and see which one you mistyped.

**Restatements** are the one legitimate disagreement: a company revises an old figure. You mark
the new row `restated = 1` and name the document it replaces in `supersedes_source_doc`. Lookups
then return the restated figure (flagged `restated`), and the original is still there if you ask
for `as_first_reported=True`. Growth ratios automatically use the restated prior year.

**Never mix accounting standards.** TCS's fact sheet has both IFRS pages and Ind AS pages. The
same "revenue" under IFRS and Ind AS is not the same fact, even if the numbers happen to match.
The config says which standard each page uses (IFRS: pages 14, 16, 17, 18, 20; Ind AS: 21, 22),
and figures are only compared within one standard. Lookups default to Ind AS. A fact citing a
page with no known standard (e.g. the highlights pages) is rejected until you tell the config
what standard that page follows.

## 4. One open design question
The accounting standard is worked out from the config (document + page), not stored in the
database. That kept the database design unchanged, but it means the database alone doesn't say
which standard a figure is in, and one document can't supply both an IFRS and an Ind AS figure
for the same line. Adding a database column would fix both. That's your call (NOTES.md).

## How the tests prove it
`tests/test_duplicates.py` covers each case: agreeing copies, rounding edges, a disagreement
that must be rejected (in one CSV, and against the database), IFRS vs Ind AS, restatements that
must be accepted (and restatement mistakes that must be rejected). Rows citing the fact sheet in
those tests are test-only; the fact sheet doesn't actually print those annual figures.
