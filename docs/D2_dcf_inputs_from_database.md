# D2: the DCF reads its starting figures from the database

## What I built

Before D2, the DCF's starting figures (FY26 revenue, cash and investments, lease liabilities,
minority interest, share count) were numbers typed into `data/manual/dcf_inputs.yaml`, each with a
note saying which page they came from. The same figures were also in the facts database, checked
by a human. That meant two copies of the same number, and nothing stopped them drifting apart.

Now the YAML says *which facts* to use instead of typing the number:

    minority_interest:
      from_db: [non_controlling_interests]
      rationale: "..."
      source: "..."
      adjustments:
        - value: 126
          rationale: "Class B CCPS of a subsidiary held by others ..."
          source: "AR FY26 balance sheet PDF p.166"

When the DCF runs, code fetches each fact for the fiscal year that ends on the valuation date
(FY26), on the consolidated basis, with the same lookup function every other answer uses. It adds
the facts up, then adds the adjustments.

**Adjustments are judgement calls, kept separate on purpose.** Some of the old typed numbers were
not plain report figures: cash had 609 and 2,289 taken off (balances that are not free cash), and
minority interest had 126 added. Those are decisions, not facts. They stay in the YAML, each with
its own value, reason and page, written as a change to a database figure. So you can see "database
says 46,896; we take off 609 and 2,289; we use 43,998" instead of one unexplained 43,998.

**Leases** are fetched too (11,283), but the file says `treat_as: operating_cost`. Lease costs are
already inside EBIT, so subtracting the liability as well would count them twice. The bridge uses 0.
The fetched total is still recorded, so you can see what was left out and why.

**Debt** is still typed (0). There is no borrowings figure in the database yet.

## What you get from it

- **Citations.** Every DCF answer now cites the facts it started from, with their PDF pages, the
  same way a ratio answer cites its inputs. The `dcf_run` record stores the fact ids and pages.
- **Missing data refuses.** If one of these facts is missing for the valuation year, the DCF
  refuses and names the metric and the year. It never falls back to an old typed number.
- **Unchecked data is labelled.** If any input fact has not been checked by a human, the DCF still
  runs, but the result and the answer say "This DCF uses N facts not yet verified by a human".
- **The UI shows where each input came from**: database figures with page chips, adjustments
  marked as judgement, and a "From" column in the assumptions table.

## Did the answer change?

No, at the precision anyone sees. The base, bear and bull values per share are still INR 1,914.82,
1,445.11 and 2,351.66, and a test pins them. The equity values are identical to the last digit.
The only movement is in the ninth significant figure: the old YAML had rounded the share count to
361.80875 crore, and the database holds the exact count, 361.8087518 crore.

## Why it was built this way

- **One source for each number.** A figure that is checked once in the database should not be typed
  again somewhere else.
- **Code does the adding.** The sums are plain Python; the language model never sees or adds them.
- **Decisions stay visible.** Facts come from the report; adjustments and treatments come from
  someone's judgement. Keeping them apart makes it obvious which is which, and who has to defend it.
