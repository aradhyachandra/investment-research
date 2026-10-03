"""DCF arithmetic: FCFF from drivers, WACC, discounting, terminal value, EV -> equity bridge,
sensitivity grid. Pure functions, no LLM, no database, no market price.

Every function returns all of its intermediate values so the UI can show the calculation path.

Timing convention (TO VERIFY with the finance partner): year-end discounting in whole years.
The cash flow of forecast year t arrives at the END of year t and is discounted by
DF_t = 1 / (1 + WACC)^t, counting from the valuation date. Mid-year discounting
(DF_t = 1 / (1 + WACC)^(t - 0.5)) is a common alternative and is NOT implemented. A valuation
date part-way through a fiscal year (stub period) is also not handled.
"""
from pydantic import BaseModel, Field


class DCFError(ValueError):
    pass


# WACC must exceed terminal growth by more than this. Guards against float rounding noise:
# 0.07 + 1.0 x 0.05 = 0.12000000000000001, which would otherwise let g = 0.12 "pass" and
# divide by ~1e-17.
MIN_WACC_GROWTH_SPREAD = 1e-9


def growth_below_wacc(terminal_growth: float, wacc: float) -> bool:
    return wacc - terminal_growth > MIN_WACC_GROWTH_SPREAD


# ---------- FCFF from drivers (PROJECT_PLAN.md 5.1) ----------

class FCFFYear(BaseModel):
    year: int                    # 1 = first forecast year
    revenue_prior: float
    revenue_growth: float
    revenue: float
    ebit_margin: float
    ebit: float                  # operating profit; other income is NOT included
    tax_rate: float
    taxes_on_ebit: float
    nopat: float                 # EBIT x (1 - tax)
    da_pct_revenue: float
    da: float
    capex_pct_revenue: float
    capex: float
    incremental_revenue: float
    nwc_pct_incremental_revenue: float
    nwc_increase: float          # negative when revenue shrinks (working capital released)
    fcff: float                  # NOPAT + D&A - capex - NWC increase


def _per_year(name: str, value, horizon: int) -> list[float]:
    if isinstance(value, (list, tuple)):
        if len(value) != horizon:
            raise DCFError(f"{name} has {len(value)} values; the forecast has {horizon} years")
        return [float(v) for v in value]
    return [float(value)] * horizon


def build_fcff(base_revenue: float, revenue_growth, ebit_margin, tax_rate, da_pct_revenue,
               capex_pct_revenue, nwc_pct_incremental_revenue, horizon: int | None = None) -> list[FCFFYear]:
    """Forecast FCFF per year. Each driver is one number for every year or a list (one per year).

    FCFF = EBIT x (1 - tax) + D&A - capex - increase in NWC, where
    NWC increase = nwc_pct x (revenue_t - revenue_{t-1}).
    Other income (treasury income for TCS) is deliberately not an input: the cash and
    investments that earn it are added in the bridge instead (no double counting).
    TO VERIFY: with negative EBIT this formula gives a tax credit; not relevant for the toy case.
    """
    drivers = {"revenue_growth": revenue_growth, "ebit_margin": ebit_margin, "tax_rate": tax_rate,
               "da_pct_revenue": da_pct_revenue, "capex_pct_revenue": capex_pct_revenue,
               "nwc_pct_incremental_revenue": nwc_pct_incremental_revenue}
    if horizon is None:
        lengths = [len(v) for v in drivers.values() if isinstance(v, (list, tuple))]
        if not lengths:
            raise DCFError("no per-year list given; pass horizon")
        horizon = lengths[0]
    if horizon < 1:
        raise DCFError("forecast is empty: horizon must be at least 1 year")
    if base_revenue <= 0:
        raise DCFError(f"base_revenue must be greater than 0, got {base_revenue}")
    d = {name: _per_year(name, v, horizon) for name, v in drivers.items()}

    years, prior = [], float(base_revenue)
    for i in range(horizon):
        revenue = prior * (1 + d["revenue_growth"][i])
        ebit = revenue * d["ebit_margin"][i]
        taxes = ebit * d["tax_rate"][i]
        nopat = ebit - taxes
        da = revenue * d["da_pct_revenue"][i]
        capex = revenue * d["capex_pct_revenue"][i]
        incremental = revenue - prior
        nwc_increase = incremental * d["nwc_pct_incremental_revenue"][i]
        years.append(FCFFYear(
            year=i + 1, revenue_prior=prior, revenue_growth=d["revenue_growth"][i], revenue=revenue,
            ebit_margin=d["ebit_margin"][i], ebit=ebit, tax_rate=d["tax_rate"][i], taxes_on_ebit=taxes,
            nopat=nopat, da_pct_revenue=d["da_pct_revenue"][i], da=da,
            capex_pct_revenue=d["capex_pct_revenue"][i], capex=capex, incremental_revenue=incremental,
            nwc_pct_incremental_revenue=d["nwc_pct_incremental_revenue"][i], nwc_increase=nwc_increase,
            fcff=nopat + da - capex - nwc_increase,
        ))
        prior = revenue
    return years


