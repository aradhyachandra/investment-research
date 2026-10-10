"""D3: four years of history (FY23-FY26) from the FY25 and FY24 annual reports.

Covers: the two new source documents and periods in the company config (dates, standard, printed
page numbers), the new rows in data/manual/financials_tcs.csv (who entered them, pages, the
duplicate-fact policy: primary source = the report for that year, the other report's comparative
is a cross-check), the new exceptional-item metric whose line name changed, ratios over four years,
the 3-year CAGR ratio kind, the page-number check that now also reads the page header, search
results carrying their document period, and the snapshot trend.

Figures were read by Claude from the PDFs (text layer checked against rendered page images).
Consolidated, Ind AS, INR crore unless stated.

                                         FY26 AR      FY25 AR             FY24 AR
                                         FY25         FY25      FY24      FY24      FY23
  PDF page (printed): P&L                167 (197)    181 (179)           181 (181)
                      balance sheet      166 (196)    180 (178)           180 (180)
                      cash flows         172 (202)    184 (182)           184 (184)
                      note 8(m) shares   196 (226)    202 (200)           203 (203)
  revenue_from_operations                255324       255324    240893    240893    225458
  other_income                             3962         3962      4422      4422      3449
  finance_costs                             796          796       778       778       779
  depreciation_amortisation                5242         5242      4985      4985      5022
  profit_before_exceptional_items_and_tax 65331        65331     62955     62955     56907
  exceptional_legal_claim_settlement         -            0       958       958         0   ("-" printed)
  profit_before_tax                       65331        65331     61997     61997     56907
  tax_expense                             16534        16534     15898     15898     14604
  profit_after_tax                        48797        48797     46099     46099     42303
  profit_attributable_to_owners           48553        48553     45908     45908     42147
  eps_basic (INR)                        134.19       134.19    125.88    125.88    115.19
  total_equity                            95771        95771     91319     91319     91206
  equity_attributable_to_owners           94756        94756     90489     90489     90424
  non_controlling_interests                1015         1015       830       830       782
  cash_and_equivalents                     8342         8342      9016      9016      7123
  other_balances_with_banks                7121         7121      4270      4270      3909
  current_investments                     30689        30689     31481     31481     36897
  non_current_investments                   275          275       281       281       266
  total_assets                           159629       159629    146449    146449    143651
  lease_liabilities_non_current            7838         7838      6516      6516      6203
  lease_liabilities_current                1554         1554      1505      1505      1485
  cash_from_operations                    48908        48908     44338     44338     41965
  purchase_of_ppe                          2917         2917      2202      2202      2532
  purchase_of_intangibles                   944          944       442       442       355
  shares_outstanding (shares)        3618087518   3618087518 3618087518 3618087518 3659051373

The FY25 and FY24 reports print ONE exceptional line, "Settlement of legal claim" (note 20; the
Epic Systems case, FY24 report PDF p.231), not the FY26 report's three lines. So the three FY26
lines have no rows from these reports, and the settlement line is its own metric.

Expected ratio values are literals worked out by hand with `bc` (scale=15) from the figures above,
NOT by calling the code under test.
"""
import csv

import pytest
import yaml

from conftest import COMPANY_CONFIG, HASHES_FILE, METRICS_CONFIG, REPO
from erp.agent.tools import ToolCall, ToolEnv, run_tool
from erp.config import ConfigError, load_context, read_source_hashes
from erp.db.load_facts import LoadError, create_db, load_rows, seed_reference_data
from erp.ingest.pdf_to_chunks import _footer_numbers, _page_numbers, parse_page_labels
from erp.tools.facts import FactNotFoundError, get_financial_fact
from erp.tools.ratios import RATIOS_CONFIG, RatioError, compute_ratio, load_ratios
from test_agent_tools import DISPLAY
from test_dcf_run import TOY_YAML

MANUAL_CSV = REPO / "data" / "manual" / "financials_tcs.csv"
RAW = REPO / "data" / "raw"
AR26, AR25, AR24 = "tcs_annual_report_FY26.pdf", "tcs_annual_report_FY25.pdf", "tcs_annual_report_FY24.pdf"
REL = 1e-9

SHA = {AR25: "62ace414871697ed4c7ef34fd235fc3c89ed6208a30afe5ff2e49b5260fd8a57",
       AR24: "4368b3466c37a083d50bfc19580d993652172937d8b3f11e6660001ee2af607f"}

