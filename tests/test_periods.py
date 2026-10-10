"""M2: period resolver (FY / quarter labels <-> real dates).

TCS's fiscal year ends in March (config/companies/tcs.yaml: fiscal_year_end_month: 3),
so FY26 runs 1 Apr 2025 - 31 Mar 2026 and its quarters are Apr-Jun, Jul-Sep, Oct-Dec, Jan-Mar.
"""
from datetime import date

import pytest
import yaml

from conftest import COMPANY_CONFIG, HASHES_FILE, METRICS_CONFIG
from erp.config import ConfigError, load_context
from erp.periods import PeriodError, label_for_dates, prior_year_label, resolve_period

MARCH = 3  # TCS fiscal year end month, as in the company config


def test_fy26_is_april_2025_to_march_2026():
    p = resolve_period("FY26", MARCH)
    assert p.label == "FY26"
    assert p.period_type == "FY"
    assert p.fiscal_year == 2026
    assert p.start_date == date(2025, 4, 1)
    assert p.end_date == date(2026, 3, 31)


def test_fy25_is_not_calendar_2025():
    p = resolve_period("FY25", MARCH)
    assert (p.start_date, p.end_date) == (date(2024, 4, 1), date(2025, 3, 31))
    assert (p.start_date, p.end_date) != (date(2025, 1, 1), date(2025, 12, 31))
    # 31 Dec 2025 falls in FY26, not FY25.
    fy26 = resolve_period("FY26", MARCH)
    assert fy26.start_date <= date(2025, 12, 31) <= fy26.end_date
    assert not p.start_date <= date(2025, 12, 31) <= p.end_date


@pytest.mark.parametrize("label, start, end", [
    ("Q1 FY27", date(2026, 4, 1), date(2026, 6, 30)),
    ("Q2 FY27", date(2026, 7, 1), date(2026, 9, 30)),
    ("Q3 FY27", date(2026, 10, 1), date(2026, 12, 31)),
    ("Q4 FY27", date(2027, 1, 1), date(2027, 3, 31)),   # Q4 FY27 is in calendar 2027
    ("Q2 FY26", date(2025, 7, 1), date(2025, 9, 30)),   # the example in PROJECT_PLAN.md risk 3
])
def test_quarter_labels(label, start, end):
    p = resolve_period(label, MARCH)
    assert p.period_type == label[:2]
    assert p.fiscal_year == 2000 + int(label[-2:])
    assert (p.start_date, p.end_date) == (start, end)


@pytest.mark.parametrize("label", ["FY25", "FY26", "Q1 FY27", "Q2 FY27", "Q3 FY27", "Q4 FY27"])
def test_dates_back_to_label(label):
    p = resolve_period(label, MARCH)
    assert label_for_dates(p.start_date, p.end_date, MARCH) == label


@pytest.mark.parametrize("start, end", [
    (date(2025, 1, 1), date(2025, 12, 31)),   # calendar 2025 is not a fiscal year
    (date(2025, 4, 1), date(2025, 9, 30)),    # half year: not supported
    (date(2025, 5, 1), date(2025, 7, 31)),    # three months, but not a fiscal quarter
    (date(2026, 3, 31), date(2025, 4, 1)),    # end before start
])
def test_dates_that_are_not_a_period_raise(start, end):
    with pytest.raises(PeriodError):
        label_for_dates(start, end, MARCH)


@pytest.mark.parametrize("label", [
    "CY25", "FY2026", "fy26", "FY 26", "Q5 FY26", "Q0 FY26", "Q2FY26", "H1 FY26", "2025-26", "", "FY26 ",
])
def test_unknown_labels_raise_a_clear_error(label):
    with pytest.raises(PeriodError, match="unknown period label"):
        resolve_period(label, MARCH)


def test_non_string_label_raises():
    with pytest.raises(PeriodError):
        resolve_period(26, MARCH)


@pytest.mark.parametrize("month", [0, 13, -1])
def test_bad_fiscal_year_end_month_raises(month):
    with pytest.raises(PeriodError, match="fiscal_year_end_month"):
        resolve_period("FY26", month)


def test_december_year_end_is_calendar_year():
    # Not TCS; checks the month arithmetic for a company whose year ends in December.
    p = resolve_period("FY25", 12)
    assert (p.start_date, p.end_date) == (date(2025, 1, 1), date(2025, 12, 31))
    q4 = resolve_period("Q4 FY25", 12)
    assert (q4.start_date, q4.end_date) == (date(2025, 10, 1), date(2025, 12, 31))


@pytest.mark.parametrize("label, prior", [
    ("FY26", "FY25"),
    ("FY10", "FY09"),
    ("Q2 FY27", "Q2 FY26"),
    ("Q4 FY26", "Q4 FY25"),
])
def test_prior_year_label(label, prior):
    assert prior_year_label(label, MARCH) == prior


def test_prior_year_of_fy00_is_not_representable():
    with pytest.raises(PeriodError):
        prior_year_label("FY00", MARCH)


# ---------- config periods must agree with the resolver ----------

def _write_company_config(tmp_path, mutate):
    cfg = yaml.safe_load(COMPANY_CONFIG.read_text())
    mutate(cfg)
    path = tmp_path / "company.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


def test_config_periods_agree_with_resolver(ctx):
    for label, p in ctx.periods.items():
        resolved = resolve_period(label, ctx.company["fiscal_year_end_month"])
        assert p["start_date"] == resolved.start_date.isoformat()
        assert p["end_date"] == resolved.end_date.isoformat()


def test_config_period_with_calendar_dates_is_rejected(tmp_path):
    def calendar_fy25(cfg):
        fy25 = next(p for p in cfg["periods"] if p["label"] == "FY25")
        fy25["start_date"] = "2025-01-01"  # FY25 typed as calendar 2025
        fy25["end_date"] = "2025-12-31"
    path = _write_company_config(tmp_path, calendar_fy25)
    with pytest.raises(ConfigError, match="FY25"):
        load_context(path, METRICS_CONFIG, HASHES_FILE, raw_dir=None)


def test_config_period_with_wrong_fiscal_year_is_rejected(tmp_path):
    def wrong_year(cfg):
        next(p for p in cfg["periods"] if p["label"] == "FY26")["fiscal_year"] = 2025
    path = _write_company_config(tmp_path, wrong_year)
    with pytest.raises(ConfigError, match="FY26"):
        load_context(path, METRICS_CONFIG, HASHES_FILE, raw_dir=None)


def test_config_period_with_unknown_label_is_rejected(tmp_path):
    def bad_label(cfg):
        cfg["periods"][0]["label"] = "2024-25"
    path = _write_company_config(tmp_path, bad_label)
    with pytest.raises(ConfigError, match="unknown period label"):
        load_context(path, METRICS_CONFIG, HASHES_FILE, raw_dir=None)
