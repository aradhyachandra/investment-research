"""D1: expanded TCS facts from the FY26 annual report (data/manual/financials_tcs.csv).

Covers: the new CSV (all rows signed off by the author, with pages), the new metrics and
their plausibility bands, the load-time cross-foot checks, the SHARES unit, the new ratios
(sum and average operands), and that the router catalog picks the new metrics and ratios up
from config with no prompt change.

Expected ratio values are literals worked out by hand with `bc` (scale=15) from the figures
printed in the annual report, NOT by calling the code under test. Inputs (INR crore):
                                                 FY26      FY25    PDF page (printed)
    revenue_from_operations                    267021    255324    167 (197)
    other_income                                 4402      3962    167 (197)
    finance_costs                                1227       796    167 (197)
    depreciation_amortisation                    5560      5242    167 (197)
    profit_before_exceptional_items_and_tax     70013     65331    167 (197)
    exceptional items: restructuring             1388         0    167 (197)  ("-" in FY25)
                       labour codes              2128         0    167 (197)
                       legal claim               1010         0    167 (197)
    profit_before_tax                           65487     65331    167 (197)
    tax_expense                                 16033     16534    167 (197)
    profit_after_tax                            49454     48797    167 (197)
    profit_attributable_to_owners               49210     48553    167 (197)
    total_equity                               108478     95771    166 (196)
    cash_from_operations                        52094     48908    172 (202)
    purchase_of_ppe                              3670      2917    172 (202)
    purchase_of_intangibles                       367       944    172 (202)
"""
import csv
import json

import pytest
import yaml

from conftest import COMPANY_CONFIG, HASHES_FILE, METRICS_CONFIG, REAL_SAMPLE_CSV, REPO
from erp.agent.router import build_catalog, router_messages, route_schema
from erp.agent.tools import ToolCall, ToolEnv, run_tool
from erp.config import ConfigError, load_context
from erp.db.load_facts import LoadError, create_db, load_rows, seed_reference_data
from erp.tools.facts import FactNotFoundError, get_financial_fact
from erp.tools.ratios import RATIOS_CONFIG, compute_ratio, load_ratios
from erp.units import conversion_factor
from test_agent_tools import DISPLAY
from test_dcf_run import TOY_YAML

MANUAL_CSV = REPO / "data" / "manual" / "financials_tcs.csv"
AR = "tcs_annual_report_FY26.pdf"
REL = 1e-9

NEW_METRICS = {
    "other_income", "finance_costs", "depreciation_amortisation",
    "profit_before_exceptional_items_and_tax", "exceptional_restructuring_expenses",
    "exceptional_labour_codes_impact", "exceptional_legal_claim_provision", "profit_before_tax",
    "tax_expense", "total_assets", "current_investments", "non_current_investments",
    "other_balances_with_banks", "lease_liabilities_current", "lease_liabilities_non_current",
    "non_controlling_interests", "equity_attributable_to_owners", "shares_outstanding", "cash_from_operations", "purchase_of_ppe",
    "purchase_of_intangibles",
}
NEW_RATIOS = {"operating_margin", "effective_tax_rate", "return_on_equity", "capex_to_revenue",
              "ocf_to_profit", "da_to_revenue"}


def _rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


# D4 added these metrics (lease note, cash-flow working-capital subtotals), also from the FY26 report;
# they are tested in tests/test_d4_history_checks.py.
D4_METRICS = {"interest_on_lease_liabilities", "depreciation_right_of_use_assets",
           "operating_profit_before_wc_changes", "cash_generated_from_operations"}


def manual_rows():
    """The D1 rows: everything read from the FY26 annual report for the D1 metrics. D3 added rows from
    the FY25 and FY24 reports to the same file (tests/test_d3_history.py); D4 added four metrics
    (tests/test_d4_history_checks.py)."""
    return [r for r in _rows(MANUAL_CSV) if r["source_doc"] == AR and r["metric_id"] not in D4_METRICS]


def manual_row(metric_id, period):
    for r in manual_rows():
        if r["metric_id"] == metric_id and r["period"] == period:
            return dict(r)
    raise KeyError((metric_id, period))


@pytest.fixture
def manual(conn, ctx):
    """In-memory DB with the whole manual CSV loaded (as the build does: llm_extracted)."""
    load_rows(conn, manual_rows(), ctx, entry_method="llm_extracted")
    return conn


