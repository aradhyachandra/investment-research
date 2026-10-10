"""M2: compute_ratio, ratio definitions from config/ratios.yaml, computed_metric writes.

Expected values are literals worked out by hand from data/sample/facts_sample.csv (and
cross-checked with `bc`, scale=15), NOT by calling the code under test. Inputs (INR crore
unless stated):
    revenue_from_operations        FY26 267021   FY25 255324
    profit_attributable_to_owners  FY26  49210   FY25  48553   (rows added by the author in M2.1)
    eps_basic (INR/share)          FY26 136.01   FY25 134.19
"""
import json
import re

import pytest
import yaml

from conftest import METRICS_CONFIG, read_sample_rows, sample_row
from erp.config import ConfigError
from erp.db.load_facts import load_rows
from erp.periods import PeriodError
from erp.tools.facts import FactNotFoundError, get_financial_fact
from erp.tools.ratios import (
    RATIOS_CONFIG,
    RatioError,
    RatioResult,
    UnknownRatioError,
    compute_ratio,
    growth_percent,
    load_ratios,
    quotient,
)

REL = 1e-9

# ---------- expected values (hand arithmetic) ----------

# net_margin FY26 = profit attributable to owners / revenue x 100 = 49210 / 267021 x 100
#   check: 267021 x 0.184 = 49131.864; 49210 - 49131.864 = 78.136;
#          78.136 / 267021 = 0.000292621179...  -> 0.184292621179
#   = 18.4292621179607 %   (bc: 18.429262117960700)
NET_MARGIN_FY26 = 18.4292621179607

# net_margin FY25 = 48553 / 255324 x 100
#   check: 255324 x 0.19 = 48511.56; 48553 - 48511.56 = 41.44;
#          41.44 / 255324 = 0.000162303582...  -> 0.190162303582
#   = 19.0162303582898 %   (bc: 19.016230358289800)
NET_MARGIN_FY25 = 19.0162303582898

# revenue_growth_yoy FY26 = (267021 - 255324) / 255324 x 100 = 11697 / 255324 x 100
#   check: 255324 x 0.045 = 11489.58; 11697 - 11489.58 = 207.42;
#          207.42 / 255324 = 0.000812379564788 -> 0.045812379564788
#   = 4.5812379564788 %
REVENUE_GROWTH_FY26 = 4.5812379564788

# net_profit_growth_yoy FY26 = (49210 - 48553) / 48553 x 100 = 657 / 48553 x 100
#   check: 48553 x 0.0135 = 655.4655; 657 - 655.4655 = 1.5345;
#          1.5345 / 48553 = 0.0000316046382 -> 0.0135316046382
#   = 1.353160463823 %   (bc: 1.353160463823000)
NET_PROFIT_GROWTH_FY26 = 1.353160463823

# eps_growth_yoy FY26 = (136.01 - 134.19) / 134.19 x 100 = 1.82 / 134.19 x 100
#   check: 134.19 x 0.0135 = 1.811565; 1.82 - 1.811565 = 0.008435;
#          0.008435 / 134.19 = 0.0000628586332 -> 0.0135628586332
#   = 1.3562858633281 %
EPS_GROWTH_FY26 = 1.3562858633281


@pytest.mark.parametrize("ratio_id, period, expected", [
    ("net_margin", "FY26", NET_MARGIN_FY26),
    ("net_margin", "FY25", NET_MARGIN_FY25),
    ("revenue_growth_yoy", "FY26", REVENUE_GROWTH_FY26),
    ("net_profit_growth_yoy", "FY26", NET_PROFIT_GROWTH_FY26),
    ("eps_growth_yoy", "FY26", EPS_GROWTH_FY26),
])
def test_ratio_matches_hand_calculation(loaded, ratio_id, period, expected):
    r = compute_ratio(loaded, "TCS", ratio_id, period)
    assert isinstance(r, RatioResult)
    assert r.value == pytest.approx(expected, rel=REL)
    assert r.unit == "PERCENT"
    assert r.ratio_id == ratio_id
    assert r.period_label == period
    assert r.basis == "consolidated"


