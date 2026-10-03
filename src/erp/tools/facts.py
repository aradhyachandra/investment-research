"""get_financial_fact: look up exactly one stored fact, with its provenance.

Plain typed function, no LLM inside. It never guesses: if the fact for that metric,
period, basis and accounting standard is not in the database, it raises. It does not fall
back to another period, basis, standard or estimate.

When several documents give the same fact (PROJECT_PLAN.md Section 4.1, rule 8):
  - the latest restatement wins by default; as_first_reported=True gives the original;
  - among agreeing figures, the primary source is returned: the document whose
    period_covered is the fact's own period (else the first one loaded); the others are
    listed in cross_checked_by;
  - figures in another accounting standard (e.g. IFRS vs Ind AS) are never mixed in.
"""
import sqlite3
from datetime import date

from pydantic import BaseModel

from erp.config import ACCOUNTING_STANDARDS, LoadContext, accounting_standard_for, company_context
from erp.periods import resolve_period

BASES = ("consolidated", "standalone")


class FactLookupError(LookupError):
    pass


class UnknownMetricError(FactLookupError):
    pass


class FactNotFoundError(FactLookupError):
    pass


class AmbiguousFactError(FactLookupError):
    """Current figures for the same fact disagree (the loader should have prevented this)."""


class CrossCheck(BaseModel):
    """Another document giving the same figure as the returned fact."""
    fact_id: int
    source_id: int
    source_title: str
    source_file: str | None
    source_page: int
    source_page_label: str | None
    value: float
    unit: str
    reported_value: float
    reported_unit: str
    verified: bool


class FactResult(BaseModel):
    fact_id: int
    ticker: str
    metric_id: str
    period_label: str
    period_start: date
    period_end: date
    basis: str
    accounting_standard: str
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
    primary_source: bool             # True if the source document is for this exact period
    cross_checked_by: list[CrossCheck]
    # restatements
    restated: bool
    supersedes_fact_id: int | None
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


_COLUMNS = (
    "fact_id", "value", "unit", "currency", "reported_value", "reported_unit", "conversion_factor",
    "source_id", "source_title", "source_doc_type", "source_file", "period_covered", "source_page",
    "source_page_label", "source_locator", "entry_method", "entered_by", "verified_by", "verified_on",
    "restated", "supersedes_fact_id",
)


def _rows(conn, company_id, metric_id, period_id, basis) -> list[dict]:
    rows = conn.execute(
        "SELECT f.fact_id, f.value, f.unit, f.currency, f.reported_value, f.reported_unit,"
        " f.conversion_factor, f.source_id, s.title, s.doc_type, s.local_path, s.period_covered,"
        " f.source_page, f.source_page_label, f.source_locator, f.entry_method, f.entered_by,"
        " f.verified_by, f.verified_on, f.restated, f.supersedes_fact_id"
        " FROM fact f JOIN source_document s USING (source_id)"
        " WHERE f.company_id = ? AND f.metric_id = ? AND f.period_id = ? AND f.basis = ?"
        " ORDER BY f.fact_id",
        (company_id, metric_id, period_id, basis)).fetchall()
    return [dict(zip(_COLUMNS, r)) for r in rows]


def _standard_of(row: dict, ctx: LoadContext) -> str:
    name = (row["source_file"] or "").rsplit("/", 1)[-1]
    source = ctx.sources.get(name)
    standard = accounting_standard_for(source, row["source_page"]) if source else None
    if standard is None:
        raise FactLookupError(f"fact_id {row['fact_id']}: no accounting standard configured for "
                              f"page {row['source_page']} of {name!r}")
    return standard


def _agree(a: dict, b: dict, ctx: LoadContext) -> bool:
    tol = sum(ctx.reporting_rounding.get(r["reported_unit"], 0) * r["conversion_factor"] / 2 for r in (a, b))
    return abs(a["value"] - b["value"]) <= tol + 1e-9 * max(abs(a["value"]), abs(b["value"]), 1.0)


def get_financial_fact(conn: sqlite3.Connection, ticker: str, metric_id: str, period_label: str,
                       basis: str = "consolidated", *, accounting_standard: str | None = None,
                       as_first_reported: bool = False, ctx: LoadContext | None = None) -> FactResult:
    """ctx: company config (sources, standards, rounding). Defaults to config/companies/<ticker>.yaml."""
    if basis not in BASES:
        raise FactLookupError(f"basis must be one of {BASES}, got {basis!r}")
    company_id, fy_end_month = company_info(conn, ticker)
    period = resolve_period(period_label, fy_end_month)   # raises PeriodError for unknown labels
    if conn.execute("SELECT 1 FROM metric WHERE metric_id = ?", (metric_id,)).fetchone() is None:
        raise UnknownMetricError(f"unknown metric {metric_id!r} (not in config/metrics.yaml)")
    ctx = ctx or company_context(ticker)
    standard = accounting_standard or ctx.primary_accounting_standard
    if standard not in ACCOUNTING_STANDARDS:
        raise FactLookupError(f"accounting standard {standard!r} is not one of {ACCOUNTING_STANDARDS}")
    what = f"{basis} {metric_id} fact for {ticker} {period.label} ({standard})"

    db_period = conn.execute(
        "SELECT period_id, start_date, end_date FROM period WHERE company_id = ? AND label = ?",
        (company_id, period.label)).fetchone()
    if db_period is None:
        raise FactNotFoundError(f"no {what}: period not in the database")
    period_id, start, end = db_period
    if (start, end) != (period.start_date.isoformat(), period.end_date.isoformat()):
        # Should be impossible: config periods are checked against the resolver at load time.
        raise FactLookupError(f"period {period.label!r} in the database has dates {start}..{end}, "
                              f"expected {period.start_date}..{period.end_date}")

    rows = [r for r in _rows(conn, company_id, metric_id, period_id, basis) if _standard_of(r, ctx) == standard]
    if as_first_reported:
        candidates = [r for r in rows if not r["restated"]]
    else:
        superseded = {r["supersedes_fact_id"] for r in rows if r["supersedes_fact_id"]}
        current = [r for r in rows if r["fact_id"] not in superseded]
        # Once a fact is restated, unrestated reprints of the old figure are no longer current.
        candidates = [r for r in current if r["restated"]] or current
    if not candidates:
        raise FactNotFoundError(f"no {what}")

    # Primary source: the document for this exact period; otherwise the first loaded.
    candidates.sort(key=lambda r: (r["period_covered"] != period.label, r["fact_id"]))
    chosen, others = candidates[0], candidates[1:]
    if any(not _agree(chosen, o, ctx) for o in others):
        raise AmbiguousFactError(
            f"{len(candidates)} current figures for the {what} disagree "
            f"(fact_ids {[r['fact_id'] for r in candidates]}); refusing to pick one")

    return FactResult(
        ticker=ticker, metric_id=metric_id, period_label=period.label,
        period_start=period.start_date, period_end=period.end_date, basis=basis,
        accounting_standard=standard,
        primary_source=chosen["period_covered"] == period.label,
        cross_checked_by=[CrossCheck(
            fact_id=o["fact_id"], source_id=o["source_id"], source_title=o["source_title"],
            source_file=o["source_file"], source_page=o["source_page"],
            source_page_label=o["source_page_label"], value=o["value"], unit=o["unit"],
            reported_value=o["reported_value"], reported_unit=o["reported_unit"],
            verified=bool(o["verified_by"])) for o in others],
        restated=bool(chosen["restated"]),
        verified=bool(chosen["verified_by"]),
        **{k: chosen[k] for k in _COLUMNS if k not in ("period_covered", "restated")},
    )
