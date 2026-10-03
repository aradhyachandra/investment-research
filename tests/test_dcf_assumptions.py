"""M3: assumptions loader (value + rationale + source for every assumption) and sanity checks.

Uses the TOY fixture tests/fixtures/dcf_toy_assumptions.yaml. Not TCS, not real.
"""
import copy
from pathlib import Path

import pytest
import yaml

from erp.dcf.assumptions import REQUIRED_ASSUMPTIONS, AssumptionError, load_scenario
from erp.dcf.checks import (
    check_required_inputs,
    check_terminal_growth_below_risk_free,
    check_terminal_growth_below_wacc,
    check_tv_share,
)

TOY_YAML = Path(__file__).parent / "fixtures" / "dcf_toy_assumptions.yaml"


@pytest.fixture
def toy():
    with open(TOY_YAML) as f:
        return yaml.safe_load(f)


def write(tmp_path, data) -> Path:
    p = tmp_path / "assumptions.yaml"
    p.write_text(yaml.safe_dump(data, sort_keys=False))
    return p


# ---------- loading ----------

def test_toy_base_scenario_loads():
    s = load_scenario(TOY_YAML, "base")
    assert s.ticker == "TOY"
    assert s.scenario == "base"
    assert s.units == {"money": "INR", "shares": "SHARES"}
    assert s.value("beta") == 1.0
    assert s.value("revenue_growth") == [0.10, 0.10, 0.10]      # scalar expanded to one per year
    assert s.assumptions["beta"].defined_in == "shared"
    assert s.assumptions["beta"].source == "Toy test fixture"


def test_scenario_overrides_shared():
    s = load_scenario(TOY_YAML, "bear")
    assert s.value("beta") == 1.2
    assert s.assumptions["beta"].defined_in == "scenario:bear"
    assert s.value("revenue_growth") == [0.10, 0.05, 0.05]
    assert s.value("ebit_margin") == [0.20, 0.20, 0.20]        # still from shared


def test_unknown_scenario(toy):
    with pytest.raises(AssumptionError, match="unknown scenario 'bull'.*base.*bear"):
        load_scenario(TOY_YAML, "bull")


def test_missing_file(tmp_path):
    with pytest.raises(AssumptionError, match="not found"):
        load_scenario(tmp_path / "nope.yaml", "base")


# ---------- refusal: rationale / source ----------

@pytest.mark.parametrize("field", ["rationale", "source"])
@pytest.mark.parametrize("bad", ["delete", "", "   ", None])
def test_missing_or_empty_provenance_refuses(tmp_path, toy, field, bad):
    if bad == "delete":
        del toy["shared"]["beta"][field]
    else:
        toy["shared"]["beta"][field] = bad
    with pytest.raises(AssumptionError, match=f"'beta' \\(shared\\).*{field}.*[Rr]efusing to run"):
        load_scenario(write(tmp_path, toy), "base")


def test_missing_rationale_in_other_scenario_still_refuses(tmp_path, toy):
    # The whole file must be complete, not just the scenario being run.
    toy["scenarios"]["bear"]["beta"]["rationale"] = ""
    with pytest.raises(AssumptionError, match=r"'beta' \(scenario 'bear'\).*rationale"):
        load_scenario(write(tmp_path, toy), "base")


def test_bare_number_without_block_refuses(tmp_path, toy):
    toy["shared"]["beta"] = 1.0
    with pytest.raises(AssumptionError, match="'beta'.*value, rationale and source"):
        load_scenario(write(tmp_path, toy), "base")


def test_unknown_assumption_name_refuses(tmp_path, toy):
    toy["shared"]["betta"] = copy.deepcopy(toy["shared"]["beta"])
    with pytest.raises(AssumptionError, match="unknown assumption 'betta'"):
        load_scenario(write(tmp_path, toy), "base")


# ---------- value checks ----------

def test_percent_written_as_whole_number_refuses(tmp_path, toy):
    toy["shared"]["risk_free_rate"]["value"] = 7
    with pytest.raises(AssumptionError, match="risk_free_rate.*decimal"):
        load_scenario(write(tmp_path, toy), "base")


def test_per_year_list_wrong_length_refuses(tmp_path, toy):
    toy["shared"]["ebit_margin"]["value"] = [0.2, 0.2]
    with pytest.raises(AssumptionError, match="ebit_margin.*3"):
        load_scenario(write(tmp_path, toy), "base")


@pytest.mark.parametrize("shares", [0, -10])
def test_non_positive_shares_refuses(tmp_path, toy, shares):
    toy["shared"]["diluted_shares"]["value"] = shares
    with pytest.raises(AssumptionError, match="diluted_shares.*greater than 0"):
        load_scenario(write(tmp_path, toy), "base")


def test_zero_horizon_refuses(tmp_path, toy):
    toy["shared"]["forecast_horizon_years"]["value"] = 0
    with pytest.raises(AssumptionError, match="forecast_horizon_years"):
        load_scenario(write(tmp_path, toy), "base")


def test_unknown_unit_refuses(tmp_path, toy):
    toy["units"]["money"] = "USD"
    with pytest.raises(AssumptionError, match="money unit 'USD'"):
        load_scenario(write(tmp_path, toy), "base")


def test_missing_assumption_loads_but_check_fails(tmp_path, toy):
    # Missing inputs are reported by the 'required inputs present' check (run_dcf then refuses).
    del toy["shared"]["minority_interest"]
    s = load_scenario(write(tmp_path, toy), "base")
    c = check_required_inputs(s)
    assert c.status == "fail" and c.blocking
    assert "minority_interest" in c.detail


def test_required_list_covers_plan_5_2():
    for name in ("valuation_date", "forecast_horizon_years", "revenue_growth", "ebit_margin", "tax_rate",
                 "da_pct_revenue", "capex_pct_revenue", "nwc_pct_incremental_revenue", "risk_free_rate",
                 "equity_risk_premium", "beta", "cost_of_debt_pre_tax", "debt_weight", "terminal_growth",
                 "lease_liabilities", "diluted_shares"):
        assert name in REQUIRED_ASSUMPTIONS


# ---------- sanity checks (PROJECT_PLAN.md 5.3) ----------

def test_required_inputs_check_passes_on_toy():
    c = check_required_inputs(load_scenario(TOY_YAML, "base"))
    assert c.status == "pass"


@pytest.mark.parametrize("g, status", [(0.04, "pass"), (0.12, "fail"), (0.13, "fail")])
def test_growth_below_wacc_check(g, status):
    c = check_terminal_growth_below_wacc(g, 0.12)
    assert c.status == status
    assert c.blocking


@pytest.mark.parametrize("g, status", [(0.04, "pass"), (0.07, "fail"), (0.08, "fail")])
def test_growth_below_risk_free_check(g, status):
    c = check_terminal_growth_below_risk_free(g, 0.07)
    assert c.status == status
    assert not c.blocking


@pytest.mark.parametrize("share, status", [(0.81, "pass"), (0.90, "warn"), (0.30, "warn"), (None, "fail")])
def test_tv_share_band_check(share, status):
    c = check_tv_share(share, band_min=0.5, band_max=0.85)
    assert c.status == status