def test_net_margin_inputs_and_formula(loaded):
    r = compute_ratio(loaded, "TCS", "net_margin", "FY26")
    pat = get_financial_fact(loaded, "TCS", "profit_attributable_to_owners", "FY26")
    rev = get_financial_fact(loaded, "TCS", "revenue_from_operations", "FY26")
    assert r.input_fact_ids == [pat.fact_id, rev.fact_id]
    assert [(i.role, i.fact.fact_id) for i in r.inputs] == [
        ("numerator", pat.fact_id), ("denominator", rev.fact_id)]
    assert "profit_attributable_to_owners[FY26]" in r.formula
    assert "revenue_from_operations[FY26]" in r.formula
    assert r.formula_version == "net_margin.v1"


def test_growth_uses_same_period_type_one_year_earlier(loaded):
    r = compute_ratio(loaded, "TCS", "revenue_growth_yoy", "FY26")
    cur = get_financial_fact(loaded, "TCS", "revenue_from_operations", "FY26")
    prior = get_financial_fact(loaded, "TCS", "revenue_from_operations", "FY25")
    assert r.input_fact_ids == [cur.fact_id, prior.fact_id]
    assert [i.role for i in r.inputs] == ["current", "prior_year"]
    assert "revenue_from_operations[FY25]" in r.formula


# ---------- computed_metric row ----------

def test_computed_metric_row_is_written(loaded):
    r = compute_ratio(loaded, "TCS", "net_margin", "FY26")
    row = loaded.execute(
        "SELECT c.ratio_id, p.label, c.value, c.unit, c.formula_version, c.inputs_json,"
        " c.code_version, c.computed_at FROM computed_metric c JOIN period p USING (period_id)"
        " WHERE c.computed_id = ?", (r.computed_id,)).fetchone()
    ratio_id, label, value, unit, formula_version, inputs_json, code_version, computed_at = row
    assert (ratio_id, label, unit, formula_version) == ("net_margin", "FY26", "PERCENT", "net_margin.v1")
    assert value == pytest.approx(NET_MARGIN_FY26, rel=REL)
    inputs = json.loads(inputs_json)
    assert inputs["fact_ids"] == r.input_fact_ids
    assert inputs["formula"] == r.formula
    assert inputs["basis"] == "consolidated"
    assert inputs["verified"] is False
    assert code_version == r.code_version
    assert computed_at == r.computed_at


def test_code_version_is_the_git_sha(loaded):
    r = compute_ratio(loaded, "TCS", "net_margin", "FY26")
    # This test runs inside the git checkout, so the SHA must be known (not 'unknown').
    assert re.fullmatch(r"[0-9a-f]{40}(-dirty)?", r.code_version), r.code_version


def test_each_call_writes_one_row(loaded):
    compute_ratio(loaded, "TCS", "net_margin", "FY26")
    compute_ratio(loaded, "TCS", "eps_growth_yoy", "FY26")
    assert loaded.execute("SELECT COUNT(*) FROM computed_metric").fetchone()[0] == 2


# ---------- verified status follows the inputs ----------

def _load_with_verified(conn, ctx, verified_keys):
    rows = read_sample_rows()
    for row in rows:
        if (row["metric_id"], row["period"]) in verified_keys:
            row["verified_by"] = "Test Reviewer"
            row["verified_on"] = "2026-10-04"
    load_rows(conn, rows, ctx, entry_method="llm_extracted")


def test_unverified_inputs_give_unverified_ratio(loaded):
    assert compute_ratio(loaded, "TCS", "net_margin", "FY26").verified is False


def test_all_inputs_verified_gives_verified_ratio(conn, ctx):
    _load_with_verified(conn, ctx, {("profit_attributable_to_owners", "FY26"), ("revenue_from_operations", "FY26")})
    r = compute_ratio(conn, "TCS", "net_margin", "FY26")
    assert r.verified is True
    assert all(i.fact.verified for i in r.inputs)


