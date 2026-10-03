"""M1 acceptance tests: the sample CSV loads cleanly, and bad rows are rejected."""
import dataclasses

import pytest

from conftest import HASHES_FILE, COMPANY_CONFIG, METRICS_CONFIG, SAMPLE_CSV, fact_count, read_sample_rows
from erp.config import ConfigError, load_context
from erp.db.load_facts import LoadError, load_facts_csv, load_rows
from erp.db.validate import check_fact, validate_rows
from erp.units import UnitError, conversion_factor


def load_one(conn, ctx, row):
    return load_rows(conn, [row], ctx, entry_method="llm_extracted")


def assert_rejected(conn, ctx, rows, *expected_words):
    with pytest.raises(LoadError) as exc:
        load_rows(conn, rows, ctx, entry_method="llm_extracted")
    message = str(exc.value).lower()
    for word in expected_words:
        assert word.lower() in message, message
    assert fact_count(conn) == 0  # all-or-nothing: nothing was written


# ---------- the real sample loads cleanly ----------

def test_sample_csv_loads_cleanly(conn, ctx):
    n = len(read_sample_rows())
    ids = load_facts_csv(conn, SAMPLE_CSV, ctx, entry_method="llm_extracted")
    assert len(ids) == n
    assert fact_count(conn) == n


def test_loaded_units_match_canonical_unit(conn, ctx):
    load_facts_csv(conn, SAMPLE_CSV, ctx, entry_method="llm_extracted")
    mismatches = conn.execute(
        "SELECT COUNT(*) FROM fact f JOIN metric m USING (metric_id) "
        "WHERE f.unit != m.canonical_unit"
    ).fetchone()[0]
    assert mismatches == 0


def test_loaded_value_equals_reported_times_factor(conn, ctx):
    load_facts_csv(conn, SAMPLE_CSV, ctx, entry_method="llm_extracted")
    for value, reported, factor in conn.execute(
        "SELECT value, reported_value, conversion_factor FROM fact"
    ):
        assert value == pytest.approx(reported * factor, rel=1e-12)


def test_loaded_provenance_fields(conn, ctx):
    load_facts_csv(conn, SAMPLE_CSV, ctx, entry_method="llm_extracted")
    rows = conn.execute("SELECT DISTINCT entry_method, basis FROM fact").fetchall()
    assert rows == [("llm_extracted", "consolidated")]
    # verified_by is stored exactly as the CSV gives it (blank -> NULL)
    expected = sorted((r.get("verified_by") or "").strip() or "" for r in read_sample_rows())
    stored = sorted(v or "" for (v,) in conn.execute("SELECT verified_by FROM fact"))
    assert stored == expected
    pages = conn.execute(
        "SELECT source_page, source_page_label FROM fact "
        "WHERE metric_id = 'revenue_from_operations' AND period_id = "
        "(SELECT period_id FROM period WHERE label = 'FY26')"
    ).fetchone()
    assert pages == (167, "197")


def test_periods_have_real_dates(conn):
    row = conn.execute(
        "SELECT period_type, fiscal_year, start_date, end_date FROM period WHERE label = 'FY26'"
    ).fetchone()
    assert row == ("FY", 2026, "2025-04-01", "2026-03-31")


def test_source_documents_seeded_with_hashes(conn):
    expected = {}
    for line in HASHES_FILE.read_text().splitlines():
        sha, path = line.split()
        expected[path.rsplit("/", 1)[-1]] = sha
    rows = conn.execute(
        "SELECT local_path, sha256, doc_type, url FROM source_document ORDER BY source_id"
    ).fetchall()
    assert len(rows) == 2
    for local_path, sha, doc_type, url in rows:
        assert sha == expected[local_path.rsplit("/", 1)[-1]]
        assert url is None
    assert rows[0][2] == "annual_report"


def test_metrics_seeded_from_config(conn):
    ids = {r[0] for r in conn.execute("SELECT metric_id FROM metric")}
    assert ids == {
        "revenue_from_operations", "profit_after_tax", "profit_attributable_to_owners",
        "eps_basic", "total_equity", "cash_and_equivalents",
    }
    defs = dict(conn.execute("SELECT metric_id, definition FROM metric"))
    assert "profit for the year, including non-controlling interests" in defs["profit_after_tax"]
    owners = " ".join(defs["profit_attributable_to_owners"].split()).lower()
    assert "attributable to shareholders of the company" in owners
    assert "after non-controlling interests" in owners
    assert "statutory (after exceptional items)" in owners
    is_flow, unit = conn.execute(
        "SELECT is_flow, canonical_unit FROM metric WHERE metric_id = 'profit_attributable_to_owners'").fetchone()
    assert (is_flow, unit) == (1, "INR_CRORE")


