"""D4: the DCF's operating assumptions next to TCS's own record, FY23-FY26.

Each operating assumption in data/manual/dcf_inputs.yaml is shown beside the same quantity computed
from verified facts, with the DCF's own definition:

  revenue_growth              (revenue[t] - revenue[t-1]) / revenue[t-1]; plus the FY23-FY26 CAGR
  ebit_margin                 (PBEIT - other income + finance costs - interest on lease liabilities)
                              / revenue. The DCF treats leases as an operating cost, so its EBIT keeps
                              lease interest as a cost (finance costs include it).
  tax_rate                    tax expense / profit before tax (effective rate). APPROXIMATE match: the
                              DCF applies the statutory rate to EBIT.
  da_pct_revenue              (D&A - depreciation on right-of-use assets) / revenue
  capex_pct_revenue           (purchase of PP&E + purchase of intangibles) / revenue
  nwc_pct_incremental_revenue (operating profit before working capital changes - cash generated from
                              operations) / (revenue[t] - revenue[t-1])

New facts (24 rows, entered by Claude, not yet verified). Figures read from the PDFs; text layer checked
against rendered page images. INR crore, consolidated.

                                      FY26 AR (PDF p.)      FY25 AR (PDF p.)      FY24 AR (PDF p.)
                                      FY26     FY25         FY25     FY24         FY24     FY23
  interest_on_lease_liabilities       778      631  (200)   631      518  (206)   518      492  (206)
  depreciation_right_of_use_assets   1866     1820  (200)  1820     1716  (205)  1716     1634  (206)
  operating_profit_before_wc_changes 68688    67853  (172) 67853    63709  (184) 63709    59148  (184)
  cash_generated_from_operations     66478    64494  (172) 64494    56827  (184) 56827    54931  (184)
  printed pages: FY26 AR 200 -> 230, 172 -> 202; FY25 AR 205 -> 203, 206 -> 204, 184 -> 182;
  FY24 AR 206 -> 206, 184 -> 184.

Expected history values: worked by hand with `bc -l` (scale=15) from the figures above and the D1/D3
facts (test_d3_history.py docstring), NOT by calling the code under test.

  ebit_margin   FY23 (56907-3449+779-492)/225458   = 0.238381428026506
                FY24 (62955-4422+778-518)/240893   = 0.244062716641828
                FY25 (65331-3962+796-631)/255324   = 0.241003587598502
                FY26 (70013-4402+1227-778)/267021  = 0.247396272203309
  revenue_growth FY24 0.068460644554639  FY25 0.059906265437351  FY26 0.045812379564788
                 CAGR FY23-FY26 (267021/225458)^(1/3) - 1 = 0.058018486193645
  tax_rate      FY23 14604/56907 = 0.256629237176445  FY24 15898/61997 = 0.256431762827233
                FY25 16534/65331 = 0.253080467159541  FY26 16033/65487 = 0.244827217615709
  da_pct        FY23 (5022-1634)/225458 = 0.015027189099521  FY24 (4985-1716)/240893 = 0.013570340358582
                FY25 (5242-1820)/255324 = 0.013402578684338  FY26 (5560-1866)/267021 = 0.013834117915819
  capex_pct     FY23 (2532+355)/225458 = 0.012805045729138   FY24 (2202+442)/240893 = 0.010975827442059
                FY25 (2917+944)/255324 = 0.015121962682709   FY26 (3670+367)/267021 = 0.015118661079091
  nwc_pct       FY24 (63709-56827)/15435 = 0.445869776482021  FY25 (67853-64494)/14431 = 0.232762802300602
                FY26 (68688-66478)/11697 = 0.188937334359237
  FY23 growth and FY23 nwc need FY22 revenue: not in the database, so n/a.

Expected check results with the tolerance in config/dcf.yaml (0: inside the observed min-max):
  base: all pass (revenue growth a flat 6%, inside 4.58%-6.85%; was warn at 7% before 2026-10-10)
  bear: revenue_growth warn (all below 4.58%), ebit_margin warn (23.5% < 23.84%), tax_rate warn (27% > 25.66%)
  bull: revenue_growth warn, ebit_margin warn (25.5% > 24.74%)
"""
import csv
import json

