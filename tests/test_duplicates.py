"""M2.1: duplicate-fact policy (PROJECT_PLAN.md Section 4.1, rule 8).

Rows citing the fact sheet below are TEST-ONLY: they pretend the fact sheet prints annual
figures it does not print, so the policy can be exercised with the two documents we have.
Values that differ from the sample CSV are made up for the test and are not TCS figures.

Fact sheet pages used (PDF page index, from tcs_factsheet_Q1_FY27.pdf):
    21  'Ind AS Income Statement - Consolidated'  -> Ind AS
    14  'IFRS Income Statement'                   -> IFRS
     4  'Q1 FY27 Performance Highlights'          -> no standard configured
"""
import copy

import pytest
import yaml

from conftest import COMPANY_CONFIG, HASHES_FILE, METRICS_CONFIG, fact_count, sample_row
from erp.config import ConfigError, accounting_standard_for, load_context
from erp.db.load_facts import LoadError, create_db, load_rows, seed_reference_data
from erp.tools.facts import get_financial_fact
from erp.tools.ratios import compute_ratio

AR = "tcs_annual_report_FY26.pdf"
FS = "tcs_factsheet_Q1_FY27.pdf"
FS_IND_AS_PAGE = "21"
FS_IFRS_PAGE = "14"
FS_NO_STANDARD_PAGE = "4"


def ar_row(metric="revenue_from_operations", period="FY26", **changes):
    """The real sample row (annual report FY26), optionally changed."""
    row = sample_row(metric, period)
    row.update(changes)
    return row


def fs_row(metric="revenue_from_operations", period="FY26", page=FS_IND_AS_PAGE, **changes):
    """Test-only copy of the sample row, cited to the fact sheet instead."""
    row = sample_row(metric, period)
    row.update(source_doc=FS, source_page=page, source_page_label="", **changes)
    return row


def load(conn, ctx, *rows):
    return load_rows(conn, list(rows), ctx, entry_method="manual")


def lookup(conn, metric="revenue_from_operations", period="FY26", **kw):
    return get_financial_fact(conn, "TCS", metric, period, **kw)


def assert_rejected(conn, ctx, rows, *words):
    before = fact_count(conn)
    with pytest.raises(LoadError) as exc:
        load_rows(conn, rows, ctx, entry_method="manual")
    for w in words:
        assert w.lower() in str(exc.value).lower(), str(exc.value)
    assert fact_count(conn) == before   # nothing written
    return str(exc.value)


# ---------- same fact, same value: both kept, primary returned ----------

def test_same_value_from_two_sources_is_allowed(conn, ctx):
    ar_id, fs_id = load(conn, ctx, ar_row(), fs_row())
    f = lookup(conn)
    # AR FY26 has period_covered FY26, so it is the primary source for an FY26 fact.
    assert f.fact_id == ar_id
    assert f.primary_source is True
    assert [c.fact_id for c in f.cross_checked_by] == [fs_id]
    c = f.cross_checked_by[0]
    assert (c.source_page, c.value, c.reported_value, c.reported_unit) == (21, 267021, 267021, "INR_CRORE")
    assert c.source_title == "TCS Financial Results, Quarter I FY 2026-27"


def test_primary_wins_whatever_the_load_order(conn, ctx):
    (fs_id,) = load(conn, ctx, fs_row())
    (ar_id,) = load(conn, ctx, ar_row())
    f = lookup(conn)
    assert f.fact_id == ar_id
    assert [c.fact_id for c in f.cross_checked_by] == [fs_id]


def test_no_primary_document_falls_back_to_first_loaded(conn, ctx):
    # Neither document is "for" FY25 (period_covered FY26 and Q1 FY27).
    ar_id, fs_id = load(conn, ctx, ar_row(period="FY25"), fs_row(period="FY25"))
    f = lookup(conn, period="FY25")
    assert f.fact_id == ar_id
    assert f.primary_source is False
    assert [c.fact_id for c in f.cross_checked_by] == [fs_id]


