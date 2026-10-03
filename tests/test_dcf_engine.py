"""M3: DCF engine arithmetic (valuation, bridge, FCFF builder, WACC, sensitivity grid).

TOY NUMBERS ONLY. Nothing here is a TCS figure or a TCS assumption.

Expected values are literals worked out by hand and cross-checked with `bc -l` (scale=20),
NOT by calling the code under test.

Convention under test: year-end discounting with whole years, DF_t = 1 / (1 + WACC)^t.
"""
import pytest

from erp.dcf.engine import (
    Bridge,
    DCFError,
    build_fcff,
    compute_wacc,
    cost_of_equity,
    equity_bridge,
    sensitivity_grid,
    value_firm,
)

REL = 1e-9

# ---------- toy case (PROJECT_PLAN.md 2.5, Day 3) ----------
# FCFF 100, 110, 121; WACC 12%; terminal growth 4%; cash 200; debt 50; 10 shares.
#
# Discount factors:  1.12^1 = 1.12       DF1 = 1/1.12     = 0.892857142857142857
#                    1.12^2 = 1.2544     DF2 = 1/1.2544   = 0.797193877551020408
#                    1.12^3 = 1.404928   DF3 = 1/1.404928 = 0.711780247813411079
# PV of each year:   100 x DF1 =  89.285714285714285714
#                    110 x DF2 =  87.691326530612244898
#                    121 x DF3 =  86.125409985422740524
#   sum of PVs                 = 263.102450801749271136
# Terminal value (Gordon, at end of year 3):
#   FCFF4 = 121 x 1.04 = 125.84;  TV = 125.84 / (0.12 - 0.04) = 125.84 / 0.08 = 1573
# PV of TV = 1573 x DF3 = 1119.630329810495626811
# EV = 263.102450801749271136 + 1119.630329810495626811 = 1382.732780612244897946
# Equity = EV + cash 200 - debt 50 = 1532.732780612244897946
# Per share = 1532.732780612244897946 / 10 = 153.273278061224489795   (plan: "about 153.3")
# TV share of EV = 1119.630329810495626811 / 1382.732780612244897946 = 0.809722851377506898  (~81%)
TOY_FCFF = [100, 110, 121]
TOY_DF = [0.892857142857142857, 0.797193877551020408, 0.711780247813411079]
TOY_PV = [89.285714285714285714, 87.691326530612244898, 86.125409985422740524]
TOY_SUM_PV = 263.102450801749271136
TOY_TERMINAL_FCFF = 125.84
TOY_TV = 1573.0
TOY_PV_TV = 1119.630329810495626811
TOY_EV = 1382.732780612244897946
TOY_EQUITY = 1532.732780612244897946
TOY_PER_SHARE = 153.273278061224489795
TOY_TV_SHARE = 0.809722851377506898


def toy_bridge(**overrides):
    b = dict(cash_and_investments=200, debt=50, lease_liabilities=0, minority_interest=0, diluted_shares=10)
    b.update(overrides)
    return Bridge(**b)


def test_toy_case_every_intermediate():
    r = value_firm(TOY_FCFF, wacc=0.12, terminal_growth=0.04, bridge=toy_bridge())
    assert r.years == [1, 2, 3]
    assert r.fcff == TOY_FCFF
    assert r.discount_factors == pytest.approx(TOY_DF, rel=REL)
    assert r.pv_fcff == pytest.approx(TOY_PV, rel=REL)
    assert r.sum_pv_fcff == pytest.approx(TOY_SUM_PV, rel=REL)
    assert r.terminal_fcff == pytest.approx(TOY_TERMINAL_FCFF, rel=REL)
    assert r.terminal_value == pytest.approx(TOY_TV, rel=REL)
    assert r.pv_terminal_value == pytest.approx(TOY_PV_TV, rel=REL)
    assert r.enterprise_value == pytest.approx(TOY_EV, rel=REL)
    assert r.equity_value == pytest.approx(TOY_EQUITY, rel=REL)
    assert r.value_per_share == pytest.approx(TOY_PER_SHARE, rel=REL)
    assert r.tv_share_of_ev == pytest.approx(TOY_TV_SHARE, rel=REL)
    assert round(r.value_per_share, 1) == 153.3
    assert round(r.tv_share_of_ev * 100) == 81
    assert r.discounting == "year_end"


def test_per_share_unit_conversion():
    # Same toy firm, money in INR crore and the share count as a plain number of shares.
    # 10 shares-worth expressed as 10 x 10^7 shares; equity 1532.7327806... crore = x 10^7 rupees.
    # (1532.732780612244897946 x 10^7) / (10 x 10^7) = 153.273278061224489795 (bc)
    r = value_firm(TOY_FCFF, 0.12, 0.04, toy_bridge(diluted_shares=10e7), money_per_unit=1e7, shares_per_unit=1)
    assert r.value_per_share == pytest.approx(TOY_PER_SHARE, rel=REL)


