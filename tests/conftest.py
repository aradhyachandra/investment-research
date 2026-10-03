import csv
import sqlite3
from pathlib import Path

import pytest

from erp.config import load_context
from erp.db.load_facts import create_db, load_rows, seed_reference_data

REPO = Path(__file__).resolve().parent.parent
SAMPLE_CSV = REPO / "data" / "sample" / "facts_sample.csv"
COMPANY_CONFIG = REPO / "config" / "companies" / "tcs.yaml"
METRICS_CONFIG = REPO / "config" / "metrics.yaml"
HASHES_FILE = REPO / "sources_hashes.txt"


def read_sample_rows():
    with open(SAMPLE_CSV, newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture
def ctx():
    # raw_dir=None: tests must not depend on the private PDFs being checked out.
    return load_context(COMPANY_CONFIG, METRICS_CONFIG, HASHES_FILE, raw_dir=None)


@pytest.fixture
def conn(ctx):
    c = create_db(":memory:")
    seed_reference_data(c, ctx)
    yield c
    c.close()


@pytest.fixture
def good_row():
    """First sample row (FY26 revenue), as a fresh dict tests can modify."""
    return dict(read_sample_rows()[0])


@pytest.fixture
def loaded(conn, ctx):
    """In-memory DB with the 10 sample facts loaded (all llm_extracted, unverified)."""
    load_rows(conn, read_sample_rows(), ctx, entry_method="llm_extracted")
    return conn


def sample_row(metric_id, period):
    """A fresh copy of the sample CSV row for one metric and period."""
    for row in read_sample_rows():
        if row["metric_id"] == metric_id and row["period"] == period:
            return dict(row)
    raise KeyError((metric_id, period))


def fact_count(c: sqlite3.Connection) -> int:
    return c.execute("SELECT COUNT(*) FROM fact").fetchone()[0]