PAGES = {   # metric statement -> PDF page (printed) per document
    AR25: {"pl": (181, "179"), "bs": (180, "178"), "cf": (184, "182"), "shares": (202, "200")},
    AR24: {"pl": (181, "181"), "bs": (180, "180"), "cf": (184, "184"), "shares": (203, "203")},
}

# metric -> (statement, FY25 AR: FY25, FY24, FY24 AR: FY24, FY23), as printed
PRINTED = {
    "revenue_from_operations":                 ("pl", 255324, 240893, 240893, 225458),
    "other_income":                            ("pl", 3962, 4422, 4422, 3449),
    "finance_costs":                           ("pl", 796, 778, 778, 779),
    "depreciation_amortisation":               ("pl", 5242, 4985, 4985, 5022),
    "profit_before_exceptional_items_and_tax": ("pl", 65331, 62955, 62955, 56907),
    "exceptional_legal_claim_settlement":      ("pl", 0, 958, 958, 0),
    "profit_before_tax":                       ("pl", 65331, 61997, 61997, 56907),
    "tax_expense":                             ("pl", 16534, 15898, 15898, 14604),
    "profit_after_tax":                        ("pl", 48797, 46099, 46099, 42303),
    "profit_attributable_to_owners":           ("pl", 48553, 45908, 45908, 42147),
    "eps_basic":                               ("pl", 134.19, 125.88, 125.88, 115.19),
    "total_equity":                            ("bs", 95771, 91319, 91319, 91206),
    "equity_attributable_to_owners":           ("bs", 94756, 90489, 90489, 90424),
    "non_controlling_interests":               ("bs", 1015, 830, 830, 782),
    "cash_and_equivalents":                    ("bs", 8342, 9016, 9016, 7123),
    "other_balances_with_banks":               ("bs", 7121, 4270, 4270, 3909),
    "current_investments":                     ("bs", 30689, 31481, 31481, 36897),
    "non_current_investments":                 ("bs", 275, 281, 281, 266),
    "total_assets":                            ("bs", 159629, 146449, 146449, 143651),
    "lease_liabilities_non_current":           ("bs", 7838, 6516, 6516, 6203),
    "lease_liabilities_current":               ("bs", 1554, 1505, 1505, 1485),
    "cash_from_operations":                    ("cf", 48908, 44338, 44338, 41965),
    "purchase_of_ppe":                         ("cf", 2917, 2202, 2202, 2532),
    "purchase_of_intangibles":                 ("cf", 944, 442, 442, 355),
    "shares_outstanding":                      ("shares", 3618087518, 3618087518, 3618087518, 3659051373),
}
FY26_ONLY_LINES = {"exceptional_restructuring_expenses", "exceptional_labour_codes_impact",
                   "exceptional_legal_claim_provision"}


def all_rows():
    with open(MANUAL_CSV, newline="") as f:
        return list(csv.DictReader(f))


def rows_from(doc):
    return [r for r in all_rows() if r["source_doc"] == doc]


@pytest.fixture
def full(conn, ctx):
    """In-memory DB with the whole manual CSV loaded (as the build does: llm_extracted)."""
    load_rows(conn, all_rows(), ctx, entry_method="llm_extracted")
    return conn


# ---------- config: sources and periods ----------

def test_fy23_and_fy24_periods_have_real_dates(ctx):
    assert ctx.periods["FY23"]["start_date"] == "2022-04-01" and ctx.periods["FY23"]["end_date"] == "2023-03-31"
    assert ctx.periods["FY24"]["start_date"] == "2023-04-01" and ctx.periods["FY24"]["end_date"] == "2024-03-31"


def test_new_reports_are_registered_after_the_old_ones(ctx):
    # Appended, so the source_ids of the FY26 report (1) and fact sheet (2) do not move and the
    # existing Chroma index and eval gold sources stay valid.
    assert list(ctx.sources) == [AR26, "tcs_factsheet_Q1_FY27.pdf", AR25, AR24]
    for name, period in ((AR25, "FY25"), (AR24, "FY24")):
        s = ctx.sources[name]
        assert s["doc_type"] == "annual_report" and s["period_covered"] == period
        assert s["accounting_standard"] == "Ind AS"
        assert s["sha256"] == SHA[name]


