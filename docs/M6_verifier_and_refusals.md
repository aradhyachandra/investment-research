# M6: Checking the answer before it ships (plain-language note)

After M5 the system could answer a question with figures that came from tools. But the final
sentence was still written by a small LLM, and nothing checked that sentence. The model could
copy a figure correctly and then add a claim around it that the data does not support. M6 adds
that check, makes refusals reliable, and adds a fixed line to every DCF answer.

The idea in one line: **the LLM writes the sentence; code reads it back and checks every
figure and every "rose/fell" claim against the tool results. If anything fails, the LLM's
sentence is thrown away and a code-written answer is shown instead.**

## 1. The verifier (`src/erp/agent/verifier.py`)

It is ordinary Python with no LLM. It gets the answer text and the tool results from the same
question, and runs four checks.

**a) Every number must come from a tool.** It finds each number in the text and looks for the
same number in the tool results. It allows for harmless formatting differences: "267,021",
"2,67,021" (Indian grouping) and "₹267,021" are the same figure, and "18.4%" is fine for a tool
value shown as "18.43%" (rounded to the decimals written). It does **not** allow a changed unit
("267,021 million", "2.67 lakh crore"), because converting units is arithmetic and the LLM may
not do arithmetic. Things that look like numbers but aren't figures are recognised and handled:
period names (FY26, 2025-26), dates (which must appear in the tool data), and page numbers
(which must be pages of the cited evidence). A number found only in a passage of the annual
report (for example "ISO 27001") is allowed with a warning. A number found nowhere is an error.

**b) Citations must be real.** Every evidence ID the model cites, e.g. `[fact:12]`, must exist in
this turn's tool results, and it must actually back the figure in its sentence. Citing the
profit fact for a revenue number is caught. This check also fixes an M5 problem: `numbers_used`
used to be whatever list of IDs the model gave, and the model often listed figures it never wrote
(in one live answer it listed six numbers and wrote one). Now `numbers_used` is built from the
figures the text actually contains.

**c) Comparisons must be backed by both figures, in the right order.** If a sentence says a
figure "increased", "fell", was "higher than", or went "from X to Y", the verifier finds which
figure it is about (from its name, e.g. "net margin") and the periods mentioned. It then checks
that the tool results contain **both** values and that their order matches the word. This
catches the M5 live failure "net margin decreased from FY25 to FY26" when only FY26 had been
fetched, and it catches a wrong direction ("increased" when it fell).

For DCF sensitivity answers it checks two more things:
- "terminal growth **decreases to** 5.00%" is wrong if 5.00% is the scenario's own terminal
  growth (nothing changed). This was a real slip by the model.
- A value from the sensitivity grid must be the cell for the conditions the sentence states. In
  one live answer the model wrote "increasing WACC to 13.92% decreases the value per share to INR
  1,858.48". That number was real, but it was the cell where terminal growth had *also* changed
  to 6.00%. The verifier now catches this: an input the sentence doesn't mention must stay at
  the scenario's own value.

**d) Judgement words are flagged, not blocked.** Words like "stable", "strong" or "significant"
with no figure behind them are recorded as warnings. They don't stop the answer.

**What happens on a failure.** The loop throws the LLM's text away and shows the
**template answer**: a plain list of the tool figures with their sources, written by code. The
verifier's full report is saved in the `Answer` (`verification`) and summarised in `warnings`, so
it is always visible what was rejected and why. An unchecked number is never shown silently.

## 2. Refusals that don't depend on the small model (`src/erp/agent/guardrails.py`)

M5 relied on the router (the LLM) to refuse out-of-scope questions. A live test this session
showed that isn't enough. The router alone *answered* "Is TCS undervalued?", "TCS vs Infosys
margins" and "Is the share price below the DCF value?".

So a **pre-check** now runs before the LLM is called. It is a short list of patterns in
`config/agent.yaml`: valuation verdicts ("undervalued", "target price"), advice ("should I buy",
"is TCS a good investment"), price forecasts ("will it hit 5000", "share price next year"), and
other-company names (in `config/companies/tcs.yaml`). It also refuses any question about a period
**after** the latest data (e.g. "revenue in FY28"), because that would be a forecast. Each refusal
uses the same fixed text as before. The patterns are kept narrow on purpose, so questions that
only *sound* like advice still go through: "What does the DCF imply?", "Did TCS buy back
shares?". The router's own refusal is still there as a second line.

## 3. The fixed DCF footer

Every answer that used the DCF ends with this line, added by code after all checks:

> Illustrative value implied by the stated assumptions, which were drafted with AI assistance;
> not a prediction or investment advice.

The LLM never writes it and cannot remove or change it. If the model writes its own copy, that
copy is removed so the line appears once. The wording lives in `config/agent.yaml`, so it can
change once a finance partner has reviewed the assumptions.

## 4. Retrieval: investigated, not changed

Two live questions got the wrong passages: dividends/buybacks and client concentration. Tested
on the 12 provisional retrieval probes (recall@5, before = 9 of 12):
- Removing "TCS" from the query: 11 of 12. But the agent searches with the router's rewritten
  query, which already leaves "TCS" out, and on one live wording it made results worse.
- Re-ranking by word overlap: 11–12 of 12. But it has two settings, and picking them on the same
  12 probes would be overfitting.

Neither is a clear, honest win, so neither went in. What was learned: the "no single customer is
10% or more of revenue" sentence sits inside a table-heavy chunk, so search can't find it (this is
a chunking problem). In the dividends case, the right page was actually retrieved, but the model
still said "not available". Details are in NOTES.md.

## 5. Fallback router: not needed

The plan builds a fallback router only if routing accuracy is below about 90%. On the provisional
dev questions it is 20 of 20, so it was not built.

## How to explain M6 in one breath

"The model writes the answer, but code reads it back. Every number has to be one the tools
returned, every citation has to exist and back its number, and every 'went up / went down' claim
has to match the two figures it's comparing. If any check fails, the model's text is replaced
by a code-written list of the figures and their sources. Advice and prediction questions are
refused by fixed rules before the model sees them, and every DCF answer ends with a fixed line
saying it is illustrative and not advice."
