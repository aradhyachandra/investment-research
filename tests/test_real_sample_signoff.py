"""The author's real sample facts load cleanly and carry a human verification (signed off 2026-10-07)."""
import csv

from conftest import REAL_SAMPLE_CSV, SAMPLE_CSV


def _rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_real_sample_rows_are_verified_by_someone_other_than_the_enterer():
    rows = _rows(REAL_SAMPLE_CSV)
    assert len(rows) == 12
    for r in rows:
        assert r["verified_by"] and r["verified_on"]
        assert r["verified_by"].casefold() != r["entered_by"].casefold()


def test_real_and_fixture_numbers_are_identical():
    key = lambda r: (r["metric_id"], r["period"], r["basis"], r["reported_value"], r["reported_unit"], r["source_page"])
    assert sorted(map(key, _rows(REAL_SAMPLE_CSV))) == sorted(map(key, _rows(SAMPLE_CSV)))
