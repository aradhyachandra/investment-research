"""Load-time validation (PROJECT_PLAN.md Sections 4.1 and 4.4).

Two steps:
  validate_rows: raw CSV rows -> Fact objects, deriving value/unit/conversion_factor
                 from config, and collecting every problem found (not just the first).
  check_fact:    rules every derived Fact must satisfy (unit = canonical unit,
                 value = reported_value * conversion_factor, page present, plausibility band).
                 Kept separate so a bug in the derivation step is still caught.
"""
import math
from dataclasses import dataclass
from datetime import date

from erp.config import LoadContext, accounting_standard_for
from erp.units import UnitError, conversion_factor

BASES = ("consolidated", "standalone")
CSV_COLUMNS = (
    "ticker", "metric_id", "period", "basis", "reported_value", "reported_unit",
    "source_doc", "source_page", "source_page_label", "entered_by",
)
# Optional: the author fills these after checking a row against the PDF. Blank = not verified.
# restated = 1 with supersedes_source_doc = the document whose figure this row replaces
# (same metric, period, basis and accounting standard). Blank = an ordinary row.
OPTIONAL_COLUMNS = ("verified_by", "verified_on", "restated", "supersedes_source_doc")


@dataclass(frozen=True)
class Fact:
    row_number: int            # line in the CSV (header = 1)
    ticker: str
    metric_id: str
    period_label: str
    basis: str
    value: float               # canonical unit
    unit: str                  # canonical unit
    reported_value: float
    reported_unit: str
    conversion_factor: float
    source_doc: str
    source_page: int
    source_page_label: str | None
    entered_by: str
    verified_by: str | None = None
    verified_on: str | None = None     # ISO date
    accounting_standard: str = ""      # of the cited page, from the source config
    tolerance: float = 0.0             # half the printing step, in the canonical unit
    restated: bool = False
    supersedes_source_doc: str | None = None

    def key(self):
        """Same fields as the fact table's UNIQUE constraint."""
        return (self.ticker, self.metric_id, self.period_label, self.basis, self.source_doc)


def _parse_page(text: str):
    text = (text or "").strip()
    if not text.isdigit() or int(text) < 1:
        return None
    return int(text)


def _parse_number(text: str):
    try:
        number = float((text or "").strip())
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _check_verification(verified_by: str, verified_on: str, entered_by: str) -> list[str]:
    """Both blank (unverified) or both filled, by someone other than the person who entered it."""
    errors = []
    if verified_on:
        try:
            date.fromisoformat(verified_on)
        except ValueError:
            errors.append(f"verified_on {verified_on!r} is not an ISO date (YYYY-MM-DD)")
        if not verified_by:
            errors.append("verified_on is set but verified_by is empty")
    elif verified_by:
        errors.append("verified_by is set but verified_on is empty")
    if verified_by and verified_by.casefold() == entered_by.casefold():
        errors.append("verified_by must be a different person from entered_by")
    return errors


def _check_restatement(restated: str, supersedes: str, source_doc: str, ctx: LoadContext) -> list[str]:
    if restated not in ("", "0", "1"):
        return [f"restated must be 1, 0 or blank, got {restated!r}"]
    if restated == "1":
        if not supersedes:
            return ["restated = 1 needs supersedes_source_doc (the document whose figure it replaces)"]
        if supersedes not in ctx.sources:
            return [f"supersedes_source_doc {supersedes!r} is not a known source document"]
        if supersedes == source_doc:
            return ["supersedes_source_doc cannot be the row's own source_doc"]
    elif supersedes:
        return ["supersedes_source_doc is set but restated is not 1"]
    return []


def check_fact(fact: Fact, ctx: LoadContext) -> list[str]:
    errors = []
    metric = ctx.metrics[fact.metric_id]
    if fact.unit != metric["canonical_unit"]:
        errors.append(f"unit {fact.unit!r} is not the canonical unit {metric['canonical_unit']!r}")
    if not math.isclose(fact.value, fact.reported_value * fact.conversion_factor, rel_tol=1e-9):
        errors.append("value does not equal reported_value * conversion_factor")
    if not fact.source_page or fact.source_page < 1:
        errors.append("source_page missing")
    if metric.get("sign") == "outflow_positive" and fact.value < 0:
        errors.append(f"{fact.metric_id} is a cash outflow and must be stored as a positive amount "
                      f"(the statement prints it in brackets), got {fact.value:,}")
    band = ctx.bands[fact.metric_id]
    if not band["min"] <= fact.value <= band["max"]:
        errors.append(
            f"value {fact.value:,} {fact.unit} is outside the plausibility band "
            f"[{band['min']:,}, {band['max']:,}] for {fact.metric_id} (unit slip?)"
        )
    return errors