import pytest
import yaml

from conftest import REPO
from erp.agent.tools import ToolCall, ToolEnv, run_tool
from erp.db.load_facts import load_rows
from erp.dcf.history import (OPERATING_ASSUMPTIONS, DCFHistory, assumptions_vs_history,
                             load_history_config)
from erp.dcf.run import DCF_CONFIG, run_dcf
from erp.ingest.pdf_to_chunks import parse_page_labels
from erp.ui import dcf_view
from test_agent_tools import DISPLAY
from test_d3_history import MANUAL_CSV
from test_dcf_run import TOY_YAML
from test_ui import FOOTER, UI_CFG

AR26, AR25, AR24 = "tcs_annual_report_FY26.pdf", "tcs_annual_report_FY25.pdf", "tcs_annual_report_FY24.pdf"
TCS_YAML = REPO / "data" / "manual" / "dcf_inputs.yaml"
REL = 1e-12

D4_METRICS = {"interest_on_lease_liabilities", "depreciation_right_of_use_assets",
              "operating_profit_before_wc_changes", "cash_generated_from_operations"}

# (source doc, metric) -> {period: printed value}, and the PDF page (printed page)
PRINTED = {
    (AR26, "interest_on_lease_liabilities"): ({"FY26": 778, "FY25": 631}, (200, "230")),
    (AR26, "depreciation_right_of_use_assets"): ({"FY26": 1866, "FY25": 1820}, (200, "230")),
    (AR26, "operating_profit_before_wc_changes"): ({"FY26": 68688, "FY25": 67853}, (172, "202")),
    (AR26, "cash_generated_from_operations"): ({"FY26": 66478, "FY25": 64494}, (172, "202")),
    (AR25, "interest_on_lease_liabilities"): ({"FY25": 631, "FY24": 518}, (206, "204")),
    (AR25, "depreciation_right_of_use_assets"): ({"FY25": 1820, "FY24": 1716}, (205, "203")),
    (AR25, "operating_profit_before_wc_changes"): ({"FY25": 67853, "FY24": 63709}, (184, "182")),
    (AR25, "cash_generated_from_operations"): ({"FY25": 64494, "FY24": 56827}, (184, "182")),
    (AR24, "interest_on_lease_liabilities"): ({"FY24": 518, "FY23": 492}, (206, "206")),
    (AR24, "depreciation_right_of_use_assets"): ({"FY24": 1716, "FY23": 1634}, (206, "206")),
    (AR24, "operating_profit_before_wc_changes"): ({"FY24": 63709, "FY23": 59148}, (184, "184")),
    (AR24, "cash_generated_from_operations"): ({"FY24": 56827, "FY23": 54931}, (184, "184")),
}

PERIODS = ["FY23", "FY24", "FY25", "FY26"]
EXPECTED = {   # assumption -> {period: value or None}
    "revenue_growth": {"FY23": None, "FY24": 0.068460644554639, "FY25": 0.059906265437351,
                       "FY26": 0.045812379564788},
    "ebit_margin": {"FY23": 0.238381428026506, "FY24": 0.244062716641828, "FY25": 0.241003587598502,
                    "FY26": 0.247396272203309},
    "tax_rate": {"FY23": 0.256629237176445, "FY24": 0.256431762827233, "FY25": 0.253080467159541,
                 "FY26": 0.244827217615709},
    "da_pct_revenue": {"FY23": 0.015027189099521, "FY24": 0.013570340358582, "FY25": 0.013402578684338,
                       "FY26": 0.013834117915819},
    "capex_pct_revenue": {"FY23": 0.012805045729138, "FY24": 0.010975827442059, "FY25": 0.015121962682709,
                          "FY26": 0.015118661079091},
    "nwc_pct_incremental_revenue": {"FY23": None, "FY24": 0.445869776482021, "FY25": 0.232762802300602,
                                    "FY26": 0.188937334359237},
}
CAGR = 0.058018486193645
STATUS = {
    "base": {"revenue_growth": "pass", "ebit_margin": "pass", "tax_rate": "pass", "da_pct_revenue": "pass",
             "capex_pct_revenue": "pass", "nwc_pct_incremental_revenue": "pass"},
    "bear": {"revenue_growth": "warn", "ebit_margin": "warn", "tax_rate": "warn", "da_pct_revenue": "pass",
             "capex_pct_revenue": "pass", "nwc_pct_incremental_revenue": "pass"},
    "bull": {"revenue_growth": "warn", "ebit_margin": "warn", "tax_rate": "pass", "da_pct_revenue": "pass",
             "capex_pct_revenue": "pass", "nwc_pct_incremental_revenue": "pass"},
}