def test_one_unverified_input_makes_ratio_unverified(conn, ctx):
    # FY26 revenue verified, FY25 revenue not -> growth is unverified.
    _load_with_verified(conn, ctx, {("revenue_from_operations", "FY26")})
    r = compute_ratio(conn, "TCS", "revenue_growth_yoy", "FY26")
    assert r.verified is False
    assert [i.fact.verified for i in r.inputs] == [True, False]


# ---------- errors ----------

def _no_rows_written(conn):
    return conn.execute("SELECT COUNT(*) FROM computed_metric").fetchone()[0] == 0


def test_unknown_ratio_raises(loaded):
    with pytest.raises(UnknownRatioError, match="ev_to_ebitda"):
        compute_ratio(loaded, "TCS", "ev_to_ebitda", "FY26")
    assert _no_rows_written(loaded)


def test_unknown_period_label_raises(loaded):
    with pytest.raises(PeriodError):
        compute_ratio(loaded, "TCS", "net_margin", "CY25")
    assert _no_rows_written(loaded)


def test_missing_period_raises(loaded):
    # FY24 is a valid label, but no facts exist for it.
    with pytest.raises(FactNotFoundError, match="FY24"):
        compute_ratio(loaded, "TCS", "net_margin", "FY24")
    assert _no_rows_written(loaded)


def test_quarter_with_no_data_raises(loaded):
    with pytest.raises(FactNotFoundError, match="Q2 FY27"):
        compute_ratio(loaded, "TCS", "net_margin", "Q2 FY27")


def test_missing_metric_raises(conn, ctx):
    # Load everything except FY26 profit attributable to owners.
    rows = [r for r in read_sample_rows()
            if not (r["metric_id"] == "profit_attributable_to_owners" and r["period"] == "FY26")]
    load_rows(conn, rows, ctx, entry_method="llm_extracted")
    with pytest.raises(FactNotFoundError, match="profit_attributable_to_owners"):
        compute_ratio(conn, "TCS", "net_margin", "FY26")
    with pytest.raises(FactNotFoundError, match="profit_attributable_to_owners"):
        compute_ratio(conn, "TCS", "net_profit_growth_yoy", "FY26")
    assert _no_rows_written(conn)


@pytest.mark.parametrize("ratio_id", ["revenue_growth_yoy", "net_profit_growth_yoy", "eps_growth_yoy"])
def test_growth_without_prior_year_fact_raises(loaded, ratio_id):
    # FY25 is the earliest year loaded, so FY25 growth has no FY24 base.
    with pytest.raises(FactNotFoundError, match="FY24"):
        compute_ratio(loaded, "TCS", ratio_id, "FY25")
    assert _no_rows_written(loaded)


def test_growth_with_prior_period_present_but_metric_missing_raises(conn, ctx):
    # FY25 period exists (other metrics loaded) but FY25 EPS is absent.
    rows = [r for r in read_sample_rows() if not (r["metric_id"] == "eps_basic" and r["period"] == "FY25")]
    load_rows(conn, rows, ctx, entry_method="llm_extracted")
    with pytest.raises(FactNotFoundError, match="eps_basic"):
        compute_ratio(conn, "TCS", "eps_growth_yoy", "FY26")


def test_wrong_basis_raises(loaded):
    with pytest.raises(FactNotFoundError, match="standalone"):
        compute_ratio(loaded, "TCS", "net_margin", "FY26", basis="standalone")


# ---------- the arithmetic helpers (toy numbers, not TCS figures) ----------

def test_quotient_and_growth_helpers():
    assert quotient(25, 200, 100) == 12.5          # 25 / 200 = 0.125 -> 12.5
    assert growth_percent(110, 100) == pytest.approx(10.0)   # (110 - 100) / 100 = 0.10 -> 10
    assert growth_percent(90, 100) == pytest.approx(-10.0)   # (90 - 100) / 100 = -0.10 -> -10


def test_zero_denominator_raises():
    with pytest.raises(RatioError, match="zero"):
        quotient(25, 0, 100)


@pytest.mark.parametrize("prior", [0, -50])
def test_growth_on_zero_or_negative_base_raises(prior):
    with pytest.raises(RatioError, match="prior"):
        growth_percent(100, prior)