@pytest.mark.parametrize("million", [
    "2670212",   # 267,021.2 crore: 0.2 away; AR prints whole crore (+-0.5), fact sheet Mn (+-0.05)
    "2670215",   # 267,021.5 crore: 0.5 away, inside 0.5 + 0.05
    "2670205",   # 267,020.5 crore: 0.5 away the other side
])
def test_same_value_within_printed_rounding_after_unit_conversion(conn, ctx, million):
    load(conn, ctx, ar_row(), fs_row(reported_value=million, reported_unit="INR_MILLION"))
    f = lookup(conn)
    assert f.value == 267021
    assert len(f.cross_checked_by) == 1
    assert f.cross_checked_by[0].reported_unit == "INR_MILLION"


# ---------- same fact, different value, no restatement link: rejected ----------

@pytest.mark.parametrize("million", [
    "2670221",   # 267,022.1 crore: 1.1 away, beyond 0.55
    "2670300",   # 267,030 crore: 9 away
])
def test_disagreement_in_one_csv_is_rejected(conn, ctx, million):
    message = assert_rejected(
        conn, ctx, [ar_row(), fs_row(reported_value=million, reported_unit="INR_MILLION")],
        "disagree", AR, FS, "p.167", "p.21", "267,021")


def test_disagreement_message_shows_both_values_and_pages(conn, ctx):
    message = assert_rejected(
        conn, ctx, [ar_row(), fs_row(reported_value="2670300", reported_unit="INR_MILLION")])
    assert "267,030" in message and "2,670,300 INR_MILLION" in message
    assert "267,021 INR_CRORE" in message
    assert "printed 197" in message
    assert "row 3" in message


def test_disagreement_with_database_is_rejected(conn, ctx):
    load(conn, ctx, ar_row())
    assert_rejected(conn, ctx, [fs_row(reported_value="267030")], "disagree", "fact_id")
    assert lookup(conn).value == 267021


def test_per_share_rounding(conn, ctx):
    # EPS printed to 2 decimals: 136.01 vs 136.015 agrees (half a paisa each side)...
    load(conn, ctx, ar_row("eps_basic"), fs_row("eps_basic", reported_value="136.015"))
    # ...but 136.03 does not.
    other = create_db(":memory:")
    seed_reference_data(other, ctx)
    assert_rejected(other, ctx, [ar_row("eps_basic"), fs_row("eps_basic", reported_value="136.03")], "disagree")


# ---------- accounting standards: never match IFRS with Ind AS ----------

def test_ifrs_figure_is_not_a_duplicate_of_ind_as(conn, ctx):
    ar_id, ifrs_id = load(conn, ctx, ar_row(), fs_row(page=FS_IFRS_PAGE, reported_value="267500"))
    ind_as = lookup(conn)
    assert (ind_as.fact_id, ind_as.accounting_standard) == (ar_id, "Ind AS")
    assert ind_as.cross_checked_by == []
    ifrs = lookup(conn, accounting_standard="IFRS")
    assert (ifrs.fact_id, ifrs.value, ifrs.accounting_standard) == (ifrs_id, 267500, "IFRS")


def test_ifrs_figure_with_same_value_is_not_a_cross_check(conn, ctx):
    load(conn, ctx, ar_row(), fs_row(page=FS_IFRS_PAGE))
    assert lookup(conn).cross_checked_by == []


def test_page_without_configured_standard_is_rejected(conn, ctx):
    assert_rejected(conn, ctx, [fs_row(page=FS_NO_STANDARD_PAGE)], "accounting standard", "page 4")


def test_unknown_standard_in_lookup_raises(conn, ctx):
    load(conn, ctx, ar_row())
    with pytest.raises(LookupError, match="US GAAP"):
        lookup(conn, accounting_standard="US GAAP")


# ---------- restatements ----------

def restating_row(**changes):
    """Test-only: the fact sheet 'restates' FY25 revenue to 255,000 crore."""
    return fs_row(period="FY25", reported_value="255000", restated="1", supersedes_source_doc=AR, **changes)