# Values per share and equity values BEFORE D4 (commit 880a647), exact floats. D4 must not move them.
# base re-pinned 2026-10-10: base revenue growth lowered to a flat 6% by the author (was 1914.8185156593645)
PINNED = {"base": (1880.5285611688391, 680391.6914407477),
          "bear": (1445.112168857655, 522854.230025379),
          "bull": (2351.6613052709554, 850851.6415164431)}
DCF_INPUTS_SHA256 = "20c1c1982dbbb1cbdbf1e6b6469827da584d12c5742b4ad1e442470032e78be7"


def all_rows():
    with open(MANUAL_CSV, newline="") as f:
        return list(csv.DictReader(f))


def d4_rows():
    return [r for r in all_rows() if r["metric_id"] in D4_METRICS]


@pytest.fixture
def full(conn, ctx):
    load_rows(conn, all_rows(), ctx, entry_method="llm_extracted")
    return conn


def rows_by_name(h: DCFHistory):
    return {r.assumption: r for r in h.rows}


def checks_by_name(h: DCFHistory):
    return {c.assumption: c for c in h.checks}


# ---------- the new facts ----------

def test_d4_rows_are_claude_entries_signed_off_with_both_pages(ctx):
    rows = d4_rows()
    assert len(rows) == 24
    for r in rows:
        assert r["entered_by"] == "Claude", r
        assert r["verified_by"] == "Aradhya Chandra" and r["verified_on"] == "2026-10-10", r   # D4 sign-off
        assert r["ticker"] == "TCS" and r["basis"] == "consolidated" and r["reported_unit"] == "INR_CRORE"
        labels = parse_page_labels(ctx.sources[r["source_doc"]]["page_labels"])
        page = int(r["source_page"])
        assert r["source_page_label"] == labels[page][0], r
        assert (page, r["source_page_label"]) == PRINTED[(r["source_doc"], r["metric_id"])][1], r


def test_d4_rows_hold_the_printed_figures():
    got = {}
    for r in d4_rows():
        got.setdefault((r["source_doc"], r["metric_id"]), {})[r["period"]] = float(r["reported_value"])
    assert got == {k: {p: float(v) for p, v in vals.items()} for k, (vals, _) in PRINTED.items()}


def test_new_metrics_are_defined_with_bands(ctx):
    metrics = yaml.safe_load((REPO / "config" / "metrics.yaml").read_text())["metrics"]
    company = yaml.safe_load((REPO / "config" / "companies" / "tcs.yaml").read_text())
    for m in D4_METRICS:
        assert metrics[m]["canonical_unit"] == "INR_CRORE" and metrics[m]["is_flow"] == 1
        assert metrics[m]["definition"].strip()
        assert m in company["plausibility_bands"]


def test_whole_csv_loads_and_comparatives_agree(full):
    # The loader compares every figure printed in two reports; a disagreement would stop the load.
    n = full.execute("SELECT COUNT(*) FROM fact f JOIN metric m USING (metric_id) WHERE m.metric_id IN "
                     f"({','.join('?' * len(D4_METRICS))})", sorted(D4_METRICS)).fetchone()[0]
    assert n == 24


# ---------- history: same definitions as the DCF ----------

def test_history_values_match_hand_arithmetic(full):
    h = assumptions_vs_history(full, "TCS", "base", TCS_YAML)
    assert h.periods == PERIODS
    rows = rows_by_name(h)
    assert set(rows) == set(OPERATING_ASSUMPTIONS)
    for name, expected in EXPECTED.items():
        got = {y.period: y.value for y in rows[name].years}
        assert list(got) == PERIODS, name
        for p, v in expected.items():
            if v is None:
                assert got[p] is None, (name, p)
            else:
                assert got[p] == pytest.approx(v, rel=REL), (name, p)