# ---------- the CSV file ----------

def test_manual_csv_has_the_sample_columns_plus_verification():
    with open(MANUAL_CSV, newline="") as f:
        header = next(csv.reader(f))
    with open(REAL_SAMPLE_CSV, newline="") as f:
        sample_header = next(csv.reader(f))
    assert header == sample_header
    assert header[-2:] == ["verified_by", "verified_on"]


def test_signed_off_sample_rows_are_kept_with_their_sign_off():
    manual = {(r["metric_id"], r["period"]): r for r in manual_rows()}
    for r in _rows(REAL_SAMPLE_CSV):
        assert manual[(r["metric_id"], r["period"])] == r


def test_new_rows_are_claude_entries_signed_off_by_the_author_with_both_page_numbers():
    signed = {(r["metric_id"], r["period"]) for r in _rows(REAL_SAMPLE_CSV)}
    new = [r for r in manual_rows() if (r["metric_id"], r["period"]) not in signed]
    assert len(new) == 2 * len(NEW_METRICS)
    for r in new:
        assert r["entered_by"] == "Claude"
        assert r["verified_by"] == "Aradhya Chandra" and r["verified_on"] == "2026-10-08"   # D1 sign-off
        assert r["source_doc"] == AR and r["basis"] == "consolidated" and r["ticker"] == "TCS"
        # AR FY26: PDF 34-358 print page number = PDF index + 30 (config page_labels).
        assert int(r["source_page_label"]) == int(r["source_page"]) + 30, r


def test_every_new_metric_has_fy26_and_fy25():
    have = {(r["metric_id"], r["period"]) for r in manual_rows()}
    for m in NEW_METRICS:
        assert {(m, "FY26"), (m, "FY25")} <= have, m


def test_no_calculated_figure_is_stored_as_a_metric():
    metrics = yaml.safe_load(METRICS_CONFIG.read_text())["metrics"]
    for derived in ("ebit", "capex", "capex_total", "exceptional_items_total", "average_total_equity"):
        assert derived not in metrics


def test_sample_csv_and_fixture_are_unchanged():
    assert len(_rows(REAL_SAMPLE_CSV)) == 12
    assert len(_rows(REPO / "tests" / "fixtures" / "facts_unverified_fixture.csv")) == 12


# ---------- metrics config ----------

def test_new_metrics_are_defined_with_bands(ctx):
    for m in NEW_METRICS:
        assert m in ctx.metrics and m in ctx.bands
        assert len(" ".join(ctx.metrics[m]["definition"].split())) > 60, m


def test_shares_outstanding_is_a_point_in_time_share_count(ctx):
    m = ctx.metrics["shares_outstanding"]
    assert (m["unit_kind"], m["canonical_unit"], m["is_flow"]) == ("shares", "SHARES_CRORE", 0)


def test_cash_outflows_are_marked_as_stored_positive(ctx):
    for m in ("purchase_of_ppe", "purchase_of_intangibles"):
        assert ctx.metrics[m].get("sign") == "outflow_positive"


# ---------- loading the manual CSV ----------

def test_manual_csv_loads_cleanly_with_all_checks(conn, ctx):
    ids = load_rows(conn, manual_rows(), ctx, entry_method="llm_extracted")
    assert len(ids) == 12 + 2 * len(NEW_METRICS)
    unverified = conn.execute("SELECT COUNT(*) FROM fact WHERE verified_by IS NULL").fetchone()[0]
    assert unverified == 0                          # all signed off (2026-10-07 and 2026-10-08)


def test_manual_csv_loads_with_the_real_pdf_hashes_if_present(tmp_path):
    raw = REPO / "data" / "raw"
    if not (raw / AR).exists():
        pytest.skip("private PDFs not checked out")
    ctx = load_context(COMPANY_CONFIG, METRICS_CONFIG, HASHES_FILE, raw_dir=raw)
    c = create_db(":memory:")
    seed_reference_data(c, ctx)
    load_rows(c, manual_rows(), ctx, entry_method="llm_extracted")


