"""The PROVISIONAL retrieval probes file is well formed (format only; recall is reported by
tests/run_provisional_probes.py, with no pass threshold)."""
from erp.config import company_context
from run_provisional_probes import load_probes

REQUIRED = ("id", "status", "topic", "question", "source_file", "expected_pdf_pages", "evidence_note")


def test_probes_are_labelled_provisional_and_well_formed():
    probes = load_probes()
    assert 8 <= len(probes) <= 15
    sources = company_context("TCS").sources
    assert len({p["id"] for p in probes}) == len(probes)
    for p in probes:
        assert all(k in p for k in REQUIRED), p["id"]
        assert p["status"] == "PROVISIONAL" and p["id"].startswith("PROV-")
        assert p["source_file"] in sources
        pages = p["expected_pdf_pages"]
        assert pages and all(isinstance(n, int) and n >= 1 for n in pages)