def test_hashes_file_lists_both_new_reports():
    hashes = read_source_hashes(HASHES_FILE)
    for name, sha in SHA.items():
        assert hashes[name] == sha


def test_hash_check_runs_on_the_real_files_if_present():
    if not all((RAW / n).exists() for n in SHA):
        pytest.skip("private PDFs not checked out")
    load_context(COMPANY_CONFIG, METRICS_CONFIG, HASHES_FILE, raw_dir=RAW)     # re-hashes every file


@pytest.mark.parametrize("name, pdf_page, printed", [
    (AR25, 4, "2"), (AR25, 180, "178"), (AR25, 181, "179"), (AR25, 184, "182"), (AR25, 202, "200"),
    (AR25, 332, "330"), (AR25, 3, None), (AR25, 333, None),
    (AR24, 3, "3"), (AR24, 181, "181"), (AR24, 203, "203"), (AR24, 336, "336"), (AR24, 2, None),
    (AR24, 337, None),
])
def test_page_labels_of_the_new_reports(ctx, name, pdf_page, printed):
    labels = parse_page_labels(ctx.sources[name]["page_labels"])
    assert labels.get(pdf_page, [None])[0] == printed


# ---------- printed page numbers in the page header (FY25 and FY24 reports) ----------

def test_page_number_in_the_header_is_read(tmp_path):
    import pymupdf
    path = tmp_path / "header.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=594, height=756)
    page.insert_text((540, 30), "182", fontsize=9, fontname="helv")     # number at the top, nothing below
    doc.save(path)
    with pymupdf.open(path) as d:
        p = d[0]
        assert _footer_numbers(p, p.rect, 40) == []
        assert "182" in _page_numbers(p, p.rect, 40, 55)


@pytest.mark.parametrize("name", [AR25, AR24])
def test_real_report_page_numbers_agree_with_config(ctx, name):
    """Every numbered page: the number read from the header/footer is the configured label, or the
    text layer drops digits (FY25 maps some digits to other glyphs). Never a different number."""
    import pymupdf
    from erp.ingest.pdf_to_chunks import _check_label, load_ingest_config
    if not (RAW / name).exists():
        pytest.skip("private PDF not checked out")
    pdf_cfg = load_ingest_config()["pdf"]
    labels = parse_page_labels(ctx.sources[name]["page_labels"])
    hard, exact = [], 0
    with pymupdf.open(RAW / name) as d:
        for pdf_page, (label,) in labels.items():
            p = d[pdf_page - 1]
            w = _check_label(pdf_page, label,
                             _page_numbers(p, p.rect, pdf_cfg["footer_band"], pdf_cfg["header_band"]))
            if w is None:
                exact += 1
            elif not w.endswith("(config kept)"):
                hard.append(w)
    assert hard == []
    assert exact >= 0.75 * len(labels)


# ---------- metrics config ----------

def test_settlement_line_is_its_own_metric_with_a_band(ctx):
    m = ctx.metrics["exceptional_legal_claim_settlement"]
    assert (m["statement"], m["canonical_unit"], m["is_flow"]) == ("income", "INR_CRORE", 1)
    assert "Settlement of legal claim" in m["definition"]
    assert "exceptional_legal_claim_provision" in m["definition"]      # says how it differs
    assert ctx.bands["exceptional_legal_claim_settlement"]["min"] == 0


def test_settlement_cross_foot_is_configured(ctx):
    check = next(c for c in ctx.cross_foot_checks if c["name"] == "profit_before_tax_single_exceptional_line")
    assert check["total"] == "profit_before_tax"
    assert check["parts"] == [{"metric": "profit_before_exceptional_items_and_tax", "sign": 1},
                              {"metric": "exceptional_legal_claim_settlement", "sign": -1}]


# ---------- the new CSV rows ----------

def test_d1_rows_are_unchanged_and_still_signed_off():
    old = rows_from(AR26)
    assert len(old) == 54
    assert all(r["verified_by"] == "Aradhya Chandra" for r in old)