@pytest.mark.parametrize("metric_id, period, value, page", [
    ("tax_expense", "FY26", 16033, 167),
    ("profit_before_tax", "FY25", 65331, 167),
    ("total_assets", "FY26", 182372, 166),
    ("lease_liabilities_non_current", "FY26", 9453, 166),     # PDF text layer prints " 9 453"
    ("exceptional_labour_codes_impact", "FY25", 0, 167),      # printed "-"
    ("cash_from_operations", "FY25", 48908, 172),
    ("purchase_of_intangibles", "FY26", 367, 172),
])
def test_spot_values_load_with_their_pages(manual, metric_id, period, value, page):
    f = get_financial_fact(manual, "TCS", metric_id, period)
    assert f.value == value and f.unit == "INR_CRORE" and f.source_page == page
    assert f.source_page_label == str(page + 30) and f.verified


def test_shares_outstanding_converted_to_crore(manual):
    f = get_financial_fact(manual, "TCS", "shares_outstanding", "FY26")
    assert f.reported_value == 3618087518 and f.reported_unit == "SHARES"
    assert f.value == pytest.approx(361.8087518, rel=REL) and f.unit == "SHARES_CRORE"
    assert (f.source_page, f.source_page_label) == (196, "226")


def test_shares_unit_conversion():
    assert conversion_factor("SHARES", "SHARES_CRORE") == pytest.approx(1e-7)


# ---------- cross-foot identities (config: cross_foot_checks) ----------

def test_identities_hold_on_the_printed_figures():
    # Hand arithmetic, both years:
    #   FY26: 70013 - 1388 - 2128 - 1010 = 65487 (PBT);  65487 - 16033 = 49454 (profit for the year)
    #   FY25: 65331 - 0 - 0 - 0 = 65331;                 65331 - 16534 = 48797
    v = {(r["metric_id"], r["period"]): float(r["reported_value"]) for r in manual_rows()}
    for p, pbt, pat in (("FY26", 65487, 49454), ("FY25", 65331, 48797)):
        parts = (v[("profit_before_exceptional_items_and_tax", p)] - v[("exceptional_restructuring_expenses", p)]
                 - v[("exceptional_labour_codes_impact", p)] - v[("exceptional_legal_claim_provision", p)])
        assert parts == v[("profit_before_tax", p)] == pbt
        assert v[("profit_before_tax", p)] - v[("tax_expense", p)] == v[("profit_after_tax", p)] == pat


def test_cross_foot_checks_are_configured(ctx):
    names = {c["name"] for c in ctx.cross_foot_checks}
    assert {"profit_before_tax", "profit_for_the_year"} <= names


def _corrupt(metric_id, period, value):
    rows = manual_rows()
    for r in rows:
        if r["metric_id"] == metric_id and r["period"] == period:
            r["reported_value"] = str(value)
    return rows


def test_wrong_profit_before_tax_is_rejected(conn, ctx):
    with pytest.raises(LoadError, match="profit_before_tax.*FY26"):
        load_rows(conn, _corrupt("profit_before_tax", "FY26", 65478), ctx, entry_method="llm_extracted")
    assert conn.execute("SELECT COUNT(*) FROM fact").fetchone()[0] == 0


def test_wrong_tax_expense_is_rejected(conn, ctx):
    with pytest.raises(LoadError, match="profit_for_the_year.*FY25"):
        load_rows(conn, _corrupt("tax_expense", "FY25", 16543), ctx, entry_method="llm_extracted")


def test_identity_within_printing_rounding_passes(conn, ctx):
    # 5 rounded terms (half a crore each) -> up to 2.5 crore of rounding slack; 1 crore off passes.
    load_rows(conn, _corrupt("profit_before_exceptional_items_and_tax", "FY26", 70014), ctx,
              entry_method="llm_extracted")


def test_identity_skipped_when_a_part_is_missing(conn, ctx):
    rows = [r for r in manual_rows() if not (r["metric_id"] == "tax_expense" and r["period"] == "FY26")]
    load_rows(conn, rows, ctx, entry_method="llm_extracted")


def test_negative_cash_outflow_is_rejected(conn, ctx):
    with pytest.raises(LoadError, match="purchase_of_ppe.*positive"):
        load_rows(conn, _corrupt("purchase_of_ppe", "FY26", -3670), ctx, entry_method="llm_extracted")


def test_bad_cross_foot_config_is_rejected(tmp_path):
    cfg = yaml.safe_load(COMPANY_CONFIG.read_text())
    cfg["cross_foot_checks"][0]["parts"][0]["metric"] = "no_such_metric"
    path = tmp_path / "tcs.yaml"
    path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ConfigError, match="no_such_metric"):
        load_context(path, METRICS_CONFIG, HASHES_FILE)