# ---------- units ----------

def test_conversion_factors():
    assert conversion_factor("INR_CRORE", "INR_CRORE") == 1
    assert conversion_factor("INR_MILLION", "INR_CRORE") == 0.1  # 1 crore = 10 million
    assert conversion_factor("INR_PER_SHARE", "INR_PER_SHARE") == 1
    with pytest.raises(UnitError):
        conversion_factor("INR_CRORE", "INR_PER_SHARE")
    with pytest.raises(UnitError):
        conversion_factor("USD_MILLION", "INR_CRORE")


def test_million_row_is_converted_to_crore(conn, ctx, good_row):
    good_row["reported_value"] = "2670210"  # FY26 revenue 267,021 crore, written in INR million
    good_row["reported_unit"] = "INR_MILLION"
    load_one(conn, ctx, good_row)
    value, unit, factor = conn.execute(
        "SELECT value, unit, conversion_factor FROM fact"
    ).fetchone()
    assert value == pytest.approx(267021)
    assert unit == "INR_CRORE"
    assert factor == 0.1


# ---------- deliberately bad rows are rejected ----------

def test_rejects_wrong_unit(conn, ctx, good_row):
    good_row["reported_unit"] = "INR_PER_SHARE"  # revenue cannot be per-share
    assert_rejected(conn, ctx, [good_row], "row 2", "unit")


def test_rejects_unknown_unit(conn, ctx, good_row):
    good_row["reported_unit"] = "USD_MILLION"
    assert_rejected(conn, ctx, [good_row], "unit")


@pytest.mark.parametrize("page", ["", "  ", "0", "-3", "abc", "12.5"])
def test_rejects_missing_or_bad_page(conn, ctx, good_row, page):
    good_row["source_page"] = page
    assert_rejected(conn, ctx, [good_row], "source_page")


def test_rejects_value_1000x_off(conn, ctx, good_row):
    good_row["reported_value"] = str(267021 * 1000)
    assert_rejected(conn, ctx, [good_row], "plausibility")


def test_rejects_value_1000x_too_small(conn, ctx, good_row):
    good_row["reported_value"] = "267.021"
    assert_rejected(conn, ctx, [good_row], "plausibility")


def test_rejects_crore_figure_labelled_as_million(conn, ctx, good_row):
    good_row["reported_unit"] = "INR_MILLION"  # 267021 million = 26,702 crore: 10x too small
    assert_rejected(conn, ctx, [good_row], "plausibility")


def test_rejects_unknown_metric(conn, ctx, good_row):
    good_row["metric_id"] = "revenue"
    assert_rejected(conn, ctx, [good_row], "unknown metric")


def test_rejects_unknown_period(conn, ctx, good_row):
    good_row["period"] = "FY24"  # not configured, so it has no real dates
    assert_rejected(conn, ctx, [good_row], "unknown period")


def test_rejects_duplicate_row_in_csv(conn, ctx, good_row):
    assert_rejected(conn, ctx, [good_row, dict(good_row)], "duplicate")


def test_rejects_duplicate_against_database(conn, ctx):
    load_facts_csv(conn, SAMPLE_CSV, ctx, entry_method="llm_extracted")
    with pytest.raises(LoadError, match="(?i)duplicate"):
        load_facts_csv(conn, SAMPLE_CSV, ctx, entry_method="llm_extracted")
    assert fact_count(conn) == len(read_sample_rows())


@pytest.mark.parametrize("basis", ["", "Consolidated", "group", "adjusted"])
def test_rejects_bad_basis(conn, ctx, good_row, basis):
    good_row["basis"] = basis
    assert_rejected(conn, ctx, [good_row], "basis")


def test_rejects_unknown_source_doc(conn, ctx, good_row):
    good_row["source_doc"] = "some_other_report.pdf"
    assert_rejected(conn, ctx, [good_row], "source_doc")


def test_rejects_unknown_ticker(conn, ctx, good_row):
    good_row["ticker"] = "INFY"
    assert_rejected(conn, ctx, [good_row], "ticker")


def test_rejects_non_numeric_value(conn, ctx, good_row):
    good_row["reported_value"] = "2,67,021"
    assert_rejected(conn, ctx, [good_row], "reported_value")


def test_rejects_missing_entered_by(conn, ctx, good_row):
    good_row["entered_by"] = ""
    assert_rejected(conn, ctx, [good_row], "entered_by")