# ---------- WACC (PROJECT_PLAN.md 5.1) ----------

class WACCResult(BaseModel):
    risk_free_rate: float
    beta: float
    equity_risk_premium: float
    cost_of_equity: float        # risk-free + beta x ERP
    equity_weight: float         # 1 - debt_weight
    debt_weight: float
    cost_of_debt_pre_tax: float
    debt_tax_rate: float
    cost_of_debt_after_tax: float
    wacc: float


def cost_of_equity(risk_free_rate: float, beta: float, equity_risk_premium: float) -> float:
    return risk_free_rate + beta * equity_risk_premium


def compute_wacc(risk_free_rate: float, beta: float, equity_risk_premium: float, debt_weight: float,
                 cost_of_debt_pre_tax: float, debt_tax_rate: float) -> WACCResult:
    """WACC = E/(D+E) x cost of equity + D/(D+E) x cost of debt x (1 - tax). debt_weight = 0 is all-equity."""
    if not 0 <= debt_weight < 1:
        raise DCFError(f"debt_weight must be at least 0 and below 1, got {debt_weight}")
    ke = cost_of_equity(risk_free_rate, beta, equity_risk_premium)
    kd_after = cost_of_debt_pre_tax * (1 - debt_tax_rate)
    equity_weight = 1 - debt_weight
    return WACCResult(
        risk_free_rate=risk_free_rate, beta=beta, equity_risk_premium=equity_risk_premium, cost_of_equity=ke,
        equity_weight=equity_weight, debt_weight=debt_weight, cost_of_debt_pre_tax=cost_of_debt_pre_tax,
        debt_tax_rate=debt_tax_rate, cost_of_debt_after_tax=kd_after,
        wacc=equity_weight * ke + debt_weight * kd_after,
    )


# ---------- EV -> equity bridge ----------

class Bridge(BaseModel):
    """Bridge items, in the same money unit as FCFF. All are amounts (not negative)."""
    cash_and_investments: float = Field(ge=0)
    debt: float = Field(ge=0)
    lease_liabilities: float = Field(ge=0)   # 0 if leases are treated as operating costs in EBIT (TO VERIFY)
    minority_interest: float = Field(ge=0)
    diluted_shares: float = Field(gt=0)


class BridgeResult(BaseModel):
    enterprise_value: float
    cash_and_investments: float
    debt: float
    lease_liabilities: float
    minority_interest: float
    equity_value: float
    diluted_shares: float
    value_per_share: float


