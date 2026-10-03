"""M3: run_dcf end to end on the TOY fixture, writing a dcf_run row.

TOY NUMBERS ONLY (tests/fixtures/dcf_toy_assumptions.yaml). Not TCS, not real.
The golden test against the author's hand-built spreadsheet comes later (P0.3).

Expected values: hand arithmetic, cross-checked with `bc -l` (scale=20).

Base scenario. Drivers give FCFF 155, 170.5, 187.55 (see test_dcf_engine.py), i.e. 1.55 x the
plan's toy series 100, 110, 121. WACC = 7% + 1.0 x 5% = 12% (all equity); g = 4%.
  EV = 1.55 x 1382.732780612244897946 = 2143.235809948979591817
  equity = 2143.235809948979591817 + 200 - 50 = 2293.235809948979591817
  per share = 229.323580994897959182
  TV share of EV unchanged by scaling = 0.809722851377506898

Bear scenario. Growth 10%, 5%, 5%; beta 1.2 -> WACC = 7% + 1.2 x 5% = 13%.
  Revenue 1100, 1155, 1212.75
  Y1 FCFF 155
  Y2 EBIT 231,     NOPAT 173.25,   NWC 0.1 x 55    = 5.5   -> FCFF 167.75
  Y3 EBIT 242.55,  NOPAT 181.9125, NWC 0.1 x 57.75 = 5.775 -> FCFF 176.1375
  DF 1/1.13 = 0.884955752212389381, 0.783146683373795912, 0.693050162277695497
  PVs 137.168141592920353982 + 131.372856135954264233 + 122.072122958187590659
      = 390.613120687062208874
  TV = 176.1375 x 1.04 / 0.09 = 2035.366666666666666667; PV TV = 1410.611198627945492062
  EV = 1801.224319315007700936; equity +150 = 1951.224319315007700936
  per share = 195.122431931500770094;  TV share = 0.783140213854313552
"""
import json
from pathlib import Path

import pytest
import yaml

from erp.db.load_facts import create_db
from erp.dcf.assumptions import AssumptionError
from erp.dcf.run import DCFCheckError, DCFResult, run_dcf

TOY_YAML = Path(__file__).parent / "fixtures" / "dcf_toy_assumptions.yaml"
REL = 1e-9


@pytest.fixture
def db():
    c = create_db(":memory:")
    c.execute("INSERT INTO company (ticker_nse, name) VALUES ('TOY', 'Toy company (test fixture, not real)')")
    yield c
    c.close()


def write(tmp_path, data) -> Path:
    p = tmp_path / "assumptions.yaml"
    p.write_text(yaml.safe_dump(data, sort_keys=False))
    return p


def toy_data():
    with open(TOY_YAML) as f:
        return yaml.safe_load(f)


def test_run_base_scenario(db):
    r = run_dcf(db, "TOY", "base", assumptions_path=TOY_YAML)
    assert isinstance(r, DCFResult)
    assert [y.fcff for y in r.fcff_build] == pytest.approx([155, 170.5, 187.55], rel=REL)
    assert r.wacc_build.cost_of_equity == pytest.approx(0.12, rel=REL)
    assert r.wacc_build.wacc == pytest.approx(0.12, rel=REL)
    assert r.valuation.enterprise_value == pytest.approx(2143.235809948979591817, rel=REL)
    assert r.valuation.equity_value == pytest.approx(2293.235809948979591817, rel=REL)
    assert r.valuation.value_per_share == pytest.approx(229.323580994897959182, rel=REL)
    assert r.valuation.tv_share_of_ev == pytest.approx(0.809722851377506898, rel=REL)
    assert r.per_share_unit == "INR_PER_SHARE"
    assert {c.check_id: c.status for c in r.checks} == {
        "required_inputs_present": "pass",
        "terminal_growth_below_wacc": "pass",
        "terminal_growth_below_risk_free": "pass",
        "tv_share_of_ev_in_band": "pass",
    }
    assert "not investment advice" in r.disclaimer.lower()


def test_run_bear_scenario(db):
    r = run_dcf(db, "TOY", "bear", assumptions_path=TOY_YAML)
    assert [y.fcff for y in r.fcff_build] == pytest.approx([155, 167.75, 176.1375], rel=REL)
    assert r.wacc_build.wacc == pytest.approx(0.13, rel=REL)
    assert r.valuation.pv_fcff == pytest.approx(
        [137.168141592920353982, 131.372856135954264233, 122.072122958187590659], rel=REL)
    assert r.valuation.terminal_value == pytest.approx(2035.366666666666666667, rel=REL)
    assert r.valuation.enterprise_value == pytest.approx(1801.224319315007700936, rel=REL)
    assert r.valuation.value_per_share == pytest.approx(195.122431931500770094, rel=REL)
    assert r.valuation.tv_share_of_ev == pytest.approx(0.783140213854313552, rel=REL)