# ---------- the new ratios (hand arithmetic, bc scale=15) ----------

# operating_margin = EBIT / revenue x 100, EBIT = PBEIT - other income + finance costs
#   FY26: 70013 - 4402 + 1227 = 66838;  66838 / 267021 x 100 = 25.0309900719419
#   FY25: 65331 - 3962 + 796 = 62165;   62165 / 255324 x 100 = 24.3474957309144
# effective_tax_rate = tax / PBT x 100
#   FY26: 16033 / 65487 x 100 = 24.4827217615709;  FY25: 16534 / 65331 x 100 = 25.3080467159541
# return_on_equity = owners' profit / average total equity x 100
#   FY26: (107240 + 94756) / 2 = 100998;  49210 / 100998 x 100 = 48.72373710370502 (v2: shareholders' equity)
# capex_to_revenue = (PP&E + intangibles purchased) / revenue x 100
#   FY26: 3670 + 367 = 4037;  4037 / 267021 x 100 = 1.5118661079091
#   FY25: 2917 + 944 = 3861;  3861 / 255324 x 100 = 1.5121962682709
# ocf_to_profit = cash from operations / owners' profit x 100
#   FY26: 52094 / 49210 x 100 = 105.8605974395448;  FY25: 48908 / 48553 x 100 = 100.7311597635573
# da_to_revenue = D&A / revenue x 100
#   FY26: 5560 / 267021 x 100 = 2.0822332325921;  FY25: 5242 / 255324 x 100 = 2.0530776581911
@pytest.mark.parametrize("ratio_id, period, expected", [
    ("operating_margin", "FY26", 25.0309900719419),
    ("operating_margin", "FY25", 24.3474957309144),
    ("effective_tax_rate", "FY26", 24.4827217615709),
    ("effective_tax_rate", "FY25", 25.3080467159541),
    ("return_on_equity", "FY26", 48.72373710370502),
    ("capex_to_revenue", "FY26", 1.5118661079091),
    ("capex_to_revenue", "FY25", 1.5121962682709),
    ("ocf_to_profit", "FY26", 105.8605974395448),
    ("ocf_to_profit", "FY25", 100.7311597635573),
    ("da_to_revenue", "FY26", 2.0822332325921),
    ("da_to_revenue", "FY25", 2.0530776581911),
])
def test_new_ratio_matches_hand_calculation(manual, ratio_id, period, expected):
    r = compute_ratio(manual, "TCS", ratio_id, period)
    assert r.value == pytest.approx(expected, rel=REL)
    assert r.unit == "PERCENT"
    # Verified only if every input is; every input is now signed off.
    assert r.verified is True


def test_new_ratios_are_in_config():
    ratios = load_ratios(RATIOS_CONFIG, METRICS_CONFIG)
    assert NEW_RATIOS <= set(ratios)
    for rid in NEW_RATIOS:
        expected = "return_on_equity.v2" if rid == "return_on_equity" else f"{rid}.v1"
        assert ratios[rid]["formula_version"] == expected


def test_operating_margin_inputs_formula_and_ebit(manual):
    r = compute_ratio(manual, "TCS", "operating_margin", "FY26")
    assert [(i.role, i.fact.metric_id) for i in r.inputs] == [
        ("numerator (+)", "profit_before_exceptional_items_and_tax"),
        ("numerator (-)", "other_income"),
        ("numerator (+)", "finance_costs"),
        ("denominator", "revenue_from_operations"),
    ]
    assert r.formula == ("(profit_before_exceptional_items_and_tax[FY26] - other_income[FY26] "
                         "+ finance_costs[FY26]) / revenue_from_operations[FY26] * 100")
    assert r.numerator_label == "EBIT" and r.numerator_value == 66838
    assert r.denominator_value == 267021
    stored = json.loads(manual.execute("SELECT inputs_json FROM computed_metric WHERE computed_id = ?",
                                       (r.computed_id,)).fetchone()[0])
    assert stored["numerator_value"] == 66838 and len(stored["fact_ids"]) == 4


