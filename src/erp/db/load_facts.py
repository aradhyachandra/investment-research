"""Load a facts CSV into SQLite.

Steps: build schema -> seed reference tables from config (company, metric, period,
source_document) -> validate every CSV row -> insert all facts in one transaction.
If any row fails, nothing is written (all-or-nothing) and every problem is reported.

Run from the repo root:
    PYTHONPATH=src python -m erp.db.load_facts --csv data/sample/facts_sample.csv \
        --entry-method llm_extracted --db data/db/sample.sqlite --replace
"""
import argparse
import csv
import sqlite3
import sys
from pathlib import Path

from erp.config import LoadContext, load_context
from erp.db.validate import Fact, validate_rows

SCHEMA = Path(__file__).with_name("schema.sql")
ENTRY_METHODS = ("manual", "parsed", "llm_extracted")


class LoadError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("load rejected:\n  " + "\n  ".join(errors))


def create_db(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA.read_text())
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def seed_reference_data(conn: sqlite3.Connection, ctx: LoadContext) -> None:
    c = ctx.company
    with conn:
        cur = conn.execute(
            "INSERT INTO company (ticker_nse, ticker_bse, isin, name, fiscal_year_end_month, reporting_currency)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (c["ticker_nse"], c.get("ticker_bse"), c.get("isin"), c["name"],
             c["fiscal_year_end_month"], c["reporting_currency"]),
        )
        company_id = cur.lastrowid
        for metric_id, m in ctx.metrics.items():
            conn.execute(
                "INSERT INTO metric (metric_id, display_name, statement, unit_kind, canonical_unit, is_flow, definition)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (metric_id, m["display_name"], m["statement"], m["unit_kind"],
                 m["canonical_unit"], m["is_flow"], m["definition"].strip()),
            )
        for p in ctx.periods.values():
            conn.execute(
                "INSERT INTO period (company_id, period_type, fiscal_year, label, start_date, end_date)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (company_id, p["period_type"], p["fiscal_year"], p["label"], p["start_date"], p["end_date"]),
            )
        for s in ctx.sources.values():
            conn.execute(
                "INSERT INTO source_document (company_id, doc_type, title, publisher, url, local_path,"
                " published_date, period_covered, sha256, retrieved_on, licence_note)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (company_id, s["doc_type"], s["title"], s["publisher"], s.get("url"), s["local_path"],
                 s.get("published_date"), s.get("period_covered"), s["sha256"], s["retrieved_on"],
                 s.get("licence_note")),
            )


def _ids(conn, fact: Fact):
    """Look up the foreign keys for a validated fact."""
    company_id = conn.execute(
        "SELECT company_id FROM company WHERE ticker_nse = ?", (fact.ticker,)).fetchone()[0]
    period_id = conn.execute(
        "SELECT period_id FROM period WHERE company_id = ? AND label = ?",
        (company_id, fact.period_label)).fetchone()[0]
    source_id = conn.execute(
        "SELECT source_id FROM source_document WHERE company_id = ? AND local_path = ?",
        (company_id, f"data/raw/{fact.source_doc}")).fetchone()[0]
    return company_id, period_id, source_id


