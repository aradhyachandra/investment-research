"""M2: get_financial_fact returns exactly one stored fact with its provenance, or raises.

Expected values below are copied from data/sample/facts_sample.csv (the rows under test),
not from the code.
"""
from datetime import date

import pytest

from conftest import read_sample_rows, sample_row
from erp.db.load_facts import load_rows
from erp.periods import PeriodError
from erp.tools.facts import (
    AmbiguousFactError,
    FactLookupError,
    FactNotFoundError,
    FactResult,
    UnknownMetricError,
    get_financial_fact,
)


def test_fy26_revenue_with_provenance(loaded):
    f = get_financial_fact(loaded, "TCS", "revenue_from_operations", "FY26", "consolidated")
    assert isinstance(f, FactResult)
    # canonical
    assert f.value == 267021
    assert f.unit == "INR_CRORE"
    # as reported
    assert f.reported_value == 267021
    assert f.reported_unit == "INR_CRORE"
    assert f.conversion_factor == 1
    # identity and period
    expected_id = loaded.execute(
        "SELECT fact_id FROM fact JOIN period USING (period_id)"
        " WHERE metric_id = 'revenue_from_operations' AND label = 'FY26'").fetchone()[0]
    assert f.fact_id == expected_id
    assert (f.period_label, f.period_start, f.period_end) == ("FY26", date(2025, 4, 1), date(2026, 3, 31))
    assert f.basis == "consolidated"
    # source
    assert f.source_title == "TCS Integrated Annual Report 2025-26"
    assert f.source_file == "data/raw/tcs_annual_report_FY26.pdf"
    assert f.source_page == 167
    assert f.source_page_label == "197"
    # provenance: sample rows are LLM-entered and unverified
    assert f.entry_method == "llm_extracted"
    assert f.verified_by is None
    assert f.verified is False
    # duplicate policy fields (M2.1)
    assert f.accounting_standard == "Ind AS"
    assert f.primary_source is True       # AR FY26 is the document for FY26
    assert f.cross_checked_by == []
    assert f.restated is False
    assert f.supersedes_fact_id is None


def test_basis_defaults_to_consolidated(loaded):
    f = get_financial_fact(loaded, "TCS", "profit_after_tax", "FY25")
    assert f.basis == "consolidated"
    assert f.value == 48797
    assert f.primary_source is False      # FY25 comes from AR FY26, not from an FY25 document


def test_per_share_metric(loaded):
    f = get_financial_fact(loaded, "TCS", "eps_basic", "FY25")
    assert (f.value, f.unit) == (134.19, "INR_PER_SHARE")


def test_balance_sheet_metric_page(loaded):
    f = get_financial_fact(loaded, "TCS", "cash_and_equivalents", "FY26")
    assert f.value == 6417
    assert (f.source_page, f.source_page_label) == (166, "196")


def test_as_reported_million_is_kept_beside_canonical_crore(conn, ctx):
    row = sample_row("revenue_from_operations", "FY26")
    row["reported_value"] = "2670210"   # 267,021 crore written as INR million
    row["reported_unit"] = "INR_MILLION"
    load_rows(conn, [row], ctx, entry_method="manual")
    f = get_financial_fact(conn, "TCS", "revenue_from_operations", "FY26")
    assert (f.value, f.unit) == (pytest.approx(267021), "INR_CRORE")
    assert (f.reported_value, f.reported_unit, f.conversion_factor) == (2670210, "INR_MILLION", 0.1)


def test_verified_flag_true_when_verified_by_is_set(conn, ctx):
    row = sample_row("revenue_from_operations", "FY26")
    row["verified_by"] = "Test Reviewer"
    row["verified_on"] = "2026-10-04"
    load_rows(conn, [row], ctx, entry_method="llm_extracted")
    f = get_financial_fact(conn, "TCS", "revenue_from_operations", "FY26")
    assert f.verified is True
    assert f.verified_by == "Test Reviewer"
    assert f.verified_on == "2026-10-04"