def test_missing_years_say_why(full):
    rows = rows_by_name(assumptions_vs_history(full, "TCS", "base", TCS_YAML))
    for name in ("revenue_growth", "nwc_pct_incremental_revenue"):
        fy23 = rows[name].years[0]
        assert fy23.value is None and "FY22" in fy23.missing


def test_range_and_average(full):
    rows = rows_by_name(assumptions_vs_history(full, "TCS", "base", TCS_YAML))
    for name, expected in EXPECTED.items():
        vals = [v for v in expected.values() if v is not None]
        r = rows[name]
        assert r.min == pytest.approx(min(vals), rel=REL)
        assert r.max == pytest.approx(max(vals), rel=REL)
        assert r.average == pytest.approx(sum(vals) / len(vals), rel=REL)


def test_revenue_cagr(full):
    r = rows_by_name(assumptions_vs_history(full, "TCS", "base", TCS_YAML))["revenue_growth"]
    assert r.cagr.value == pytest.approx(CAGR, rel=REL)
    assert r.cagr.period == "FY23-FY26"


def test_fy26_history_reproduces_the_assumption_files_own_fy26_figures(full):
    """The YAML rationales derive FY26 figures by hand (EBIT 66,060 = 24.7%, D&A ex-ROU 1.38%, capex
    1.51%, NWC about 19%). Same definition -> the same FY26 numbers, rounded as the file rounds them."""
    rows = rows_by_name(assumptions_vs_history(full, "TCS", "base", TCS_YAML))
    fy26 = {n: r.years[-1].value for n, r in rows.items()}
    assert round(fy26["ebit_margin"], 3) == 0.247
    assert round(fy26["da_pct_revenue"], 4) == 0.0138
    assert round(fy26["capex_pct_revenue"], 4) == 0.0151
    assert round(fy26["nwc_pct_incremental_revenue"], 2) == 0.19


def test_ebit_deducts_lease_interest(full):
    r = rows_by_name(assumptions_vs_history(full, "TCS", "base", TCS_YAML))["ebit_margin"]
    fy26 = r.years[-1]
    assert "interest_on_lease_liabilities[FY26]" in fy26.formula
    assert fy26.numerator == 66060                       # 70013 - 4402 + 1227 - 778


def test_each_row_states_its_definition_and_match(full):
    rows = rows_by_name(assumptions_vs_history(full, "TCS", "base", TCS_YAML))
    for name, r in rows.items():
        assert r.definition.strip(), name
    assert {n: r.definition_match for n, r in rows.items()} == {
        "revenue_growth": "same", "ebit_margin": "same", "tax_rate": "approximate", "da_pct_revenue": "same",
        "capex_pct_revenue": "same", "nwc_pct_incremental_revenue": "same"}
    assert "statutory" in rows["tax_rate"].match_note


def test_rows_carry_their_facts_with_pages(full):
    rows = rows_by_name(assumptions_vs_history(full, "TCS", "base", TCS_YAML))
    ebit = rows["ebit_margin"]
    metrics = {(f.metric_id, f.period_label) for f in ebit.facts}
    assert ("interest_on_lease_liabilities", "FY23") in metrics and ("revenue_from_operations", "FY26") in metrics
    assert all(f.source_page for f in ebit.facts)
    # Each year's fact ids are among the row's facts.
    ids = {f.fact_id for f in ebit.facts}
    assert all(set(y.fact_ids) <= ids for y in ebit.years)
    # Primary source: the report for that year (FY26 lease interest from the FY26 report, PDF p.200).
    li26 = next(f for f in ebit.facts if (f.metric_id, f.period_label) == ("interest_on_lease_liabilities", "FY26"))
    assert li26.source_page == 200 and li26.source_page_label == "230"


def test_unverified_history_facts_are_listed(full):
    h = assumptions_vs_history(full, "TCS", "base", TCS_YAML)
    # All facts are signed off (D4 rows on 2026-10-10), so nothing is listed as unverified.
    assert h.unverified_fact_ids == []


