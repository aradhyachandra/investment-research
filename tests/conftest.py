import csv
import sqlite3
from pathlib import Path

import pytest

from erp.config import load_context
from erp.db.load_facts import create_db, seed_reference_data

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


def fact_count(c: sqlite3.Connection) -> int:
    return c.execute("SELECT COUNT(*) FROM fact").fetchone()[0]
