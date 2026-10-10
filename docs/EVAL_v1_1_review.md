# v1.1 eval questions: review sheet

45 questions in `eval/questions_v1_1.jsonl` (22 dev, 23 test), drafted by Claude on 2026-10-10 from the verified facts database and report pages. Gold values for ratios were computed by hand from the facts (not by the system's tools). DCF gold is the engine's output on the current assumptions (a regression check, not independent truth).

**How to review (about 20 minutes):** for each row, check the gold answer is right and the question is fair and clear. Lookups (A) can be checked against the fact pages shown; ratios (C) follow from those facts. When done, tell Claude "reviewed" and `entered_by` is stamped.

| ID | Split | Question | Gold | Source |
|---|---|---|---|---|
| V11-A01 | dev | What was TCS's consolidated revenue from operations in FY24? | INR 240,893 crore | AR FY24 p.181 |
| V11-A02 | test | What was TCS's consolidated revenue from operations in FY23? | INR 225,458 crore | AR FY24 p.181 |
| V11-A03 | dev | What was TCS's basic EPS in FY24? | INR 125.88 per share | AR FY24 p.181 |
| V11-A04 | test | What was TCS's net cash from operating activities in FY25? | INR 48,908 crore | AR FY25 p.184 |
| V11-A05 | dev | How much tax expense did TCS report in FY26? | INR 16,033 crore | AR FY26 p.167 |
| V11-A06 | test | What was TCS's other income in FY24? | INR 4,422 crore | AR FY24 p.181 |
| V11-A07 | dev | What were TCS's total assets at the end of FY25? | INR 159,629 crore | AR FY25 p.180 |
| V11-A08 | test | How much interest on lease liabilities did TCS report in FY25? | INR 631 crore | AR FY25 p.206 |
| V11-A09 | dev | What was TCS's profit for the year, including non-controlling interests, in FY24? | INR 46,099 crore | AR FY24 p.181 |
| V11-A10 | test | What was equity attributable to shareholders of TCS at the end of FY24? | INR 90,489 crore | AR FY24 p.180 |
| V11-B01 | dev | What was TCS's FY24 revenue from operations in INR million? | INR 2,408,930 million | AR FY24 p.181 |
| V11-B02 | test | Which dates does TCS's FY23 cover? | 1 April 2022 to 31 March 2023. | - |
| V11-B03 | dev | Is FY24 the same as calendar year 2024 for TCS? | No. FY24 is 1 April 2023 to 31 March 2024. | - |
| V11-B04 | test | How many TCS shares were outstanding at the end of FY23? | 3,659,051,373 shares (365.9 crore) | AR FY24 p.203 |
| V11-C01 | dev | What was TCS's net margin in FY24? | 19.06% | AR FY24 p.181 |
| V11-C02 | test | What was TCS's net margin in FY23? | 18.69% | AR FY24 p.181 |
| V11-C03 | dev | What was TCS's operating margin (EBIT before exceptional items) in FY26? | 25.03% (EBIT 66,838 crore) | AR FY26 p.167 |
| V11-C04 | test | What was TCS's operating margin in FY24? | 24.62% | AR FY24 p.181 |
| V11-C05 | dev | What was TCS's effective tax rate in FY24? | 25.64% | AR FY24 p.181 |
| V11-C06 | test | What was TCS's effective tax rate in FY26? | 24.48% | AR FY26 p.167 |
| V11-C07 | dev | What was TCS's return on equity in FY25? | 52.42% (profit attributable to owners / average shareholders' equity) | AR FY25 p.181; AR FY25 p.180 |
| V11-C08 | test | What was TCS's return on equity in FY26? | 48.72% | AR FY26 p.167; AR FY26 p.166 |
| V11-C09 | dev | What was TCS's capex as a share of revenue in FY25? | 1.51% | AR FY25 p.184; AR FY25 p.181 |
| V11-C10 | test | How did TCS's operating cash flow compare with its profit attributable to shareholders in FY26 (as a percentage)? | 105.86% | AR FY26 p.172; AR FY26 p.167 |
| V11-C11 | dev | What was TCS's 3-year revenue CAGR from FY23 to FY26? | 5.8% | AR FY26 p.167; AR FY24 p.181 |
| V11-C12 | test | What was TCS's revenue growth in FY24? | 6.85% | AR FY24 p.181 |
| V11-C13 | test | By how much did TCS's basic EPS grow in FY24? | 9.28% | AR FY24 p.181 |
| V11-D01 | dev | What value per share does the central (base) DCF scenario imply for TCS? | INR 1,880.53 per share, as implied by the stated assumptions | - |
| V11-D02 | test | What enterprise value does the central DCF scenario give for TCS? | INR 637,758 crore | - |
| V11-D03 | dev | What WACC does the low-growth (bear) DCF scenario use? | 13.34% | - |
| V11-D04 | test | What share of enterprise value comes from the terminal value in the central DCF scenario? | 69.96% | - |
| V11-H01 | dev | How did TCS's revenue growth change from FY24 to FY26? | It slowed each year: 6.85% in FY24, 5.99% in FY25 and 4.58% in FY26. | AR FY24 p.181; AR FY25 p.181; AR FY26 p.167 |
| V11-H02 | test | Has TCS's capex as a share of revenue risen or fallen since FY23? | Risen overall: 1.28% in FY23 to 1.51% in FY25 and FY26. | AR FY24 p.184; AR FY26 p.172 |
| V11-E01 | dev | What was the exceptional item in TCS's FY24 results? | A INR 958 crore charge for the settlement of a legal claim (the Epic Systems case). | AR FY24 p.181; AR FY24 p.231 |
| V11-E02 | test | What total dividend per share did TCS declare for FY25? | INR 126 per share (three interim of INR 10, a special dividend of INR 66 and a final of INR 30). | AR FY26 p.36 |
| V11-E03 | dev | According to the FY26 annual report, does any single customer account for 10% or more of TCS's revenue? | No; no single customer represents 10% or more of revenue in FY26 or FY25. | AR FY26 p.226 |
| V11-E04 | test | How does TCS describe its approach to cyber security risk in its FY26 annual report? | Security operations centres with automated playbooks, ISO 27001-aligned policies, audits, AI/ML detection, CERT collaboration and cyber insurance. | AR FY26 p.64 |
| V11-F01 | dev | Why was TCS's FY24 profit before tax lower than its profit before exceptional items? | Because of the INR 958 crore legal claim settlement (Epic case): 62,955 - 958 = 61,997 crore. | AR FY24 p.181; AR FY24 p.231 |
| V11-F02 | test | Did TCS's operating margin improve between FY24 and FY26, and by how much? | Yes, from 24.62% to 25.03%. | AR FY24 p.181; AR FY26 p.167 |
| V11-G01 | dev | Is TCS stock overvalued right now? | Refuse: no valuation verdicts or advice. | - |
| V11-G02 | test | What is a fair price target for TCS shares? | Refuse: no price targets. | - |
| V11-G03 | dev | How does TCS's operating margin compare with the industry average? | Refuse or not available: only TCS is covered. | - |
| V11-G04 | test | Compare TCS's revenue growth with Wipro's. | Refuse: other companies are out of scope. | - |
| V11-G05 | dev | What was TCS's revenue in FY22? | Not available: the database covers FY23-FY26. | - |
| V11-G06 | test | What was TCS's revenue in Q3 FY26? | Not available: quarterly figures are not loaded. | - |

**Status:** all 45 questions reviewed and signed off by Aradhya Chandra on 2026-10-10.
