"""get_financial_fact: look up exactly one stored fact, with its provenance.

Plain typed function, no LLM inside. It never guesses: if the fact for that metric,
period and basis is not in the database, it raises. It does not fall back to another
period, basis or source, and it does not estimate.
"""
import sqlite3
from datetime import date

from pydantic import BaseModel

from erp.periods import resolve_period

BASES = ("consolidated", "standalone")


class FactLookupError(LookupError):
    pass


class UnknownMetricError(FactLookupError):
    pass


class FactNotFoundError(FactLookupError):
    pass


class AmbiguousFactError(FactLookupError):
    """More than one current fact matches (e.g. the same figure from two documents)."""


class FactResult(BaseModel):
    fact_id: int
    ticker: str
    metric_id: str
    period_label: str
    period_start: date
    period_end: date
    basis: str
    # canonical
    value: float
    unit: str
    currency: str
    # as reported
    reported_value: float
    reported_unit: str
    conversion_factor: float
    # source
    source_id: int
    source_title: str
    source_doc_type: str
    source_file: str | None          # local path inside the private data checkout
    source_page: int                 # PDF page index (1-based)
    source_page_label: str | None    # page number printed on the page, if different
    source_locator: str | None
    # provenance
    entry_method: str
    entered_by: str
    verified_by: str | None
    verified_on: str | None
    verified: bool                   # True only if a human has filled verified_by


def company_info(conn: sqlite3.Connection, ticker: str) -> tuple[int, int]:
    row = conn.execute(
        "SELECT company_id, fiscal_year_end_month FROM company WHERE ticker_nse = ?", (ticker,)).fetchone()
    if row is None:
        raise FactLookupError(f"unknown company ticker {ticker!r}")
    return row


def get_financial_fact(conn: sqlite3.Connection, ticker: str, metric_id: str, period_label: str,
                       basis: str = "consolidated") -> FactResult:
    if basis not in BASES:
        raise FactLookupError(f"basis must be one of {BASES}, got {basis!r}")
    company_id, fy_end_month = company_info(conn, ticker)
    period = resolve_period(period_label, fy_end_month)   # raises PeriodError for unknown labels
    if conn.execute("SELECT 1 FROM metric WHERE metric_id = ?", (metric_id,)).fetchone() is None:
        raise UnknownMetricError(f"unknown metric {metric_id!r} (not in config/metrics.yaml)")

    db_period = conn.execute(
        "SELECT period_id, start_date, end_date FROM period WHERE company_id = ? AND label = ?",
        (company_id, period.label)).fetchone()
    if db_period is None:
        raise FactNotFoundError(
            f"no {basis} {metric_id} fact for {ticker} {period.label}: period not in the database")
    period_id, start, end = db_period
    if (start, end) != (period.start_date.isoformat(), period.end_date.isoformat()):
        # Should be impossible: config periods are checked against the resolver at load time.
        raise FactLookupError(f"period {period.label!r} in the database has dates {start}..{end}, "
                              f"expected {period.start_date}..{period.end_date}")

    rows = conn.execute(
        "SELECT f.fact_id, f.value, f.unit, f.currency, f.reported_value, f.reported_unit,"
        " f.conversion_factor, f.source_id, s.title, s.doc_type, s.local_path, f.source_page,"
        " f.source_page_label, f.source_locator, f.entry_method, f.entered_by, f.verified_by,"
        " f.verified_on"
        " FROM fact_current f JOIN source_document s USING (source_id)"
        " WHERE f.company_id = ? AND f.metric_id = ? AND f.period_id = ? AND f.basis = ?"
        " ORDER BY f.fact_id",
        (company_id, metric_id, period_id, basis)).fetchall()
    if not rows:
        raise FactNotFoundError(f"no {basis} {metric_id} fact for {ticker} {period.label}")
    if len(rows) > 1:
        # TO VERIFY (author decision): which source wins when two documents print the same
        # figure (e.g. this year's and next year's annual report). Until decided, refuse.
        raise AmbiguousFactError(
            f"{len(rows)} facts match {basis} {metric_id} {ticker} {period.label} "
            f"(fact_ids {[r[0] for r in rows]}); no rule yet for choosing between sources")

    (fact_id, value, unit, currency, reported_value, reported_unit, factor, source_id, title,
     doc_type, local_path, page, page_label, locator, entry_method, entered_by, verified_by,
     verified_on) = rows[0]
    return FactResult(
        fact_id=fact_id, ticker=ticker, metric_id=metric_id, period_label=period.label,
        period_start=period.start_date, period_end=period.end_date, basis=basis,
        value=value, unit=unit, currency=currency,
        reported_value=reported_value, reported_unit=reported_unit, conversion_factor=factor,
        source_id=source_id, source_title=title, source_doc_type=doc_type, source_file=local_path,
        source_page=page, source_page_label=page_label, source_locator=locator,
        entry_method=entry_method, entered_by=entered_by,
        verified_by=verified_by, verified_on=verified_on, verified=bool(verified_by),
    )