# ---------- bridge with leases and minorities ----------
# EV 1000 + cash and investments 300 - debt 100 - lease liabilities 80 - minorities 20
#   = 1100 equity;  1100 / 50 shares = 22.0 per share
def test_bridge_with_leases_and_minorities():
    b = Bridge(cash_and_investments=300, debt=100, lease_liabilities=80, minority_interest=20, diluted_shares=50)
    r = equity_bridge(1000, b)
    assert r.equity_value == pytest.approx(1100, rel=REL)
    assert r.value_per_share == pytest.approx(22.0, rel=REL)


def test_bridge_items_flow_through_value_firm():
    # Toy EV 1382.732780612244897946 + 200 - 50 - 30 (leases) - 20 (minorities)
    #   = 1482.732780612244897946;  / 10 = 148.273278061224489795
    r = value_firm(TOY_FCFF, 0.12, 0.04, toy_bridge(lease_liabilities=30, minority_interest=20))
    assert r.equity_value == pytest.approx(1482.732780612244897946, rel=REL)
    assert r.value_per_share == pytest.approx(148.273278061224489795, rel=REL)


# ---------- FCFF builder (PROJECT_PLAN.md 5.1) ----------
# FCFF = EBIT x (1 - tax) + D&A - capex - increase in NWC. Other income is not an input.
# Base revenue 1000; growth 10% then 20%; EBIT margin 20% then 25%; tax 25%; D&A 4%;
# capex 6%; NWC 10% of incremental revenue.
# Year 1: revenue 1000 x 1.10 = 1100; EBIT 1100 x 0.20 = 220; tax 220 x 0.25 = 55; NOPAT 165;
#         D&A 1100 x 0.04 = 44; capex 1100 x 0.06 = 66; NWC increase 0.10 x (1100-1000) = 10
#         FCFF = 165 + 44 - 66 - 10 = 133
# Year 2: revenue 1100 x 1.20 = 1320; EBIT 1320 x 0.25 = 330; tax 82.5; NOPAT 247.5;
#         D&A 52.8; capex 79.2; NWC increase 0.10 x 220 = 22
#         FCFF = 247.5 + 52.8 - 79.2 - 22 = 199.1
def test_fcff_builder_round_numbers():
    years = build_fcff(1000, revenue_growth=[0.10, 0.20], ebit_margin=[0.20, 0.25], tax_rate=0.25,
                       da_pct_revenue=0.04, capex_pct_revenue=0.06, nwc_pct_incremental_revenue=0.10)
    y1, y2 = years
    assert (y1.year, y1.revenue, y1.ebit, y1.taxes_on_ebit, y1.nopat) == pytest.approx((1, 1100, 220, 55, 165))
    assert (y1.da, y1.capex, y1.nwc_increase, y1.fcff) == pytest.approx((44, 66, 10, 133))
    assert (y2.year, y2.revenue, y2.ebit, y2.taxes_on_ebit, y2.nopat) == pytest.approx((2, 1320, 330, 82.5, 247.5))
    assert (y2.da, y2.capex, y2.nwc_increase, y2.fcff) == pytest.approx((52.8, 79.2, 22, 199.1))


# Shrinking revenue releases working capital (adds cash):
# base 1000, growth -10% -> revenue 900; EBIT 900 x 0.20 = 180; NOPAT 135; D&A 36; capex 54;
# NWC increase 0.10 x (900 - 1000) = -10;  FCFF = 135 + 36 - 54 - (-10) = 127
def test_fcff_builder_negative_growth_releases_nwc():
    (y1,) = build_fcff(1000, [-0.10], [0.20], 0.25, 0.04, 0.06, 0.10)
    assert y1.nwc_increase == pytest.approx(-10)
    assert y1.fcff == pytest.approx(127)


def test_fcff_builder_per_year_list_length_must_match():
    with pytest.raises(DCFError, match="ebit_margin"):
        build_fcff(1000, [0.1, 0.1, 0.1], [0.2, 0.2], 0.25, 0.04, 0.06, 0.10)


def test_fcff_builder_rejects_empty_and_bad_base():
    with pytest.raises(DCFError, match="empty"):
        build_fcff(1000, [], [], 0.25, 0.04, 0.06, 0.10)
    with pytest.raises(DCFError, match="base"):
        build_fcff(0, [0.1], [0.2], 0.25, 0.04, 0.06, 0.10)


def test_toy_drivers_reproduce_scaled_toy_fcff():
    # Drivers used by the toy YAML fixture: base 1000, growth 10%, margin 20%, tax 25%,
    # D&A 5% = capex 5%, NWC 10% of incremental revenue.
    # Y1: rev 1100, NOPAT 220 x 0.75 = 165, NWC 10   -> FCFF 155
    # Y2: rev 1210, NOPAT 242 x 0.75 = 181.5, NWC 11 -> FCFF 170.5
    # Y3: rev 1331, NOPAT 266.2 x 0.75 = 199.65, NWC 12.1 -> FCFF 187.55
    # = 1.55 x (100, 110, 121), so the toy valuation scales by 1.55.
    years = build_fcff(1000, 0.10, 0.20, 0.25, 0.05, 0.05, 0.10, horizon=3)
    assert [y.fcff for y in years] == pytest.approx([155, 170.5, 187.55])