def load_rows(conn: sqlite3.Connection, rows: list[dict], ctx: LoadContext, entry_method: str) -> list[int]:
    """Validate and insert rows. Returns the new fact_ids. Raises LoadError on any problem."""
    if entry_method not in ENTRY_METHODS:
        raise LoadError([f"entry_method must be one of {ENTRY_METHODS}, got {entry_method!r}"])

    facts, errors = validate_rows(rows, ctx)
    if errors:
        raise LoadError(errors)

    keyed = [(f, _ids(conn, f)) for f in facts]
    for f, (company_id, period_id, source_id) in keyed:
        existing = conn.execute(
            "SELECT fact_id FROM fact WHERE company_id = ? AND metric_id = ? AND period_id = ?"
            " AND basis = ? AND source_id = ?",
            (company_id, f.metric_id, period_id, f.basis, source_id)).fetchone()
        if existing:
            errors.append(f"row {f.row_number}: duplicate of fact_id {existing[0]} already in the database")
    if errors:
        raise LoadError(errors)

    fact_ids = []
    try:
        with conn:
            for f, (company_id, period_id, source_id) in keyed:
                cur = conn.execute(
                    "INSERT INTO fact (company_id, metric_id, period_id, basis, value, unit, reported_value,"
                    " reported_unit, conversion_factor, source_id, source_page, source_page_label,"
                    " entry_method, entered_by, verified_by)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                    (company_id, f.metric_id, period_id, f.basis, f.value, f.unit, f.reported_value,
                     f.reported_unit, f.conversion_factor, source_id, f.source_page, f.source_page_label,
                     entry_method, f.entered_by),
                )
                fact_ids.append(cur.lastrowid)
    except sqlite3.IntegrityError as e:  # backstop; the checks above should catch these first
        raise LoadError([f"database rejected the load (duplicate or bad reference): {e}"]) from e
    return fact_ids


def read_csv(csv_path) -> list[dict]:
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


def load_facts_csv(conn, csv_path, ctx: LoadContext, entry_method: str) -> list[int]:
    return load_rows(conn, read_csv(csv_path), ctx, entry_method)


def print_summary(conn: sqlite3.Connection) -> None:
    print("\nSource documents:")
    for sid, doc_type, title, sha in conn.execute(
            "SELECT source_id, doc_type, title, sha256 FROM source_document ORDER BY source_id"):
        print(f"  [{sid}] {doc_type:<14} {title}  (sha256 {sha[:12]}...)")
    print("\nFacts loaded:")
    print(f"  {'metric':<26}{'period':<8}{'value':>14}  {'unit':<15}{'page (printed)':<16}entry / verified")
    for metric, label, value, unit, page, plabel, method, verified in conn.execute(
            "SELECT f.metric_id, p.label, f.value, f.unit, f.source_page, f.source_page_label,"
            " f.entry_method, f.verified_by FROM fact f JOIN period p USING (period_id)"
            " ORDER BY f.metric_id, p.end_date"):
        page_text = f"{page} ({plabel})" if plabel else str(page)
        print(f"  {metric:<26}{label:<8}{value:>14,.2f}  {unit:<15}{page_text:<16}{method} / {verified or 'NOT VERIFIED'}")
    total, unverified = conn.execute(
        "SELECT COUNT(*), SUM(verified_by IS NULL) FROM fact").fetchone()
    print(f"\n{total} facts loaded, {unverified} not yet verified by a human.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Load a facts CSV into SQLite with validation.")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--entry-method", required=True, choices=ENTRY_METHODS,
                    help="how the CSV numbers were entered (not stored in the CSV itself)")
    ap.add_argument("--db", default="data/db/sample.sqlite")
    ap.add_argument("--replace", action="store_true", help="delete and rebuild the database if it exists")
    ap.add_argument("--company-config", default="config/companies/tcs.yaml")
    ap.add_argument("--metrics-config", default="config/metrics.yaml")
    ap.add_argument("--hashes", default="sources_hashes.txt")
    ap.add_argument("--raw-dir", default="data/raw", help="folder with source PDFs, used to re-check sha256")
    args = ap.parse_args(argv)

    db = Path(args.db)
    if db.exists():
        if not args.replace:
            print(f"{db} already exists; pass --replace to rebuild it.", file=sys.stderr)
            return 2
        db.unlink()
    db.parent.mkdir(parents=True, exist_ok=True)

    ctx = load_context(args.company_config, args.metrics_config, args.hashes, raw_dir=args.raw_dir)
    conn = create_db(db)
    try:
        seed_reference_data(conn, ctx)
        load_facts_csv(conn, args.csv, ctx, args.entry_method)
    except LoadError as e:
        conn.close()
        db.unlink()  # never leave a half-loaded database behind
        print(e, file=sys.stderr)
        return 1
    print(f"Loaded {args.csv} into {db}")
    print_summary(conn)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
