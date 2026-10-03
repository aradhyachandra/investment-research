# M3: The DCF engine (plain-language note)

All numbers here are the **toy case** from the tests. They are not TCS figures and not
assumptions about TCS. Real assumptions come later, with the finance partner (P0.3).

A DCF answers one question: *if the business produces these cash flows, and money has this
cost, what is the business worth today?* The answer is "what these assumptions imply", not a
prediction and not a recommendation.

## 1. FCFF: the cash the business produces

**Free cash flow to the firm** is the cash left from operations after paying tax and
reinvesting. It belongs to everyone who funded the business (shareholders and lenders).

    FCFF = EBIT x (1 - tax) + D&A - capex - increase in working capital

- **EBIT** is operating profit. **Other income is left out on purpose.** TCS earns a lot of
  interest on its cash. That cash is added separately in the bridge (section 4); counting its
  income here as well would count the same money twice.
- **D&A** is added back because it is an accounting charge, not cash leaving.
- **Capex** and **more working capital** (receivables etc. growing with sales) are cash spent.

The engine builds FCFF from **drivers** you choose: revenue growth, EBIT margin, tax rate,
D&A % of revenue, capex % of revenue, and working capital as % of *extra* revenue.
Example (test): base revenue 1000, growth 10%, margin 20%, tax 25%, D&A 4%, capex 6%, NWC 10%:
revenue 1100, EBIT 220, after tax 165, + D&A 44, - capex 66, - working capital 10 = **133**.

The plan's toy case simply starts from FCFF of **100, 110, 121** for three years.

## 2. WACC: the cost of money

Future cash is worth less than cash today, because investors want a return. The discount
rate is the **weighted average cost of capital**:

    cost of equity = risk-free rate + beta x equity risk premium
    WACC = equity weight x cost of equity + debt weight x cost of debt x (1 - tax)

For a company with almost no debt, WACC is just the cost of equity. Example: 7% + 1.0 x 5% =
**12%**. The toy case uses 12%.

**Discounting.** Each year's cash is divided by 1.12 once per year of waiting (year-end
convention):

| Year | FCFF | Discount factor | Present value |
|---|---|---|---|
| 1 | 100 | 1/1.12 = 0.8929 | 89.29 |
| 2 | 110 | 1/1.2544 = 0.7972 | 87.69 |
| 3 | 121 | 1/1.4049 = 0.7118 | 86.13 |
| | | **sum** | **263.10** |

(Mid-year discounting, which assumes cash arrives through the year, is an alternative. Not
built; marked TO VERIFY.)

## 3. Terminal value: everything after year 3

The business doesn't stop after year 3. The **terminal value** assumes cash keeps growing at a
steady rate *g* forever (Gordon growth):

    TV = FCFF of year 4 / (WACC - g) = 121 x 1.04 / (0.12 - 0.04) = 125.84 / 0.08 = 1573

That 1573 is a value *at the end of year 3*, so it is discounted too: 1573 x 0.7118 = **1119.63**.

Two things to notice:
- **g must be below WACC**, or the formula divides by zero or a negative number. The engine
  refuses. It also checks g is below the risk-free rate (an economy-level ceiling).
- **The terminal value is most of the answer**: 1119.63 of the 1382.73 total, about **81%**.
  Small changes to g or WACC move the result a lot. That is why every run stores a
  **sensitivity grid** (value per share for WACC and g each nudged up and down), and a check
  warns when the TV share is outside a band.

## 4. The bridge: from the business to one share

    Enterprise value (EV) = 263.10 + 1119.63 = 1382.73

EV is the value of the *operations*. To get what belongs to shareholders:

    equity = EV + cash and investments - debt - lease liabilities - minority interests
           = 1382.73 + 200 - 50 - 0 - 0 = 1532.73
    per share = 1532.73 / 10 diluted shares = 153.27

- **Cash and investments** are added because the operations' value doesn't include them.
- **Debt and lease liabilities** belong to lenders/lessors, so they come off. (Leases: decide
  once with the finance partner whether they are debt here or a cost inside EBIT. Not both.)
- **Minority interests** are the share of subsidiaries owned by others.
- **Diluted shares** include options etc. that could become shares.

## 5. The assumptions file

Every assumption is written as a block with **value, rationale and source**. If any rationale
or source is missing or blank, anywhere in the file, the engine refuses to run and names the
assumption. Rates are decimals (0.12, not 12). A `shared` block holds common assumptions;
`base`, `bear`, `bull` blocks override only what differs. The commented example is
`tests/fixtures/dcf_toy_assumptions.yaml` (toy numbers; copy the shape, not the values).

## 6. What a run stores

`run_dcf(conn, ticker, scenario)` writes one `dcf_run` row: a full copy of the YAML file, every
intermediate value (FCFF build, WACC build, discount factors, PVs, TV, EV, bridge, per share,
grid), the pass/fail/warn checks, and the git SHA. If a blocking check fails, nothing is
stored. No market price is used anywhere, and nothing is called "cheap" or "expensive".

## 7. What is not done yet

- The **golden test** (Python within 0.1% of your hand spreadsheet) waits for P0.3.
- Checks that compare assumptions with history (margins, growth jumps) need more metrics in
  SQLite. Base revenue and bridge items are typed into the YAML for now. See NOTES.md.