# ---------- WACC ----------
# Cost of equity = 7% + 0.9 x 6% = 7% + 5.4% = 12.4%
# With 20% debt, pre-tax cost of debt 9%, tax 25%: after-tax 9% x 0.75 = 6.75%
# WACC = 0.8 x 12.4% + 0.2 x 6.75% = 9.92% + 1.35% = 11.27%   (bc: .11270)
def test_wacc_with_debt():
    w = compute_wacc(risk_free_rate=0.07, beta=0.9, equity_risk_premium=0.06, debt_weight=0.2,
                     cost_of_debt_pre_tax=0.09, debt_tax_rate=0.25)
    assert w.cost_of_equity == pytest.approx(0.124, rel=REL)
    assert w.equity_weight == pytest.approx(0.8, rel=REL)
    assert w.cost_of_debt_after_tax == pytest.approx(0.0675, rel=REL)
    assert w.wacc == pytest.approx(0.1127, rel=REL)


def test_wacc_all_equity_equals_cost_of_equity():
    assert cost_of_equity(0.07, 1.0, 0.05) == pytest.approx(0.12, rel=REL)
    w = compute_wacc(0.07, 1.0, 0.05, debt_weight=0, cost_of_debt_pre_tax=0, debt_tax_rate=0)
    assert w.wacc == pytest.approx(0.12, rel=REL)


@pytest.mark.parametrize("weight", [-0.1, 1.0, 1.5])
def test_wacc_rejects_bad_debt_weight(weight):
    with pytest.raises(DCFError, match="debt_weight"):
        compute_wacc(0.07, 1.0, 0.05, weight, 0.09, 0.25)


# ---------- sensitivity grid ----------
# Toy firm at WACC 11%, g 3%:
#   PVs 100/1.11 = 90.090090090090, 110/1.11^2 = 89.278467656846, 121/1.11^3 = 88.474157137414
#   sum 267.842714884350; TV = 121 x 1.03 / 0.08 = 1557.875; PV TV = 1557.875/1.11^3 = 1139.104773144217
#   EV 1406.947488028567; equity +150 = 1556.947488028567; per share 155.694748802857  (bc)
# Toy firm at WACC 13%, g 5%: per share 150.915106899522  (bc, same method)
def test_sensitivity_grid_cells():
    g = sensitivity_grid(TOY_FCFF, wacc_values=[0.11, 0.12, 0.13], growth_values=[0.03, 0.04, 0.05],
                         bridge=toy_bridge())
    assert g.wacc_values == [0.11, 0.12, 0.13]
    assert g.growth_values == [0.03, 0.04, 0.05]
    assert g.value_per_share[0][0] == pytest.approx(155.694748802857, rel=1e-11)
    assert g.value_per_share[1][1] == pytest.approx(TOY_PER_SHARE, rel=REL)
    assert g.value_per_share[2][2] == pytest.approx(150.915106899522, rel=1e-11)


def test_sensitivity_grid_blank_where_growth_not_below_wacc():
    g = sensitivity_grid(TOY_FCFF, [0.04, 0.05], [0.04], toy_bridge())
    assert g.value_per_share[0][0] is None      # g = WACC: Gordon formula undefined
    assert g.value_per_share[1][0] is not None


# ---------- error cases ----------

@pytest.mark.parametrize("g", [0.12, 0.13])
def test_terminal_growth_not_below_wacc_raises(g):
    with pytest.raises(DCFError, match="terminal growth .* must be below WACC"):
        value_firm(TOY_FCFF, wacc=0.12, terminal_growth=g, bridge=toy_bridge())


@pytest.mark.parametrize("shares", [0, -10])
def test_non_positive_shares_rejected(shares):
    with pytest.raises(ValueError, match="diluted_shares"):
        toy_bridge(diluted_shares=shares)


def test_negative_bridge_item_rejected():
    with pytest.raises(ValueError, match="debt"):
        toy_bridge(debt=-1)


def test_empty_forecast_rejected():
    with pytest.raises(DCFError, match="empty"):
        value_firm([], 0.12, 0.04, toy_bridge())


@pytest.mark.parametrize("fcff", [[0, 0, 0], [100, 110, 0], [100, 110, -5]])
def test_zero_or_negative_final_year_fcff_rejected(fcff):
    # Gordon growth on a zero or negative final-year cash flow gives a meaningless terminal value.
    with pytest.raises(DCFError, match="final-year FCFF"):
        value_firm(fcff, 0.12, 0.04, toy_bridge())


def test_growth_equal_to_wacc_caught_despite_float_rounding():
    # 0.07 + 1.0 x 0.05 is 0.12000000000000001 in floating point; g = 0.12 must still be refused.
    wacc = 0.07 + 1.0 * 0.05
    assert wacc > 0.12
    with pytest.raises(DCFError, match="must be below WACC"):
        value_firm(TOY_FCFF, wacc, 0.12, toy_bridge())