def test_run_writes_dcf_run_row(db):
    r = run_dcf(db, "TOY", "base", assumptions_path=TOY_YAML)
    row = db.execute("SELECT * FROM dcf_run WHERE run_id = ?", (r.run_id,)).fetchone()
    cols = [d[0] for d in db.execute("SELECT * FROM dcf_run").description]
    row = dict(zip(cols, row))
    assert row["scenario_name"] == "base"
    assert row["valuation_date"] == "2026-03-31"
    assert row["code_version"] == r.code_version and row["code_version"]

    assumptions = json.loads(row["assumptions_json"])
    assert assumptions["yaml_text"] == TOY_YAML.read_text()           # full copy of the YAML used
    assert assumptions["resolved"]["beta"] == {
        "value": 1.0, "rationale": "Toy: market beta, so cost of equity = 7% + 1.0 x 5% = 12%.",
        "source": "Toy test fixture", "defined_in": "shared"}

    outputs = json.loads(row["outputs_json"])
    assert outputs["valuation"]["value_per_share"] == pytest.approx(229.323580994897959182, rel=REL)
    assert outputs["valuation"]["discount_factors"] == pytest.approx(
        [0.892857142857142857, 0.797193877551020408, 0.711780247813411079], rel=REL)
    assert len(outputs["fcff_build"]) == 3
    assert "sensitivity" in outputs

    checks = json.loads(row["checks_json"])
    assert {c["check_id"] for c in checks} == {"required_inputs_present", "terminal_growth_below_wacc",
                                              "terminal_growth_below_risk_free", "tv_share_of_ev_in_band"}


def test_sensitivity_grid_centre_is_the_scenario(db):
    r = run_dcf(db, "TOY", "base", assumptions_path=TOY_YAML)
    g = r.sensitivity
    i, j = g.wacc_values.index(pytest.approx(0.12)), g.growth_values.index(pytest.approx(0.04))
    assert g.value_per_share[i][j] == pytest.approx(r.valuation.value_per_share, rel=REL)


def test_no_market_price_anywhere(db):
    r = run_dcf(db, "TOY", "base", assumptions_path=TOY_YAML)
    text = r.model_dump_json().lower()
    for word in ("market_price", "target", "undervalued", "overvalued", "upside", "buy", "sell"):
        assert word not in text


# ---------- refusals ----------

def test_growth_not_below_wacc_refuses_and_writes_nothing(db, tmp_path):
    data = toy_data()
    data["shared"]["terminal_growth"]["value"] = 0.12
    with pytest.raises(DCFCheckError, match="terminal_growth_below_wacc"):
        run_dcf(db, "TOY", "base", assumptions_path=write(tmp_path, data))
    assert db.execute("SELECT COUNT(*) FROM dcf_run").fetchone()[0] == 0


def test_growth_above_risk_free_runs_but_check_fails(db, tmp_path):
    # g 8% < WACC 12% (valid maths) but > risk-free 7%: stored as a failed, non-blocking check.
    data = toy_data()
    data["shared"]["terminal_growth"]["value"] = 0.08
    r = run_dcf(db, "TOY", "base", assumptions_path=write(tmp_path, data))
    status = {c.check_id: c.status for c in r.checks}
    assert status["terminal_growth_below_risk_free"] == "fail"
    assert r.all_checks_passed is False


def test_missing_rationale_refuses(db, tmp_path):
    data = toy_data()
    data["shared"]["terminal_growth"]["rationale"] = ""
    with pytest.raises(AssumptionError, match="terminal_growth.*rationale"):
        run_dcf(db, "TOY", "base", assumptions_path=write(tmp_path, data))
    assert db.execute("SELECT COUNT(*) FROM dcf_run").fetchone()[0] == 0


def test_missing_input_refuses(db, tmp_path):
    data = toy_data()
    del data["shared"]["debt"]
    with pytest.raises(DCFCheckError, match="required_inputs_present.*debt"):
        run_dcf(db, "TOY", "base", assumptions_path=write(tmp_path, data))


def test_ticker_mismatch_refuses(db):
    with pytest.raises(AssumptionError, match="TOY.*TCS"):
        run_dcf(db, "TCS", "base", assumptions_path=TOY_YAML)


def test_default_path_missing_gives_clear_error(db, tmp_path, monkeypatch):
    import erp.dcf.run as run_mod
    monkeypatch.setattr(run_mod, "DEFAULT_ASSUMPTIONS", tmp_path / "dcf_inputs.yaml")
    with pytest.raises(AssumptionError, match="not found"):
        run_dcf(db, "TOY", "base")