def test_return_on_equity_uses_the_average_of_two_year_ends(manual):
    r = compute_ratio(manual, "TCS", "return_on_equity", "FY26")
    assert [(i.role, i.fact.metric_id, i.fact.period_label) for i in r.inputs] == [
        ("numerator", "profit_attributable_to_owners", "FY26"),
        ("denominator (current year end)", "equity_attributable_to_owners", "FY26"),
        ("denominator (prior year end)", "equity_attributable_to_owners", "FY25"),
    ]
    assert r.denominator_value == 100998            # (107240 + 94756) / 2, PDF p.166
    assert "(equity_attributable_to_owners[FY26] + equity_attributable_to_owners[FY25]) / 2" in r.formula


def test_return_on_equity_fy25_needs_fy24_equity(manual):
    # Only FY26 and FY25 are loaded, so FY25 has no opening equity: refuse, never guess.
    with pytest.raises(FactNotFoundError, match="FY24"):
        compute_ratio(manual, "TCS", "return_on_equity", "FY25")


def test_existing_ratios_unchanged_on_the_manual_data(manual):
    # 49210 / 267021 x 100 (same as test_ratios.NET_MARGIN_FY26)
    assert compute_ratio(manual, "TCS", "net_margin", "FY26").value == pytest.approx(18.4292621179607, rel=REL)


def _write_ratios(tmp_path, mutate):
    cfg = yaml.safe_load(RATIOS_CONFIG.read_text())
    mutate(cfg["ratios"])
    path = tmp_path / "ratios.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


@pytest.mark.parametrize("mutate, match", [
    (lambda r: r["operating_margin"]["numerator"]["sum"][1].update(metric="ebit"), "ebit"),
    (lambda r: r["operating_margin"]["numerator"]["sum"][1].update(sign=2), "sign"),
    (lambda r: r["operating_margin"].update(numerator={"sum": [{"metric": "other_income", "sign": 1}]}), "two"),
    (lambda r: r["return_on_equity"].update(denominator={"average": "equity"}), "equity"),
    (lambda r: r["return_on_equity"].update(denominator={"median": "total_equity"}), "median"),
])
def test_bad_operand_config_is_rejected(tmp_path, mutate, match):
    with pytest.raises(ConfigError, match=match):
        load_ratios(_write_ratios(tmp_path, mutate), METRICS_CONFIG)


def test_composite_numerator_is_a_tool_number_the_verifier_can_check(manual):
    env = ToolEnv(conn=manual, ticker="TCS", display=DISPLAY, dcf_assumptions=TOY_YAML)
    res = run_tool(ToolCall(tool="compute_ratio", args={"ratio_id": "operating_margin", "period": "FY26"}), env)
    ebit = [n for n in res.numbers if n.number_id.endswith("#numerator")]
    assert len(ebit) == 1 and ebit[0].value == 66838 and ebit[0].display == "INR 66,838 crore"
    assert "EBIT" in ebit[0].label
    assert res.numbers[0].number_id.endswith("#value")       # the ratio itself stays first
    # Plain quotients add no extra number.
    res = run_tool(ToolCall(tool="compute_ratio", args={"ratio_id": "net_margin", "period": "FY26"}), env)
    assert not [n for n in res.numbers if n.number_id.endswith(("#numerator", "#denominator"))]


# ---------- router: new metrics and ratios come from config automatically ----------

def test_router_catalog_and_schema_include_the_new_items(manual):
    catalog = build_catalog(manual, "TCS", dcf_assumptions=TOY_YAML)
    assert NEW_METRICS <= set(catalog.metrics) and NEW_RATIOS <= set(catalog.ratios)
    item = route_schema(catalog, max_calls=4)["properties"]["calls"]["items"]["properties"]
    assert "tax_expense" in item["metric_id"]["enum"] and "operating_margin" in item["ratio_id"]["enum"]
    system = router_messages("TCS's tax expense in FY26", catalog)[0]["content"]
    assert "tax_expense: Tax expense" in system
    assert "operating_margin: Operating margin" in system


def test_tax_expense_question_reaches_the_tax_expense_fact(manual):
    # The M7.1 held-out miss: "tax expense" was substituted by profit_after_tax because no
    # tax metric existed. With tax_expense listed, a route naming it returns the printed figure.
    env = ToolEnv(conn=manual, ticker="TCS", display=DISPLAY, dcf_assumptions=TOY_YAML)
    res = run_tool(ToolCall(tool="get_financial_fact",
                            args={"metric_id": "tax_expense", "period": "FY26"}), env)
    assert res.numbers[0].display == "INR 16,033 crore"
    assert res.evidence[0].page == 167 and res.evidence[0].page_label == "197"