def test_rejects_bad_entry_method(conn, ctx, good_row):
    with pytest.raises(LoadError, match="entry_method"):
        load_rows(conn, [good_row], ctx, entry_method="guessed")


def test_one_bad_row_blocks_whole_load(conn, ctx):
    rows = read_sample_rows()
    rows[5]["source_page"] = ""
    assert_rejected(conn, ctx, rows, "row 7")  # CSV row 7 = header + 6th data row


# ---------- checks on already-derived facts (guards against loader bugs) ----------

def test_check_fact_catches_unit_and_value_mismatch(ctx, good_row):
    facts, errors = validate_rows([good_row], ctx)
    assert errors == []
    fact = facts[0]
    assert check_fact(fact, ctx) == []

    wrong_unit = dataclasses.replace(fact, unit="INR_MILLION")
    assert any("canonical" in e for e in check_fact(wrong_unit, ctx))

    wrong_value = dataclasses.replace(fact, value=fact.value * 10)
    assert any("reported_value * conversion_factor" in e for e in check_fact(wrong_value, ctx))


# ---------- source hashes ----------

def test_missing_hash_is_rejected(tmp_path):
    hashes = tmp_path / "hashes.txt"
    hashes.write_text(HASHES_FILE.read_text().splitlines()[0] + "\n")  # only one of two docs
    with pytest.raises(ConfigError, match="sha256"):
        load_context(COMPANY_CONFIG, METRICS_CONFIG, hashes, raw_dir=None)


def test_file_not_matching_hash_is_rejected(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "tcs_annual_report_FY26.pdf").write_bytes(b"not the real pdf")
    with pytest.raises(ConfigError, match="sha256"):
        load_context(COMPANY_CONFIG, METRICS_CONFIG, HASHES_FILE, raw_dir=raw)


def test_real_pdfs_match_hashes_if_present():
    raw = HASHES_FILE.parent / "data" / "raw"
    if not (raw / "tcs_annual_report_FY26.pdf").exists():
        pytest.skip("private data repo not checked out")
    load_context(COMPANY_CONFIG, METRICS_CONFIG, HASHES_FILE, raw_dir=raw)  # must not raise


def test_rejects_fact_citing_generated_sample(conn, ctx, good_row):
    # LLM-generated notes must never be the source of a number in SQLite.
    ctx.sources["tcs_annual_report_FY26.pdf"]["doc_type"] = "generated_sample"
    assert_rejected(conn, ctx, [good_row], "generated_sample")


# ---------- optional verified_by / verified_on columns (M2) ----------

def test_csv_without_verified_columns_loads_unverified(conn, ctx, good_row):
    assert "verified_by" not in good_row  # the sample CSV has no such columns
    load_one(conn, ctx, good_row)
    assert conn.execute("SELECT verified_by, verified_on FROM fact").fetchone() == (None, None)


def test_blank_verified_columns_stay_null(conn, ctx, good_row):
    good_row["verified_by"] = "  "
    good_row["verified_on"] = ""
    load_one(conn, ctx, good_row)
    assert conn.execute("SELECT verified_by, verified_on FROM fact").fetchone() == (None, None)


def test_verified_columns_are_stored(conn, ctx, good_row):
    good_row["verified_by"] = "Test Reviewer"
    good_row["verified_on"] = "2026-10-04"
    load_one(conn, ctx, good_row)
    assert conn.execute("SELECT verified_by, verified_on FROM fact").fetchone() == (
        "Test Reviewer", "2026-10-04")


@pytest.mark.parametrize("verified_on", ["04/10/2026", "2026-13-01", "yesterday"])
def test_rejects_bad_verified_on_date(conn, ctx, good_row, verified_on):
    good_row["verified_by"] = "Test Reviewer"
    good_row["verified_on"] = verified_on
    assert_rejected(conn, ctx, [good_row], "verified_on")


def test_rejects_verified_on_without_verified_by(conn, ctx, good_row):
    good_row["verified_by"] = ""
    good_row["verified_on"] = "2026-10-04"
    assert_rejected(conn, ctx, [good_row], "verified_by")


def test_rejects_verified_by_without_date(conn, ctx, good_row):
    good_row["verified_by"] = "Test Reviewer"
    good_row["verified_on"] = ""
    assert_rejected(conn, ctx, [good_row], "verified_on")


def test_rejects_verifier_same_as_enterer(conn, ctx, good_row):
    # Verification means a second pair of eyes.
    good_row["verified_by"] = good_row["entered_by"]
    good_row["verified_on"] = "2026-10-04"
    assert_rejected(conn, ctx, [good_row], "verified_by")