def equity_bridge(enterprise_value: float, bridge: Bridge, money_per_unit: float = 1,
                  shares_per_unit: float = 1) -> BridgeResult:
    """Equity = EV + cash and investments - debt - lease liabilities - minorities.

    value per share = equity x money_per_unit / (shares x shares_per_unit), e.g. money in INR crore
    (money_per_unit 1e7) and shares as a plain count (shares_per_unit 1) gives rupees per share.
    """
    equity = (enterprise_value + bridge.cash_and_investments - bridge.debt
              - bridge.lease_liabilities - bridge.minority_interest)
    per_share = equity * money_per_unit / (bridge.diluted_shares * shares_per_unit)
    return BridgeResult(enterprise_value=enterprise_value, equity_value=equity, value_per_share=per_share,
                        **bridge.model_dump())


# ---------- valuation ----------

class ValuationResult(BaseModel):
    discounting: str             # 'year_end' (see module docstring)
    wacc: float
    terminal_growth: float
    years: list[int]
    fcff: list[float]
    discount_factors: list[float]
    pv_fcff: list[float]
    sum_pv_fcff: float
    terminal_fcff: float         # FCFF of year n+1 = FCFF_n x (1 + g)
    terminal_value: float        # at end of year n: FCFF_(n+1) / (WACC - g)
    pv_terminal_value: float
    enterprise_value: float
    tv_share_of_ev: float | None  # None if EV is not positive
    bridge: BridgeResult
    equity_value: float
    value_per_share: float


def value_firm(fcff: list[float], wacc: float, terminal_growth: float, bridge: Bridge, *,
               money_per_unit: float = 1, shares_per_unit: float = 1) -> ValuationResult:
    if not fcff:
        raise DCFError("forecast is empty: give at least one year of FCFF")
    if not growth_below_wacc(terminal_growth, wacc):
        raise DCFError(f"terminal growth {terminal_growth} must be below WACC {wacc}; "
                       "the Gordon growth formula is undefined otherwise")
    if wacc <= -1:
        raise DCFError(f"WACC {wacc} is not a valid discount rate")
    if fcff[-1] <= 0:
        raise DCFError(f"final-year FCFF is {fcff[-1]}; a terminal value needs a positive final-year FCFF")

    fcff = [float(x) for x in fcff]
    years = list(range(1, len(fcff) + 1))
    dfs = [1 / (1 + wacc) ** t for t in years]
    pvs = [cf * df for cf, df in zip(fcff, dfs)]
    terminal_fcff = fcff[-1] * (1 + terminal_growth)
    tv = terminal_fcff / (wacc - terminal_growth)
    pv_tv = tv * dfs[-1]
    ev = sum(pvs) + pv_tv
    b = equity_bridge(ev, bridge, money_per_unit, shares_per_unit)
    return ValuationResult(
        discounting="year_end", wacc=wacc, terminal_growth=terminal_growth, years=years, fcff=fcff,
        discount_factors=dfs, pv_fcff=pvs, sum_pv_fcff=sum(pvs), terminal_fcff=terminal_fcff,
        terminal_value=tv, pv_terminal_value=pv_tv, enterprise_value=ev,
        tv_share_of_ev=pv_tv / ev if ev > 0 else None, bridge=b, equity_value=b.equity_value,
        value_per_share=b.value_per_share,
    )


# ---------- sensitivity grid ----------

class SensitivityGrid(BaseModel):
    wacc_values: list[float]     # rows
    growth_values: list[float]   # columns
    value_per_share: list[list[float | None]]   # None where g >= WACC (formula undefined)


def sensitivity_grid(fcff: list[float], wacc_values: list[float], growth_values: list[float], bridge: Bridge,
                     *, money_per_unit: float = 1, shares_per_unit: float = 1) -> SensitivityGrid:
    """Value per share for every (WACC, terminal growth) pair, holding the FCFF forecast fixed."""
    rows = []
    for w in wacc_values:
        row = []
        for g in growth_values:
            if not growth_below_wacc(g, w):
                row.append(None)
            else:
                row.append(value_firm(fcff, w, g, bridge, money_per_unit=money_per_unit,
                                      shares_per_unit=shares_per_unit).value_per_share)
        rows.append(row)
    return SensitivityGrid(wacc_values=list(wacc_values), growth_values=list(growth_values), value_per_share=rows)