# ---------- checks ----------

def test_tolerance_rule_lives_in_config_and_is_marked_to_verify():
    cfg = load_history_config(DCF_CONFIG)
    assert cfg["years"] == 4
    assert cfg["tolerance"]["default"] == 0.0
    text = DCF_CONFIG.read_text()
    assert "TO VERIFY" in text[text.index("history:"):]


@pytest.mark.parametrize("scenario", ["base", "bear", "bull"])
def test_check_status_per_scenario(full, scenario):
    h = assumptions_vs_history(full, "TCS", scenario, TCS_YAML)
    checks = checks_by_name(h)
    assert {n: c.status for n, c in checks.items()} == STATUS[scenario]
    assert all(c.blocking is False for c in checks.values())


def test_check_reports_which_forecast_years_are_outside(full):
    # Base is a flat 6% since 2026-10-10 (inside history); the bull case is above it in every year.
    base = checks_by_name(assumptions_vs_history(full, "TCS", "base", TCS_YAML))["revenue_growth"]
    assert base.outside == [] and base.status == "pass"
    c = checks_by_name(assumptions_vs_history(full, "TCS", "bull", TCS_YAML))["revenue_growth"]
    assert c.values == [0.09, 0.10, 0.10, 0.09, 0.08]
    assert c.outside == [1, 2, 3, 4, 5]              # all above the FY24-FY26 maximum of 6.85%
    assert "above" in c.detail


def test_wider_tolerance_from_config_changes_the_result(full, tmp_path):
    cfg = yaml.safe_load(DCF_CONFIG.read_text())
    cfg["history"]["tolerance"]["by_assumption"] = {"revenue_growth": 0.002}
    p = tmp_path / "dcf.yaml"
    p.write_text(yaml.safe_dump(cfg))
    c = checks_by_name(assumptions_vs_history(full, "TCS", "base", TCS_YAML, dcf_config=p))["revenue_growth"]
    assert c.status == "pass" and c.tolerance == 0.002


def test_assumption_without_a_history_definition_is_flagged(full, tmp_path):
    cfg = yaml.safe_load(DCF_CONFIG.read_text())
    del cfg["history"]["assumptions"]["nwc_pct_incremental_revenue"]
    p = tmp_path / "dcf.yaml"
    p.write_text(yaml.safe_dump(cfg))
    h = assumptions_vs_history(full, "TCS", "base", TCS_YAML, dcf_config=p)
    row = rows_by_name(h)["nwc_pct_incremental_revenue"]
    assert row.definition_match == "none" and all(y.value is None for y in row.years)
    c = checks_by_name(h)["nwc_pct_incremental_revenue"]
    assert c.status == "warn" and "cannot be matched" in c.detail


def test_no_history_in_the_database_warns_but_never_stops_a_run(db_toy):
    r = run_dcf(db_toy, "TOY", "base", assumptions_path=TOY_YAML)
    assert r.valuation.value_per_share == pytest.approx(229.323580994897959182, rel=1e-9)
    assert r.history.checks and all(c.status == "warn" for c in r.history.checks)
    assert r.history.note


@pytest.fixture
def db_toy():
    from erp.db.load_facts import create_db
    c = create_db(":memory:")
    c.execute("INSERT INTO company (ticker_nse, name) VALUES ('TOY', 'Toy company (test fixture, not real)')")
    yield c
    c.close()


# ---------- run record, tool output, results unchanged ----------

@pytest.mark.parametrize("scenario", ["base", "bear", "bull"])
def test_values_per_share_are_exactly_unchanged(full, scenario):
    per_share, equity = PINNED[scenario]
    r = run_dcf(full, "TCS", scenario)
    assert r.valuation.value_per_share == per_share          # exact, not approx
    assert r.valuation.equity_value == equity
    assert all(c.status == "pass" for c in r.checks)        # engine checks: history warnings are separate
    assert r.all_checks_passed is True


def test_assumptions_file_is_unchanged():
    import hashlib
    assert hashlib.sha256(TCS_YAML.read_bytes()).hexdigest() == DCF_INPUTS_SHA256


