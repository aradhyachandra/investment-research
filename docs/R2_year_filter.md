# R2: a question that names a year searches that year's report (plain-language note)

## The problem

R1 found that "year" questions were never filtered: the router could only give `search_documents`
a search phrase, never a year. So "What did TCS say about attrition in FY24?" searched all three
annual reports equally, and the FY24 report supplied only 0 to 3 of the top 5 passages. The rest
were near-copies from FY25 or FY26: well-matched text, but from the wrong year.

## The fix

The router now adds a year filter to the search, and **code decides it, not the model**:

1. Code reads the periods named in the question with the same period reader the verifier uses
   (`periods_in`). It understands "FY24", "FY 2024", "2023-24" and "fiscal 2024".
2. If the question names **exactly one** period, that period is a **fiscal year** (not a quarter),
   and the database has data for it (FY23 to FY26 today), the period resolver turns it into a
   number (FY24 -> 2024) and the search call gets `fiscal_year: 2024`.
3. Otherwise there is no filter.

The model cannot set the year: `fiscal_year` is not in the list of fields it fills in, and if it
writes one anyway it is dropped. The router prompt was not changed.

| The question names | Year filter | Latest-report preference (R1) |
|---|---|---|
| no period | none | on |
| one fiscal year with data (e.g. FY24) | that year | off |
| two or more periods (FY24 and FY26) | none | off |
| a quarter (Q1 FY27), or a year with no data (FY22) | none | off |

## When the year has no indexed report

The database has FY23 figures, but no FY23 annual report is in the search index. A filtered search
for FY23 finds nothing. Instead of failing quietly, the search tool then searches all reports and
adds a note to its result: "No passages from FY23 documents are indexed, so all indexed reports
were searched instead; these passages are not from FY23." That note reaches the answer as a
limitation. Checked live: an FY23 attrition question returns FY26, FY25 and FY24 passages, with
the note.

## What it did (PROVISIONAL probes, not the eval)

| | before (R1) | after (R2) |
|---|---|---|
| 4 "older year" questions: top-5 from the named year's report | 3, 1, 2, 0 of 5 | 5, 5, 5, 5 of 5 |
| 12 retrieval probes: recall@5 | 9 of 12 | 9 of 12 |
| recall@10 | 11 of 12 | 11 of 12 |
| top-5 from the latest (FY26) report | 47 of 60 | 53 of 60 |

Two of the 12 probes name "FY 2026". They are now filtered to the FY26 report, which accounts for
the 47 -> 53. PROV-11 moved from 8th to 6th. Routing of the 20 provisional dev questions with the
live model: 19 of 20 before and after, with identical routes. The one miss (PDEV-07) was already
there before this change (see PROGRESS.md).

## Questions naming two or more years

These get no filter and no recency weight, the same as in R1, so all reports compete equally.
Checked live, the results are a mix. One named year can be missing entirely, and an unnamed year
can appear: "Which companies did TCS acquire in FY24 and FY25?" returned FY24 and FY26 passages and
no FY25 passage. A possible next step is one search per named year (like the router already does
for figures in two years). It has not been built.

## Words to know
- **Filter**: only passages whose document has this fiscal year are considered at all.
- **Fallback**: if the filter leaves nothing, search again without it, and say so.
- **Period resolver**: the code that turns a label like FY24 into its real dates and year number.