# ---------- ratio definitions come from config ----------

def test_ratios_defined_in_config():
    ratios = load_ratios(RATIOS_CONFIG, METRICS_CONFIG)
    assert set(ratios) == {"net_margin", "revenue_growth_yoy", "net_profit_growth_yoy", "eps_growth_yoy",
                           # D1 (tests/test_d1_facts.py)
                           "operating_margin", "effective_tax_rate", "return_on_equity", "capex_to_revenue",
                           "ocf_to_profit", "da_to_revenue",
                           # D3 (tests/test_d3_history.py)
                           "revenue_cagr_3y"}
    assert ratios["net_margin"]["numerator"] == "profit_attributable_to_owners"
    assert ratios["net_profit_growth_yoy"]["metric"] == "profit_attributable_to_owners"
    assert ratios["eps_growth_yoy"]["metric"] == "eps_basic"


def test_pat_ratios_are_gone(loaded):
    for old in ("pat_margin", "pat_growth_yoy"):
        with pytest.raises(UnknownRatioError):
            compute_ratio(loaded, "TCS", old, "FY26")


def test_ratio_definitions_state_the_exceptional_items_basis():
    # Since D1 not every ratio is "after exceptional items" (operating margin is before them;
    # capex and D&A ratios are not affected), but every definition must say which.
    for ratio_id, r in load_ratios(RATIOS_CONFIG, METRICS_CONFIG).items():
        text = " ".join(r["definition"].split())
        assert re.search(r"Basis: [^.]*(after exceptional items|before exceptional items|"
                         r"not affected by exceptional items)", text), ratio_id
        assert "fact sheets exclude exceptional items" in text, ratio_id
    defs = {k: " ".join(r["definition"].split()) for k, r in load_ratios(RATIOS_CONFIG, METRICS_CONFIG).items()}
    for ratio_id in ("net_margin", "revenue_growth_yoy", "net_profit_growth_yoy", "eps_growth_yoy",
                     "effective_tax_rate", "return_on_equity"):
        assert "statutory, after exceptional items" in defs[ratio_id], ratio_id
    assert "Basis: before exceptional items" in defs["operating_margin"]


def _write_ratios(tmp_path, mutate):
    cfg = yaml.safe_load(RATIOS_CONFIG.read_text())
    mutate(cfg["ratios"])
    path = tmp_path / "ratios.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


def test_config_with_unknown_metric_is_rejected(tmp_path):
    path = _write_ratios(tmp_path, lambda r: r["net_margin"].update(numerator="net_profit"))
    with pytest.raises(ConfigError, match="net_profit"):
        load_ratios(path, METRICS_CONFIG)


def test_config_with_unknown_kind_is_rejected(tmp_path):
    path = _write_ratios(tmp_path, lambda r: r["net_margin"].update(kind="moving_average"))
    with pytest.raises(ConfigError, match="kind"):
        load_ratios(path, METRICS_CONFIG)


def test_config_missing_field_is_rejected(tmp_path):
    path = _write_ratios(tmp_path, lambda r: r["revenue_growth_yoy"].pop("formula_version"))
    with pytest.raises(ConfigError, match="formula_version"):
        load_ratios(path, METRICS_CONFIG)


def test_ratio_config_is_used_at_run_time(loaded, tmp_path):
    # Swapping numerator and denominator in config changes the result: proof the
    # definition is read from YAML, not hard-coded.
    # 267021 / 49210 x 100: 49210 x 5.4 = 265734; 267021 - 265734 = 1287;
    # 1287 / 49210 = 0.0261532209... -> 5.4261532209 -> 542.61532209 %
    # (bc, scale=15: 542.615322089006)
    def swap(r):
        r["net_margin"]["numerator"], r["net_margin"]["denominator"] = (
            r["net_margin"]["denominator"], r["net_margin"]["numerator"])
    path = _write_ratios(tmp_path, swap)
    r = compute_ratio(loaded, "TCS", "net_margin", "FY26", ratios_config=path)
    assert r.value == pytest.approx(542.615322089006, rel=REL)
