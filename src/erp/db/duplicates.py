"""Duplicate-fact policy at load time (PROJECT_PLAN.md Section 4.1, rule 8).

The same fact (same metric, period, basis AND accounting standard) may come from more than
one document. Each new row is compared with the rows already in the database and the rows
before it in the CSV:
  - ordinary row: must agree with every other ordinary row (same value as printed, after unit
    conversion, within printing rounding). Agreeing rows are all kept; they cross-check each other.
  - restated row (restated = 1, supersedes_source_doc = X): the row from X must already exist
    (in the database or earlier in the CSV). It may differ from X. Rows restating the same
    fact must agree with each other.
Anything else that disagrees is rejected, with both values, sources and pages.
"""
from collections import defaultdict
from dataclasses import dataclass

from erp.config import LoadContext, accounting_standard_for
from erp.db.validate import Fact


@dataclass
class Entry:
    """One figure for a fact, from the database or from the CSV being loaded."""
    ref: str                     # 'row 3' or 'fact_id 7', for messages
    source_doc: str
    page: int
    page_label: str | None
    value: float                 # canonical unit
    unit: str
    reported_value: float
    reported_unit: str
    tolerance: float             # half the printing step, canonical unit
    restated: bool
    supersedes: str | None       # source_doc of the figure this one replaces
    fact_id: int | None = None   # set once the row is in the database
    target: "Entry | None" = None


def _fmt(x: float) -> str:
    return f"{x:,.10g}"


def describe(e: Entry) -> str:
    printed = f" (printed {e.page_label})" if e.page_label else ""
    return (f"{_fmt(e.value)} {e.unit} (as printed {_fmt(e.reported_value)} {e.reported_unit}) "
            f"from {e.source_doc} p.{e.page}{printed} [{e.ref}]")


def agree(a: Entry, b: Entry) -> bool:
    slack = 1e-9 * max(abs(a.value), abs(b.value), 1.0)   # float noise only
    return abs(a.value - b.value) <= a.tolerance + b.tolerance + slack


def entry_from_fact(f: Fact) -> Entry:
    return Entry(
        ref=f"row {f.row_number}", source_doc=f.source_doc, page=f.source_page,
        page_label=f.source_page_label, value=f.value, unit=f.unit, reported_value=f.reported_value,
        reported_unit=f.reported_unit, tolerance=f.tolerance, restated=f.restated,
        supersedes=f.supersedes_source_doc,
    )


def group_key(metric_id, period_label, basis, standard):
    return (metric_id, period_label, basis, standard)


def existing_entries(conn, ctx: LoadContext) -> dict:
    """Facts already in the database, grouped by (metric, period, basis, accounting standard)."""
    rows = conn.execute(
        "SELECT f.fact_id, f.metric_id, p.label, f.basis, s.local_path, f.source_page,"
        " f.source_page_label, f.value, f.unit, f.reported_value, f.reported_unit,"
        " f.conversion_factor, f.restated, f.supersedes_fact_id"
        " FROM fact f JOIN period p USING (period_id) JOIN source_document s USING (source_id)"
        " ORDER BY f.fact_id").fetchall()
    doc_of = {r[0]: r[4].rsplit("/", 1)[-1] for r in rows}
    groups = defaultdict(list)
    for (fact_id, metric_id, label, basis, local_path, page, page_label, value, unit, reported_value,
         reported_unit, factor, restated, supersedes_id) in rows:
        name = local_path.rsplit("/", 1)[-1]
        source = ctx.sources.get(name, {})
        step = ctx.reporting_rounding.get(reported_unit, 0)
        groups[group_key(metric_id, label, basis, accounting_standard_for(source, page))].append(Entry(
            ref=f"fact_id {fact_id}", source_doc=name, page=page, page_label=page_label, value=value,
            unit=unit, reported_value=reported_value, reported_unit=reported_unit,
            tolerance=step * factor / 2, restated=bool(restated),
            supersedes=doc_of.get(supersedes_id), fact_id=fact_id,
        ))
    for group in groups.values():   # link restatements to the entries they replace
        for e in group:
            if e.supersedes:
                e.target = next((t for t in group if t.source_doc == e.supersedes), None)
    return groups


def check_new(group: list[Entry], new: Entry, what: str) -> list[str]:
    """Problems with adding `new` to `group`. `what` names the fact, for messages."""
    if new.restated:
        new.target = next((e for e in group if e.source_doc == new.supersedes), None)
        if new.target is None:
            return [f"{new.ref}: supersedes_source_doc {new.supersedes!r}: there is no {what} figure from "
                    f"that document in the database or earlier in this CSV, so there is nothing to restate"]
        peers = [e for e in group if e.restated and e.supersedes == new.supersedes]
    else:
        peers = [e for e in group if not e.restated]
    return [
        f"{new.ref}: {what} disagrees with an existing figure: {describe(new)} vs {describe(e)}. "
        f"If one replaces the other, mark the newer row restated = 1 with supersedes_source_doc."
        for e in peers if not agree(new, e)
    ]


def check_duplicates(conn, facts: list[Fact], ctx: LoadContext) -> tuple[list[Entry], list[str]]:
    """Apply the policy to a batch. Returns one Entry per fact (in order) and any errors."""
    groups = existing_entries(conn, ctx)
    entries, errors = [], []
    for f in facts:
        e = entry_from_fact(f)
        what = f"{f.metric_id} {f.period_label} {f.basis} ({f.accounting_standard})"
        group = groups[group_key(f.metric_id, f.period_label, f.basis, f.accounting_standard)]
        errors += check_new(group, e, what)
        group.append(e)
        entries.append(e)
    return entries, errors