def test_dcf_run_record_stores_the_history_table(full):
    r = run_dcf(full, "TCS", "bear")
    row = full.execute("SELECT outputs_json, checks_json FROM dcf_run WHERE run_id = ?", (r.run_id,)).fetchone()
    out = json.loads(row[0])
    h = out["history"]
    assert h["periods"] == PERIODS
    ebit = next(x for x in h["rows"] if x["assumption"] == "ebit_margin")
    assert ebit["years"][-1]["value"] == pytest.approx(EXPECTED["ebit_margin"]["FY26"], rel=REL)
    assert {f["source_page"] for f in ebit["facts"]} >= {167, 200}
    assert {c["assumption"]: c["status"] for c in h["checks"]} == STATUS["bear"]
    # The engine's own checks list is unchanged in shape and content.
    assert [c["check_id"] for c in json.loads(row[1])] == ["required_inputs_present", "terminal_growth_below_wacc",
                                                           "terminal_growth_below_risk_free", "tv_share_of_ev_in_band"]


def test_tool_output_includes_the_history_table_and_notes_departures(full):
    env = ToolEnv(conn=full, ticker="TCS", display=DISPLAY, dcf_assumptions=TCS_YAML)
    res = run_tool(ToolCall(tool="run_dcf", args={"scenario": "bull"}), env)
    assert res.ok
    h = res.detail["history"]
    assert {r["assumption"] for r in h["rows"]} == set(OPERATING_ASSUMPTIONS)
    notes = [n for n in res.notes if n.startswith("History check")]
    assert len(notes) == 2 and any("revenue_growth" in n for n in notes) and any("ebit_margin" in n for n in notes)
    # Notes carry no figures (the verifier only accepts figures that are tool numbers).
    assert not any(ch.isdigit() for n in notes for ch in n.replace("FY23", "").replace("FY26", ""))
    # No verdict language.
    text = " ".join(notes + [c["detail"] for c in h["checks"]]).lower()
    for word in ("undervalued", "overvalued", "buy", "sell", "target price", "cheap", "expensive"):
        assert word not in text


# ---------- UI: Assumptions vs history ----------

@pytest.fixture
def tcs_env(full):
    return ToolEnv(conn=full, ticker="TCS", display=DISPLAY, dcf_assumptions=TCS_YAML)


def test_dcf_tab_has_an_assumptions_vs_history_table(tcs_env):
    v = dcf_view.build_dcf_tab(tcs_env, ["bear", "base", "bull"], base="base", assumptions_file=TCS_YAML,
                               footer=FOOTER, labels=UI_CFG["dcf"].get("labels"))
    t = v.history
    assert t is not None and t.periods == PERIODS
    rows = {r.assumption: r for r in t.rows}
    assert list(rows) == list(OPERATING_ASSUMPTIONS)
    ebit = rows["ebit_margin"]
    assert list(ebit.scenario_values) == ["bear", "base", "bull"]
    assert ebit.scenario_values["base"] == "24.70%"
    assert ebit.years == {"FY23": "23.84%", "FY24": "24.41%", "FY25": "24.10%", "FY26": "24.74%"}
    assert ebit.range == "23.84% to 24.74% (average 24.27%)"
    assert ebit.status == {"bear": "warn", "base": "pass", "bull": "warn"}
    growth = rows["revenue_growth"]
    assert growth.scenario_values["base"] == "6.00%"           # same value every year is shown once
    assert growth.years["FY23"] == "n/a"
    assert "5.80%" in growth.note                    # CAGR shown with the row
    # Page chips for the facts used.
    assert ebit.chips and all(c.page_text for c in ebit.chips)
    assert any("PDF p.200" in c.page_text for c in ebit.chips)
    assert t.tolerance_rule and not t.unverified_fact_ids


def test_dcf_tab_history_with_no_history_data(loaded, tmp_path):
    env = ToolEnv(conn=loaded, ticker="TCS", display=DISPLAY, dcf_assumptions=TOY_YAML)
    # The toy file is for ticker TOY; the tab reports the refusal and shows no table.
    v = dcf_view.build_dcf_tab(env, ["base"], base="base", assumptions_file=TOY_YAML, footer=FOOTER)
    assert v.history is None