def test_restatement_is_accepted_and_returned_by_default(conn, ctx):
    (original_id,) = load(conn, ctx, ar_row(period="FY25"))
    (restated_id,) = load(conn, ctx, restating_row())
    f = lookup(conn, period="FY25")
    assert (f.fact_id, f.value, f.restated, f.supersedes_fact_id) == (restated_id, 255000, True, original_id)
    # The original stays in the database and can still be asked for.
    o = lookup(conn, period="FY25", as_first_reported=True)
    assert (o.fact_id, o.value, o.restated) == (original_id, 255324, False)
    assert conn.execute("SELECT restated, supersedes_fact_id FROM fact WHERE fact_id = ?",
                        (restated_id,)).fetchone() == (1, original_id)


def test_restatement_in_the_same_csv_after_the_original(conn, ctx):
    original_id, restated_id = load(conn, ctx, ar_row(period="FY25"), restating_row())
    assert lookup(conn, period="FY25").fact_id == restated_id


def test_restatement_before_its_original_in_the_csv_is_rejected(conn, ctx):
    assert_rejected(conn, ctx, [restating_row(), ar_row(period="FY25")], "supersedes")


def test_growth_ratio_uses_the_restated_prior_year(conn, ctx):
    load(conn, ctx, ar_row(), ar_row(period="FY25"))
    load(conn, ctx, restating_row())
    # (267021 - 255000) / 255000 x 100 = 12021 / 255000 x 100
    #   check: 255000 x 0.047 = 11985; 12021 - 11985 = 36; 36 / 255000 = 0.000141176...
    #   -> 4.7141176470588 %   (bc: 4.714117647058800)
    r = compute_ratio(conn, "TCS", "revenue_growth_yoy", "FY26")
    assert r.value == pytest.approx(4.7141176470588, rel=1e-9)
    assert r.inputs[1].fact.restated is True


@pytest.mark.parametrize("changes, words", [
    ({"restated": "1", "supersedes_source_doc": ""}, ["supersedes_source_doc"]),
    ({"restated": "", "supersedes_source_doc": AR}, ["restated"]),
    ({"restated": "yes", "supersedes_source_doc": AR}, ["restated"]),
    ({"restated": "1", "supersedes_source_doc": "nope.pdf"}, ["supersedes_source_doc"]),
])
def test_bad_restatement_columns_are_rejected(conn, ctx, changes, words):
    load(conn, ctx, ar_row(period="FY25"))
    row = fs_row(period="FY25", reported_value="255000", **changes)
    assert_rejected(conn, ctx, [row], *words)


def test_restatement_cannot_supersede_its_own_document(conn, ctx):
    assert_rejected(conn, ctx, [ar_row(period="FY25", restated="1", supersedes_source_doc=AR)],
                    "supersedes")


def test_restatement_of_a_missing_fact_is_rejected(conn, ctx):
    assert_rejected(conn, ctx, [restating_row()], "supersedes", "no", AR)


def test_restatement_cannot_cross_accounting_standards(conn, ctx):
    load(conn, ctx, fs_row(period="FY25", page=FS_IFRS_PAGE))   # IFRS original
    row = ar_row(period="FY25", reported_value="255000", restated="1", supersedes_source_doc=FS)
    assert_rejected(conn, ctx, [row], "supersedes")


# ---------- two documents restating the same fact (needs a third, test-only document) ----------

@pytest.fixture
def ctx3(ctx):
    c = copy.deepcopy(ctx)
    c.sources["test_annual_report_FY27.pdf"] = dict(
        c.sources[AR], file_name="test_annual_report_FY27.pdf", title="TEST-ONLY later report",
        period_covered="FY27", local_path="data/raw/test_annual_report_FY27.pdf", sha256="0" * 64)
    return c


@pytest.fixture
def conn3(ctx3):
    c = create_db(":memory:")
    seed_reference_data(c, ctx3)
    yield c
    c.close()