@pytest.mark.parametrize("doc", [AR25, AR24])
def test_new_rows_are_claude_entries_not_yet_verified_with_both_pages(ctx, doc):
    rows = rows_from(doc)
    assert len(rows) == 2 * len(PRINTED)
    labels = parse_page_labels(ctx.sources[doc]["page_labels"])
    for r in rows:
        assert r["entered_by"] == "Claude", r
        assert r["verified_by"] == "Aradhya Chandra" and r["verified_on"] == "2026-10-10", r   # D3 sign-off
        assert r["ticker"] == "TCS" and r["basis"] == "consolidated"
        page = int(r["source_page"])
        assert r["source_page_label"] == labels[page][0], r
        assert (page, r["source_page_label"]) == PAGES[doc][PRINTED[r["metric_id"]][0]], r


@pytest.mark.parametrize("doc, col, period", [(AR25, 1, "FY25"), (AR25, 2, "FY24"),
                                              (AR24, 3, "FY24"), (AR24, 4, "FY23")])
def test_new_rows_hold_the_printed_figures(doc, col, period):
    got = {r["metric_id"]: float(r["reported_value"]) for r in rows_from(doc) if r["period"] == period}
    assert got == {m: float(v[col]) for m, v in PRINTED.items()}


def test_units_as_printed():
    for r in rows_from(AR25) + rows_from(AR24):
        expected = {"eps_basic": "INR_PER_SHARE", "shares_outstanding": "SHARES"}.get(r["metric_id"], "INR_CRORE")
        assert r["reported_unit"] == expected, r


def test_fy26_only_exceptional_lines_are_not_invented_for_older_years():
    for r in rows_from(AR25) + rows_from(AR24):
        assert r["metric_id"] not in FY26_ONLY_LINES
    assert {r["period"] for r in all_rows() if r["metric_id"] in FY26_ONLY_LINES} == {"FY26", "FY25"}


def test_fy23_comes_only_from_the_fy24_report():
    assert {r["source_doc"] for r in all_rows() if r["period"] == "FY23"} == {AR24}


def test_no_row_is_a_restatement():
    # Every FY25 and FY24 comparative agreed with the primary report; nothing needed restating.
    for r in all_rows():
        assert not r.get("restated") and not r.get("supersedes_source_doc")


# ---------- loading: all checks ----------

def test_whole_csv_loads_with_all_checks(conn, ctx):
    ids = load_rows(conn, all_rows(), ctx, entry_method="llm_extracted")
    assert len(ids) == 54 + 4 * len(PRINTED)
    unverified = conn.execute("SELECT COUNT(*) FROM fact WHERE verified_by IS NULL").fetchone()[0]
    assert unverified == 0                                  # all signed off (D3 on 2026-10-10)


def test_whole_csv_loads_with_the_real_pdf_hashes_if_present():
    if not all((RAW / n).exists() for n in (AR26, AR25, AR24)):
        pytest.skip("private PDFs not checked out")
    ctx = load_context(COMPANY_CONFIG, METRICS_CONFIG, HASHES_FILE, raw_dir=RAW)
    c = create_db(":memory:")
    seed_reference_data(c, ctx)
    load_rows(c, all_rows(), ctx, entry_method="llm_extracted")


def _corrupt(doc, metric_id, period, value):
    rows = all_rows()
    for r in rows:
        if (r["source_doc"], r["metric_id"], r["period"]) == (doc, metric_id, period):
            r["reported_value"] = str(value)
    return rows


def test_fy25_figure_disagreeing_with_the_fy26_reports_comparative_is_rejected(conn, ctx):
    with pytest.raises(LoadError, match=r"revenue_from_operations FY25.*disagrees.*restated"):
        load_rows(conn, _corrupt(AR25, "revenue_from_operations", "FY25", 255342), ctx, "llm_extracted")
    assert conn.execute("SELECT COUNT(*) FROM fact").fetchone()[0] == 0


def test_fy24_comparative_disagreeing_with_the_fy24_report_is_rejected(conn, ctx):
    with pytest.raises(LoadError, match=r"total_assets FY24.*disagrees"):
        load_rows(conn, _corrupt(AR25, "total_assets", "FY24", 146494), ctx, "llm_extracted")


