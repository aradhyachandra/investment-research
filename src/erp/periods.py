"""Period resolver: period labels <-> real start/end dates.

Two label shapes are accepted, exactly as written (no other spellings):
    'FY26'     fiscal year ending in 2026
    'Q2 FY27'  second quarter of FY27

The fiscal year end month is company-specific, so callers pass it in (from the company
config or the `company` table). For TCS it is March, so FY26 = 1 Apr 2025 - 31 Mar 2026
and Q2 FY27 = 1 Jul 2026 - 30 Sep 2026.

Two-digit years mean 20xx (FY26 = 2026). Labels before 2000 are not supported.
"""
import calendar
import re
from datetime import date

from pydantic import BaseModel, ConfigDict

_FY = re.compile(r"FY(\d{2})")
_QUARTER = re.compile(r"Q([1-4]) FY(\d{2})")


class PeriodError(ValueError):
    pass


class Period(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    period_type: str      # 'FY', 'Q1', 'Q2', 'Q3', 'Q4' (same values as the period table)
    fiscal_year: int      # FY ending March 2026 -> 2026
    start_date: date
    end_date: date


def _add_months(year: int, month: int, n: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + n
    return index // 12, index % 12 + 1


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _check_end_month(fiscal_year_end_month) -> None:
    if not isinstance(fiscal_year_end_month, int) or not 1 <= fiscal_year_end_month <= 12:
        raise PeriodError(f"fiscal_year_end_month must be 1-12, got {fiscal_year_end_month!r}")


def _make_label(period_type: str, fiscal_year: int) -> str:
    fy = f"FY{fiscal_year % 100:02d}"
    return fy if period_type == "FY" else f"{period_type} {fy}"


def _build(period_type: str, fiscal_year: int, fiscal_year_end_month: int) -> Period:
    # The fiscal year starts the month after the previous fiscal year ended.
    start_year, start_month = _add_months(fiscal_year - 1, fiscal_year_end_month, 1)
    if period_type == "FY":
        first, months = 0, 12
    else:
        first, months = 3 * (int(period_type[1]) - 1), 3
    y, m = _add_months(start_year, start_month, first)
    end_y, end_m = _add_months(y, m, months - 1)
    return Period(
        label=_make_label(period_type, fiscal_year),
        period_type=period_type,
        fiscal_year=fiscal_year,
        start_date=date(y, m, 1),
        end_date=_month_end(end_y, end_m),
    )


def resolve_period(label: str, fiscal_year_end_month: int) -> Period:
    """'FY26' / 'Q2 FY27' -> Period with real dates. Raises PeriodError for anything else."""
    _check_end_month(fiscal_year_end_month)
    if isinstance(label, str):
        if m := _FY.fullmatch(label):
            return _build("FY", 2000 + int(m[1]), fiscal_year_end_month)
        if m := _QUARTER.fullmatch(label):
            return _build(f"Q{m[1]}", 2000 + int(m[2]), fiscal_year_end_month)
    raise PeriodError(
        f"unknown period label {label!r}: expected a fiscal year like 'FY26' "
        f"or a fiscal quarter like 'Q2 FY27'"
    )


def label_for_dates(start_date: date, end_date: date, fiscal_year_end_month: int) -> str:
    """Real dates -> label. The dates must be exactly one fiscal year or one fiscal quarter."""
    _check_end_month(fiscal_year_end_month)
    # The fiscal year containing end_date ends in end_date.year, or the year after
    # if end_date falls after the fiscal year end month.
    fiscal_year = end_date.year + (1 if end_date.month > fiscal_year_end_month else 0)
    for period_type in ("FY", "Q1", "Q2", "Q3", "Q4"):
        p = _build(period_type, fiscal_year, fiscal_year_end_month)
        if (p.start_date, p.end_date) == (start_date, end_date):
            return p.label
    raise PeriodError(
        f"{start_date} to {end_date} is not a fiscal year or fiscal quarter "
        f"(fiscal year ends in month {fiscal_year_end_month})"
    )


def prior_year_label(label: str, fiscal_year_end_month: int) -> str:
    """Same period type, one fiscal year earlier: 'FY26' -> 'FY25', 'Q2 FY27' -> 'Q2 FY26'."""
    p = resolve_period(label, fiscal_year_end_month)
    if p.fiscal_year - 1 < 2000:
        raise PeriodError(f"the year before {label!r} cannot be written as a two-digit 20xx label")
    return _make_label(p.period_type, p.fiscal_year - 1)