def test_restated_fact_replaces_the_old_one(loaded):
    old = get_financial_fact(loaded, "TCS", "revenue_from_operations", "FY25")
    # The loader cannot write restatements yet, so insert one directly.
    # Test-only value; not a TCS figure.
    with loaded:
        loaded.execute(
            "INSERT INTO fact (company_id, metric_id, period_id, basis, value, unit, reported_value,"
            " reported_unit, conversion_factor, source_id, source_page, entry_method, entered_by,"
            " restated, supersedes_fact_id)"
            " SELECT company_id, metric_id, period_id, basis, 255000, unit, 255000, reported_unit, 1,"
            " 2, 21, 'manual', 'test', 1, fact_id FROM fact WHERE fact_id = ?", (old.fact_id,))
    new = get_financial_fact(loaded, "TCS", "revenue_from_operations", "FY25")
    assert new.fact_id != old.fact_id
    assert new.value == 255000
    assert new.restated is True
    assert new.supersedes_fact_id == old.fact_id
    original = get_financial_fact(loaded, "TCS", "revenue_from_operations", "FY25", as_first_reported=True)
    assert original.fact_id == old.fact_id


# ---------- errors: never guess ----------

def test_unknown_metric_raises(loaded):
    with pytest.raises(UnknownMetricError, match="revenue"):
        get_financial_fact(loaded, "TCS", "revenue", "FY26")


def test_known_metric_with_no_fact_for_period_raises(loaded):
    # FY24 is a valid label but nothing is loaded for it. Must not fall back to FY25.
    with pytest.raises(FactNotFoundError, match="FY24"):
        get_financial_fact(loaded, "TCS", "revenue_from_operations", "FY24")


def test_quarter_with_no_data_raises(loaded):
    with pytest.raises(FactNotFoundError, match="Q1 FY27"):
        get_financial_fact(loaded, "TCS", "revenue_from_operations", "Q1 FY27")


def test_wrong_basis_raises(loaded):
    # Only consolidated facts are loaded. Must not fall back to consolidated.
    with pytest.raises(FactNotFoundError, match="standalone"):
        get_financial_fact(loaded, "TCS", "revenue_from_operations", "FY26", "standalone")


@pytest.mark.parametrize("basis", ["Consolidated", "group", ""])
def test_invalid_basis_raises(loaded, basis):
    with pytest.raises(FactLookupError, match="basis"):
        get_financial_fact(loaded, "TCS", "revenue_from_operations", "FY26", basis)


def test_unknown_period_label_raises(loaded):
    with pytest.raises(PeriodError, match="unknown period label"):
        get_financial_fact(loaded, "TCS", "revenue_from_operations", "CY25")


def test_unknown_ticker_raises(loaded):
    with pytest.raises(FactLookupError, match="INFY"):
        get_financial_fact(loaded, "INFY", "revenue_from_operations", "FY26")


def test_metric_known_but_empty_database_raises(conn):
    with pytest.raises(FactNotFoundError):
        get_financial_fact(conn, "TCS", "revenue_from_operations", "FY26")


def test_disagreeing_current_facts_are_ambiguous(loaded):
    # The loader rejects disagreeing duplicates, so this can only happen if someone writes to
    # the database directly. The lookup must still refuse rather than pick one.
    # Test-only value; not a TCS figure.
    with loaded:
        loaded.execute(
            "INSERT INTO fact (company_id, metric_id, period_id, basis, value, unit, reported_value,"
            " reported_unit, conversion_factor, source_id, source_page, entry_method, entered_by)"
            " SELECT company_id, metric_id, period_id, basis, 260000, unit, 260000, reported_unit, 1,"
            " 2, 21, 'manual', 'test' FROM fact WHERE metric_id = 'revenue_from_operations'"
            " AND period_id = (SELECT period_id FROM period WHERE label = 'FY26')")
    with pytest.raises(AmbiguousFactError, match="disagree"):
        get_financial_fact(loaded, "TCS", "revenue_from_operations", "FY26")


def test_every_sample_row_is_retrievable(loaded):
    for row in read_sample_rows():
        f = get_financial_fact(loaded, row["ticker"], row["metric_id"], row["period"], row["basis"])
        assert f.reported_value == float(row["reported_value"])
        assert f.source_page == int(row["source_page"])
