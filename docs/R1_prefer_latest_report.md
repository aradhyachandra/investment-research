# R1: Letting the latest annual report win (plain-language note)

## The problem

Since D3 the search index holds three TCS annual reports (FY24, FY25, FY26). Large parts of an
annual report are repeated almost word for word every year: the risk descriptions, the risk
management framework, the capital allocation policy. When you search for "how does TCS manage
cyber risk?", the FY24 and FY25 copies of that passage are about as close a match as the FY26
copy, and sometimes slightly closer by chance. So the older copies pushed the latest one down:
on the 12 provisional probe questions, 32 of the 60 top-5 results came from the older reports,
and the expected FY26 page fell from 1st to 4th on one probe (PROV-01).

Nothing was "wrong" with the older passages, but a reader asking a question without naming a
year almost always means "now", i.e. the latest report.

## The fix: a small, configured recency weight

When the question names no year, every search result's score is multiplied by a weight:

- the latest annual report in the index: x 1.0
- one year older: x 0.95
- two years older: x 0.95 x 0.95 = x 0.9025

The number 0.95 is in `config/ingest.yaml` (`retrieval.recency.factor_per_year`), not in code.
It means an older passage has to be about 5% more similar per year of age to beat the latest
one. Near-copies of the same passage differ by roughly 0-4%, so the latest copy now wins, while
an older passage that is clearly a better match can still come first.

"Latest" is worked out separately for each kind of document (annual report, fact sheet, quarterly
results), from everything in the index. So the Q1 FY27 quarterly document does not make the FY26
annual report count as "old".

## When the weight is not used

- **The question names a year** ("attrition in FY24", "fiscal 2024", "2023-24"). Then search ranks
  all reports exactly as before. The check is done in code by the router, using the same period
  reader the verifier uses (`periods_in`), on both the question and the search phrase. The LLM
  cannot switch the weight on or off.
- A search that is already filtered to one year or one document.
- Any direct call to `search_documents` that does not ask for it (`prefer_latest` defaults to
  off). The naive-RAG baseline in the eval is such a call, so it is unchanged.

## What it did (12 provisional probes, not the eval)

| | before | after |
|---|---|---|
| recall@5 | 9 of 12 | 9 of 12 |
| recall@10 | 11 of 12 | 11 of 12 |
| top-5 results from the latest (FY26) report | 28 of 60 | 47 of 60 |

PROV-01 went from 4th back to 1st, PROV-02 and PROV-04 from 2nd to 1st (all three were 1st before
D3 added the older reports). PROV-09 and PROV-11 name "FY 2026", so they get no weight and did
not change. For information only (the value was not chosen from this): factor 0.90 gives 52 of
60, 0.98 gives 41 of 60; recall was the same at all three.

The second idea in the brief (collapsing near-duplicate passages from different reports) was not
built: the first fix already did the job.

## Something this exposed: year questions are not filtered

The brief assumed that when a question names a year, search is filtered to that year. It is not,
and never was: the router can only give `search_documents` a query; it has no way to pass a year.
With four new "older year" questions, the right year's report supplies only 0 to 3 of the top 5
results today (unchanged by R1). With a year filter it would be 5 of 5 every time. If the weight
were applied to those questions anyway, it would be 0 or 1 of 5, which is why the router turns it
off. Making the router pass the year as a filter is a separate change, left for the author to
decide.

## Words to know
- **Recency weight**: a number below 1 that older documents' scores are multiplied by.
- **recall@k**: share of questions where a correct page appears in the top k results.
- **Near-duplicate**: the same passage, lightly edited, repeated in another year's report.