@pytest.mark.parametrize("metric_id, period, wrong, check", [
    ("profit_before_tax", "FY24", 61979, "profit_before_tax_single_exceptional_line"),
    ("exceptional_legal_claim_settlement", "FY23", 958, "profit_before_tax_single_exceptional_line"),
    ("tax_expense", "FY23", 14640, "profit_for_the_year"),
    ("non_controlling_interests", "FY23", 728, "total_equity"),
])
def test_cross_foots_catch_typos_in_the_fy24_report(conn, ctx, metric_id, period, wrong, check):
    with pytest.raises(LoadError, match=rf"{check}.*{period}"):
        load_rows(conn, _corrupt(AR24, metric_id, period, wrong), ctx, "llm_extracted")


def test_identities_hold_on_the_printed_figures():
    # Hand arithmetic:
    #   FY25: 65331 - 0 = 65331;   65331 - 16534 = 48797;  94756 + 1015 = 95771
    #   FY24: 62955 - 958 = 61997; 61997 - 15898 = 46099;  90489 + 830 = 91319
    #   FY23: 56907 - 0 = 56907;   56907 - 14604 = 42303;  90424 + 782 = 91206
    for col in (1, 2, 3, 4):
        v = {m: p[col] for m, p in PRINTED.items()}
        assert v["profit_before_exceptional_items_and_tax"] - v["exceptional_legal_claim_settlement"] \
            == v["profit_before_tax"]
        assert v["profit_before_tax"] - v["tax_expense"] == v["profit_after_tax"]
        assert v["equity_attributable_to_owners"] + v["non_controlling_interests"] == v["total_equity"]


# ---------- lookups: primary source and cross-checks ----------

def test_fy25_primary_source_is_now_the_fy25_report_cross_checked_by_fy26(full):
    f = get_financial_fact(full, "TCS", "revenue_from_operations", "FY25")
    assert f.value == 255324 and f.primary_source is True
    assert f.source_file == f"data/raw/{AR25}" and (f.source_page, f.source_page_label) == (181, "179")
    assert f.verified                                       # signed off 2026-10-10
    [x] = f.cross_checked_by
    assert x.source_file == f"data/raw/{AR26}" and x.source_page == 167 and x.value == 255324 and x.verified


def test_fy24_primary_is_the_fy24_report_cross_checked_by_fy25(full):
    f = get_financial_fact(full, "TCS", "total_assets", "FY24")
    assert f.value == 146449 and f.primary_source and f.source_file == f"data/raw/{AR24}"
    assert [(x.source_file, x.source_page) for x in f.cross_checked_by] == [(f"data/raw/{AR25}", 180)]


def test_fy23_has_no_primary_report_and_no_cross_check(full):
    f = get_financial_fact(full, "TCS", "revenue_from_operations", "FY23")
    assert f.value == 225458 and f.primary_source is False
    assert f.source_file == f"data/raw/{AR24}" and f.cross_checked_by == []


def test_fy26_lookups_are_unchanged(full):
    f = get_financial_fact(full, "TCS", "revenue_from_operations", "FY26")
    assert f.source_file == f"data/raw/{AR26}" and f.source_page == 167 and f.verified


def test_settlement_line_fy24(full):
    f = get_financial_fact(full, "TCS", "exceptional_legal_claim_settlement", "FY24")
    assert f.value == 958 and (f.source_page, f.source_page_label) == (181, "181")
    with pytest.raises(FactNotFoundError):
        get_financial_fact(full, "TCS", "exceptional_restructuring_expenses", "FY24")


def test_fy23_share_count_before_the_buyback(full):
    f = get_financial_fact(full, "TCS", "shares_outstanding", "FY23")
    assert f.reported_value == 3659051373 and f.value == pytest.approx(365.9051373, rel=REL)
    assert (f.source_page, f.source_page_label) == (203, "203")


# ---------- ratios over four years (hand arithmetic, bc scale=15) ----------

