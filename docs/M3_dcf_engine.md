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

Every assumption is written as a block with **value, rationale and source**. (Since D2, base-year
revenue and the bridge items can instead point at the facts database; see section 8.) If any rationale
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
- ~~Checks that compare assumptions with history~~: done in D4 (section 9).

## 8. What now comes from where (D2, 2026-10-08)

The real file (`data/manual/dcf_inputs.yaml`) no longer types the starting figures. They are read
from the facts database: consolidated, for the fiscal year that ends on the valuation date (FY26).

| Input | From the database | Judgement in the YAML |
|---|---|---|
| Base-year revenue | revenue from operations | none |
| Cash and investments | cash + other bank balances + current investments + non-current investments | minus earmarked balances 609 and TCS Foundation deposits 2,289 (note, PDF p.185) |
| Lease liabilities | current + non-current lease liabilities | `treat_as: operating_cost`, so the bridge uses 0 |
| Minority interest | non-controlling interests | plus Class B CCPS of a subsidiary 126 (PDF p.166) |
| Diluted shares | shares outstanding (crore shares) | none |
| Debt | (no borrowings metric yet) | typed: 0 |

Everything else (growth, margins, tax, D&A, capex, working capital, WACC inputs, terminal growth)
is still a typed judgement in the YAML, as before.

Each database input is written like this:

    cash_and_investments:
      from_db: [cash_and_equivalents, other_balances_with_banks, current_investments, non_current_investments]
      rationale: "..."
      source: "..."
      adjustments:
        - {value: -609, rationale: "...", source: "AR FY26 ... PDF p.185"}

The engine adds the facts, then the adjustments. Each fact used is stored in the `dcf_run` row with
its fact id and page, and the answer cites it. If a fact is missing, the run refuses and names it;
there is no typed number to fall back on. If a fact has not been checked by a human, the run still
works but says "This DCF uses N facts not yet verified by a human".

## 9. Assumptions vs history (D4, 2026-10-10)

Every run now also computes, from the facts database, TCS's own record for the fiscal years ending
with the valuation year (FY23-FY26), using the DCF's own definitions (`config/dcf.yaml`, `history`):

| Assumption | History measure |
|---|---|
| revenue_growth | year-on-year revenue growth; plus the compound growth over the window |
| ebit_margin | (PBEIT - other income + finance costs - lease interest) / revenue (leases are an operating cost) |
| tax_rate | effective rate, tax / PBT: an **approximate** match (the DCF uses a statutory rate on EBIT) |
| da_pct_revenue | (D&A - right-of-use depreciation) / revenue |
| capex_pct_revenue | (PP&E + intangibles purchased) / revenue |
| nwc_pct_incremental_revenue | (operating profit before WC changes - cash generated from operations) / increase in revenue |

Each scenario value is checked against the historical min-max, widened by a tolerance from the
config (0 for now, TO VERIFY): **pass** or **warn**. A warning never stops a run, never changes a
value, and is stored apart from the engine checks (`outputs_json["history"]`, `DCFResult.history`),
so `all_checks_passed` still covers only the engine's sanity checks. An assumption with no history
definition is shown as "not matched" and warns. Missing years say why (FY23 growth needs FY22).

The plain-language summary of what the checks show is `docs/D4_assumptions_vs_history.md`.
