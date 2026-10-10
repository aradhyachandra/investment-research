# U1: friendlier fixed answers for meta questions, more accurate refusal reasons

Everything here is code and config. The router prompt is unchanged, and the model is never asked to
decide these cases.

## 1. "What can you do?" gets an answer, not a refusal

Before U1, "what can you tell me?" went to the model, which had no good option and refused it as
investment advice. Now a short list of patterns in `config/agent.yaml` (`about.patterns`) spots
help / about questions: "help", "what can you do", "who are you", "who made you", "how do you work",
and so on. Each pattern must match the **whole** question, so "What can you tell me about TCS's
dividends in FY25?" is still a real question and still goes to the router.

When one matches, `loop.py` returns the fixed text from `about.text`: what the assistant is, how it
works, five example questions, and what it does not do. No model, no tools, no figures.
The refusal pre-check runs first, so an advice question can never be answered as "about".

The answer has `composed_by = "about"`. The UI shows it as a normal answer with a blue
"About this assistant" badge, not the grey "Refused by code" box.

The text says "178 verified facts from TCS's annual reports for FY24, FY25 and FY26 (covering FY23 to
FY26)". A test reads the real database and fails if those counts or years stop matching, so the text
cannot drift silently. (The brief said "four annual reports"; the database has three. FY23 figures are
the comparatives printed in the FY24 report.)

## 2. Share price questions get an honest reason

"What was TCS's share price at the end of FY25?" used to be refused as `price_prediction`, which is
wrong: it is not a forecast, we just have no price data. A new pre-check reason, `no_market_data`,
covers share/stock/closing price, market cap, market value of TCS, P/E and P/B multiples, dividend
yield, "trading at", and 52-week high/low. Its fixed text starts: "I don't have market price data;
this tool works from TCS's annual reports."

The order matters and is deliberate:
- `investment_advice` is checked first, so "Is the share price below the DCF value?" stays advice.
- `price_prediction` is next, so "Will the share price go up?" stays a forecast refusal.
- Another company's share price is reported as `other_company`.
- Not refused: a buyback price (it is in the filings), the face value of a share, and "what does the
  annual report say about the share price".

## 3. Why factual dividend questions were refused as advice

**The pattern pre-check was not the cause.** I ran it on both reported questions ("what can you tell
me?" and "What total dividend per share did TCS declare for FY25?"): it passes both. The saved v1.1
test answer for V11-E02 shows `route.problems` empty (a pre-check refusal always writes a problem
line) and the model's raw reply set `refusal_reason: investment_advice`. So **the model** refused it.
The README calls this an over-refusal "by the advice pre-check"; that wording is wrong.

Because the prompt must not change, the fix is a code rule after the router (`router.py`,
`advice_refusal_is_factual`). A model `investment_advice` refusal is overridden only when all three hold:
1. the question opens like a factual question (what, how much, how many, when, which, did, was, list ...);
2. it names a dividend / payout / share / EPS / buyback topic;
3. it has none of the judging or personal words (should, would, I, my, we, worth, good, best, safe,
   attractive, think, opinion, "you recommend" ...).

Then the plan becomes a search of the filings (with the R2 year filter), plus a fact lookup if the
question names exactly one metric (e.g. "basic EPS" -> `eps_basic` for each named year). Other
refusal reasons (other company, forecast) are never overridden. Advice questions are still refused
before the router by the unchanged pattern pre-check ("Should I buy TCS for the dividend?", "Is TCS a
good investment?", "Is TCS undervalued?").

Seen live: "How much dividend per share did TCS pay for FY24?" was refused by the model as advice;
the rule turned it into a search, and an answer was given.

## Results
- New tests: `tests/test_u1_meta_answers.py`, 77 tests, all new phrasings (written first, seen failing).
- Whole suite in batches: no failures (1,075 collected = 998 before + 77 new; 2 skipped as before).
- Live, qwen2.5:3b: v1 guardrail phrasings 12 of 13 (same known miss, industry average);
  provisional dev routing 20 of 20. The five example questions in the about text all answer.