# net_margin: FY24 45908 / 240893 x 100 = 19.0574238354788;  FY23 42147 / 225458 x 100 = 18.6939474314506
# operating_margin: FY24 EBIT 62955 - 4422 + 778 = 59311; / 240893 x 100 = 24.6213048947042
#                   FY23 EBIT 56907 - 3449 + 779 = 54237; / 225458 x 100 = 24.0563652653709
# effective_tax_rate: FY24 15898 / 61997 x 100 = 25.6431762827233; FY23 14604 / 56907 x 100 = 25.6629237176445
# return_on_equity: FY25 avg (94756 + 90489) / 2 = 92622.5; 48553 / 92622.5 x 100 = 52.4203082404383
#                   FY24 avg (90489 + 90424) / 2 = 90456.5; 45908 / 90456.5 x 100 = 50.7514661743489
# capex_to_revenue: FY24 (2202 + 442) / 240893 x 100 = 1.0975827442059; FY23 (2532 + 355) / 225458 x 100 = 1.2805045729138
# ocf_to_profit: FY24 44338 / 45908 x 100 = 96.5801167552496; FY23 41965 / 42147 x 100 = 99.5681780435143
# da_to_revenue: FY24 4985 / 240893 x 100 = 2.0693835022188; FY23 5022 / 225458 x 100 = 2.2274658694745
# revenue_growth_yoy: FY24 (240893 - 225458) / 225458 x 100 = 6.8460644554639
#                     FY25 (255324 - 240893) / 240893 x 100 = 5.9906265437351
# net_profit_growth_yoy: FY24 (45908 - 42147) / 42147 x 100 = 8.9235295513322
# eps_growth_yoy: FY24 (125.88 - 115.19) / 115.19 x 100 = 9.2803194721764
#                 FY25 (134.19 - 125.88) / 125.88 x 100 = 6.6015252621544
@pytest.mark.parametrize("ratio_id, period, expected", [
    ("net_margin", "FY24", 19.0574238354788),
    ("net_margin", "FY23", 18.6939474314506),
    ("operating_margin", "FY24", 24.6213048947042),
    ("operating_margin", "FY23", 24.0563652653709),
    ("effective_tax_rate", "FY24", 25.6431762827233),
    ("effective_tax_rate", "FY23", 25.6629237176445),
    ("return_on_equity", "FY25", 52.4203082404383),
    ("return_on_equity", "FY24", 50.7514661743489),
    ("capex_to_revenue", "FY24", 1.0975827442059),
    ("capex_to_revenue", "FY23", 1.2805045729138),
    ("ocf_to_profit", "FY24", 96.5801167552496),
    ("ocf_to_profit", "FY23", 99.5681780435143),
    ("da_to_revenue", "FY24", 2.0693835022188),
    ("da_to_revenue", "FY23", 2.2274658694745),
    ("revenue_growth_yoy", "FY24", 6.8460644554639),
    ("revenue_growth_yoy", "FY25", 5.9906265437351),
    ("net_profit_growth_yoy", "FY24", 8.9235295513322),
    ("eps_growth_yoy", "FY24", 9.2803194721764),
    ("eps_growth_yoy", "FY25", 6.6015252621544),
])
def test_ratio_history_matches_hand_calculation(full, ratio_id, period, expected):
    r = compute_ratio(full, "TCS", ratio_id, period)
    assert r.value == pytest.approx(expected, rel=REL)
    assert r.verified is True           # every input is signed off


def test_every_ratio_computes_for_fy24_to_fy26(full):
    for ratio_id in load_ratios(RATIOS_CONFIG, METRICS_CONFIG):
        for period in ("FY24", "FY25", "FY26"):
            if ratio_id == "revenue_cagr_3y" and period != "FY26":
                continue                              # needs FY21/FY22, see below
            compute_ratio(full, "TCS", ratio_id, period)


@pytest.mark.parametrize("ratio_id", ["return_on_equity", "revenue_growth_yoy", "net_profit_growth_yoy",
                                      "eps_growth_yoy"])
def test_fy23_ratios_needing_fy22_refuse(full, ratio_id):
    with pytest.raises(FactNotFoundError, match="FY22"):
        compute_ratio(full, "TCS", ratio_id, "FY23")


# ---------- 3-year revenue CAGR (new ratio kind) ----------

# (267021 / 225458) ^ (1/3) - 1, x 100:  267021 / 225458 = 1.184349191423679;  bc -l:
#   (e(l(1.184349191423679) / 3) - 1) * 100 = 5.8018486193645
CAGR_FY26 = 5.8018486193645


def test_revenue_cagr_3y_is_configured():
    r = load_ratios(RATIOS_CONFIG, METRICS_CONFIG)["revenue_cagr_3y"]
    assert (r["kind"], r["metric"], r["years"], r["unit"]) == ("cagr", "revenue_from_operations", 3, "PERCENT")
    assert r["formula_version"] == "revenue_cagr_3y.v1"