def test_two_agreeing_restatements_are_accepted(conn3, ctx3):
    load(conn3, ctx3, ar_row(period="FY25"))
    a, b = load(conn3, ctx3, restating_row(),
                ar_row(period="FY25", source_doc="test_annual_report_FY27.pdf", source_page="5",
                       source_page_label="", reported_value="255000", restated="1",
                       supersedes_source_doc=AR))
    f = lookup(conn3, period="FY25", ctx=ctx3)
    assert f.value == 255000 and f.restated
    assert {f.fact_id} | {c.fact_id for c in f.cross_checked_by} == {a, b}


def test_two_disagreeing_restatements_are_rejected(conn3, ctx3):
    load(conn3, ctx3, ar_row(period="FY25"))
    assert_rejected(conn3, ctx3, [
        restating_row(),
        ar_row(period="FY25", source_doc="test_annual_report_FY27.pdf", source_page="5",
               source_page_label="", reported_value="254000", restated="1", supersedes_source_doc=AR),
    ], "disagree")


def test_second_restatement_supersedes_the_first(conn3, ctx3):
    (original_id,) = load(conn3, ctx3, ar_row(period="FY25"))
    (first_id,) = load(conn3, ctx3, restating_row())
    (second_id,) = load(conn3, ctx3, ar_row(
        period="FY25", source_doc="test_annual_report_FY27.pdf", source_page="5", source_page_label="",
        reported_value="254000", restated="1", supersedes_source_doc=FS))
    f = lookup(conn3, period="FY25", ctx=ctx3)
    assert (f.fact_id, f.value, f.supersedes_fact_id) == (second_id, 254000, first_id)
    assert lookup(conn3, period="FY25", ctx=ctx3, as_first_reported=True).fact_id == original_id


def test_unrestated_comparative_must_agree_with_the_original(conn, ctx):
    # A later document that reprints the ORIGINAL figure (not marked restated) must agree with it.
    load(conn, ctx, ar_row(period="FY25"))
    load(conn, ctx, fs_row(period="FY25"))   # same value -> fine
    assert len(lookup(conn, period="FY25").cross_checked_by) == 1


# ---------- config: accounting standards and printed rounding ----------


def test_configured_standards(ctx):
    assert accounting_standard_for(ctx.sources[AR], 167) == "Ind AS"
    assert accounting_standard_for(ctx.sources[FS], 21) == "Ind AS"
    assert accounting_standard_for(ctx.sources[FS], 22) == "Ind AS"
    for page in (14, 16, 17, 18, 20):
        assert accounting_standard_for(ctx.sources[FS], page) == "IFRS"
    assert accounting_standard_for(ctx.sources[FS], 4) is None


def test_sources_have_period_covered(ctx):
    assert ctx.sources[AR]["period_covered"] == "FY26"
    assert ctx.sources[FS]["period_covered"] == "Q1 FY27"


def _config_with(tmp_path, mutate):
    cfg = yaml.safe_load(COMPANY_CONFIG.read_text())
    mutate(cfg)
    path = tmp_path / "company.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


@pytest.mark.parametrize("mutate, words", [
    (lambda c: c["sources"][0].update(accounting_standard="GAAP"), "GAAP"),
    (lambda c: c["sources"][0].pop("accounting_standard"), "accounting_standard"),
    (lambda c: c["sources"][1]["accounting_standard_by_page"]["IFRS"].append(21), "21"),
    (lambda c: c["sources"][0].update(period_covered="2025-26"), "period_covered"),
    (lambda c: c.pop("reporting_rounding"), "reporting_rounding"),
])
def test_bad_source_config_is_rejected(tmp_path, mutate, words):
    path = _config_with(tmp_path, mutate)
    with pytest.raises(ConfigError, match=words):
        load_context(path, METRICS_CONFIG, HASHES_FILE, raw_dir=None)


def test_unit_without_configured_rounding_is_rejected(conn, ctx):
    del ctx.reporting_rounding["INR_MILLION"]
    assert_rejected(conn, ctx, [ar_row(reported_value="2670210", reported_unit="INR_MILLION")],
                    "rounding", "INR_MILLION")