def validate_row(row: dict, row_number: int, ctx: LoadContext) -> tuple[Fact | None, list[str]]:
    errors = []
    get = lambda col: (row.get(col) or "").strip()

    missing_cols = [c for c in CSV_COLUMNS if c not in row]
    if missing_cols:
        return None, [f"missing columns {missing_cols}"]

    if get("ticker") != ctx.company["ticker_nse"]:
        errors.append(f"unknown ticker {get('ticker')!r}")
    metric = ctx.metrics.get(get("metric_id"))
    if metric is None:
        errors.append(f"unknown metric {get('metric_id')!r} (not in config/metrics.yaml)")
    if get("period") not in ctx.periods:
        errors.append(f"unknown period {get('period')!r} (no dates configured for it)")
    if row.get("basis") not in BASES:
        errors.append(f"basis must be one of {BASES}, got {row.get('basis')!r}")
    source = ctx.sources.get(get("source_doc"))
    if source is None:
        errors.append(f"unknown source_doc {get('source_doc')!r} (not in company config)")
    elif source["doc_type"] == "generated_sample":
        errors.append(f"source_doc {get('source_doc')!r} is generated_sample; generated notes never supply numbers")
    if not get("entered_by"):
        errors.append("entered_by is empty")
    errors += _check_verification(get("verified_by"), get("verified_on"), get("entered_by"))
    errors += _check_restatement(get("restated"), get("supersedes_source_doc"), get("source_doc"), ctx)

    reported_value = _parse_number(row.get("reported_value"))
    if reported_value is None:
        errors.append(f"reported_value {row.get('reported_value')!r} is not a plain number")
    page = _parse_page(row.get("source_page"))
    if page is None:
        errors.append(f"source_page {row.get('source_page')!r} missing or not a positive whole number")

    standard = None
    if source is not None and page is not None:
        standard = accounting_standard_for(source, page)
        if standard is None:
            errors.append(f"no accounting standard configured for page {page} of {get('source_doc')!r} "
                          f"(add it to accounting_standard_by_page in the company config)")

    factor = None
    reported_unit = get("reported_unit")
    step = ctx.reporting_rounding.get(reported_unit)
    if reported_unit and step is None:
        errors.append(f"no reporting_rounding configured for reported unit {reported_unit!r}")
    if metric is not None:
        try:
            factor = conversion_factor(reported_unit, metric["canonical_unit"])
        except UnitError as e:
            errors.append(f"unit: {e} (metric {get('metric_id')})")

    if errors:
        return None, errors

    fact = Fact(
        row_number=row_number,
        ticker=get("ticker"),
        metric_id=get("metric_id"),
        period_label=get("period"),
        basis=row["basis"],
        value=reported_value * factor,
        unit=metric["canonical_unit"],
        reported_value=reported_value,
        reported_unit=reported_unit,
        conversion_factor=factor,
        source_doc=get("source_doc"),
        source_page=page,
        source_page_label=get("source_page_label") or None,
        entered_by=get("entered_by"),
        verified_by=get("verified_by") or None,
        verified_on=get("verified_on") or None,
        accounting_standard=standard,
        tolerance=step * factor / 2,
        restated=get("restated") == "1",
        supersedes_source_doc=get("supersedes_source_doc") or None,
    )
    return fact, check_fact(fact, ctx)


def validate_rows(rows: list[dict], ctx: LoadContext) -> tuple[list[Fact], list[str]]:
    """Return (facts, errors). Errors are prefixed with the CSV row number."""
    facts, errors, seen = [], [], {}
    for i, row in enumerate(rows):
        row_number = i + 2  # header is row 1
        fact, row_errors = validate_row(row, row_number, ctx)
        errors += [f"row {row_number}: {e}" for e in row_errors]
        if fact is None or row_errors:
            continue
        if fact.key() in seen:
            errors.append(f"row {row_number}: duplicate of row {seen[fact.key()]} {fact.key()}")
            continue
        seen[fact.key()] = row_number
        facts.append(fact)
    return facts, errors