def test_revenue_cagr_3y_matches_hand_calculation(full):
    r = compute_ratio(full, "TCS", "revenue_cagr_3y", "FY26")
    assert r.value == pytest.approx(CAGR_FY26, rel=REL)
    assert [(i.role, i.fact.period_label, i.fact.value) for i in r.inputs] == [
        ("current", "FY26", 267021), ("base (3 years earlier)", "FY23", 225458)]
    assert r.formula == ("((revenue_from_operations[FY26] / revenue_from_operations[FY23]) ^ (1 / 3) - 1) * 100")
    assert r.verified is True                      # FY23 rows signed off 2026-10-10 (single source)


def test_revenue_cagr_needs_the_base_year(full):
    with pytest.raises(FactNotFoundError, match="FY22"):
        compute_ratio(full, "TCS", "revenue_cagr_3y", "FY25")


def test_cagr_refuses_a_non_positive_base():
    from erp.tools.ratios import cagr_percent
    assert cagr_percent(133.1, 100, 3) == pytest.approx(10.0, rel=REL)     # 1.1^3 = 1.331
    with pytest.raises(RatioError, match="positive"):
        cagr_percent(100, 0, 3)
    with pytest.raises(RatioError, match="positive"):
        cagr_percent(-5, 100, 3)


def _write_ratios(tmp_path, mutate):
    cfg = yaml.safe_load(RATIOS_CONFIG.read_text())
    mutate(cfg["ratios"])
    path = tmp_path / "ratios.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


@pytest.mark.parametrize("mutate, match", [
    (lambda r: r["revenue_cagr_3y"].pop("years"), "years"),
    (lambda r: r["revenue_cagr_3y"].update(years=0), "years"),
    (lambda r: r["revenue_cagr_3y"].update(years=2.5), "years"),
    (lambda r: r["revenue_cagr_3y"].update(metric="revenue"), "revenue"),
])
def test_bad_cagr_config_is_rejected(tmp_path, mutate, match):
    with pytest.raises(ConfigError, match=match):
        load_ratios(_write_ratios(tmp_path, mutate), METRICS_CONFIG)


def test_cagr_is_a_growth_number_for_the_verifier(full):
    env = ToolEnv(conn=full, ticker="TCS", display=DISPLAY, dcf_assumptions=TOY_YAML)
    res = run_tool(ToolCall(tool="compute_ratio", args={"ratio_id": "revenue_cagr_3y", "period": "FY26"}), env)
    assert res.ok and res.numbers[0].display == "5.80%" and res.numbers[0].measures_change
    assert {e.page for e in res.evidence if e.kind == "fact"} == {167, 181}


# ---------- search results carry the right document period ----------

def test_search_evidence_carries_each_documents_period(full, tmp_path):
    from erp.ingest.index_chroma import add_chunks, open_collection
    from fakes import fake_embed
    collection = open_collection(tmp_path / "chroma", "d3_docs")
    ids = dict(full.execute("SELECT local_path, source_id FROM source_document").fetchall())
    chunks = []
    for name, fy in ((AR26, 2026), (AR25, 2025), (AR24, 2024)):
        sid = ids[f"data/raw/{name}"]
        meta = {"source_id": sid, "doc_type": "annual_report", "doc_title": f"Report {fy}", "page": 10,
                "page_end": 10, "page_label": "10", "page_label_end": "10", "section": "Risks",
                "fiscal_year": fy, "chunk_id": f"src{sid}-p10-0", "is_table_heavy": False,
                "file_sha256": "0" * 64, "embed_model": "fake"}
        chunks.append((f"risk text {fy}", meta))
    add_chunks(collection, chunks, embed_fn=fake_embed)
    env = ToolEnv(conn=full, ticker="TCS", display=DISPLAY, dcf_assumptions=TOY_YAML, collection=collection,
                  embed_fn=fake_embed, search_top_k=3)
    res = run_tool(ToolCall(tool="search_documents", args={"query": "risk text"}), env)
    by_source = {e.source_id: e.period for e in res.evidence}
    assert by_source == {ids[f"data/raw/{AR26}"]: "FY26", ids[f"data/raw/{AR25}"]: "FY25",
                         ids[f"data/raw/{AR24}"]: "FY24"}
    fy = {r["source_id"]: r["fiscal_year"] for r in res.detail["results"]}
    assert fy == {ids[f"data/raw/{AR26}"]: 2026, ids[f"data/raw/{AR25}"]: 2025, ids[f"data/raw/{AR24}"]: 2024}


# ---------- Company snapshot: small 4-year trend under each card ----------

def _snapshot_cfg(**kw):
    cfg = {"period": "FY26", "compare_period": "FY25", "basis": "consolidated",
           "trend_periods": ["FY23", "FY24", "FY25", "FY26"],
           "cards": [{"label": "Revenue", "tool": "get_financial_fact", "metric_id": "revenue_from_operations"},
                     {"label": "Net margin", "tool": "compute_ratio", "ratio_id": "net_margin"}]}
    cfg.update(kw)
    return cfg


def _ui_cfg():
    return yaml.safe_load((REPO / "config" / "ui.yaml").read_text())


def test_ui_config_asks_for_a_four_year_trend():
    assert _ui_cfg()["snapshot"]["trend_periods"] == ["FY23", "FY24", "FY25", "FY26"]


def test_snapshot_trend_values_come_from_the_tools(full):
    from erp.ui import snapshot
    env = ToolEnv(conn=full, ticker="TCS", display=DISPLAY, dcf_assumptions=TOY_YAML)
    rev, margin = snapshot.build_snapshot(env, _snapshot_cfg(), _ui_cfg())
    assert [(p.period, p.display) for p in rev.trend] == [
        ("FY23", "INR 225,458 crore"), ("FY24", "INR 240,893 crore"),
        ("FY25", "INR 255,324 crore"), ("FY26", "INR 267,021 crore")]
    assert [p.value for p in rev.trend] == [225458, 240893, 255324, 267021]
    # FY23-FY25 now come from the FY24/FY25 reports (not signed off yet); FY26 is signed off.
    assert [p.verified for p in rev.trend] == [True, True, True, True]     # all signed off
    assert [p.display for p in margin.trend] == ["18.69%", "19.06%", "19.02%", "18.43%"]
    assert all(p.error is None for p in rev.trend + margin.trend)


def test_snapshot_trend_without_data_says_so_and_invents_nothing(full):
    from erp.ui import snapshot
    env = ToolEnv(conn=full, ticker="TCS", display=DISPLAY, dcf_assumptions=TOY_YAML)
    [rev, _] = snapshot.build_snapshot(env, _snapshot_cfg(trend_periods=["FY22", "FY26"]), _ui_cfg())
    fy22, fy26 = rev.trend
    assert fy22.display is None and fy22.value is None and "FY22" in fy22.error
    assert fy26.display == "INR 267,021 crore"


def test_snapshot_without_trend_config_has_no_trend(full):
    from erp.ui import snapshot
    env = ToolEnv(conn=full, ticker="TCS", display=DISPLAY, dcf_assumptions=TOY_YAML)
    cfg = _snapshot_cfg()
    cfg.pop("trend_periods")
    assert all(c.trend == [] for c in snapshot.build_snapshot(env, cfg, _ui_cfg()))


def test_trend_chart_plots_only_the_points_with_values():
    from erp.ui.charts import trend_chart
    from erp.ui.snapshot import TrendPoint
    points = [TrendPoint(period="FY22", error="no data"),
              TrendPoint(period="FY23", display="INR 225,458 crore", value=225458, verified=False),
              TrendPoint(period="FY26", display="INR 267,021 crore", value=267021, verified=True)]
    chart = trend_chart(points)
    assert list(chart.data["Period"]) == ["FY23", "FY26"]
    assert list(chart.data["Value"]) == [225458, 267021]


def test_page_snapshot_tab_shows_the_trend(full, tmp_path):
    import sqlite3
    from streamlit.testing.v1 import AppTest
    db = tmp_path / "db.sqlite"
    disk = sqlite3.connect(db)
    full.backup(disk)
    disk.close()
    (tmp_path / "runs").mkdir()

    def page(results, db_path):
        from erp.ui.app import main as _main
        _main(["--demo", results, "--db", db_path])

    at = AppTest.from_function(page, args=(str(tmp_path / "runs"), str(db)), default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    snap = at.tabs[1]
    text = "\n".join(c.value for c in snap.caption)
    assert "FY23: INR 225,458 crore" in text and "FY26: INR 267,021 crore" in text
    assert "not yet checked by a human" not in text                       # all years signed off
