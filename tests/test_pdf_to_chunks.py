"""M4: PDF -> chunks. Page numbers must be right, because every citation depends on them."""
from pathlib import Path

import pytest

from erp.ingest.pdf_to_chunks import extract_chunks, load_ingest_config
from pdf_fixtures import build_pdf, sentences

REPO = Path(__file__).resolve().parent.parent
REAL_AR = REPO / "data" / "raw" / "tcs_annual_report_FY26.pdf"


@pytest.fixture(scope="module")
def cfg():
    return load_ingest_config()


@pytest.fixture
def three_pages(tmp_path):
    return build_pdf(tmp_path / "three.pdf", [
        {"blocks": [("h", "Alpha Section"), ("p", sentences("alphaword", 6))], "footer": None},
        {"blocks": [("h", "Bravo Section"), ("p", sentences("bravoword", 6))], "footer": "10"},
        {"blocks": [("p", sentences("charlieword", 6))], "footer": "11"},
    ])


def test_each_chunk_carries_the_page_its_text_is_on(three_pages, cfg):
    chunks = extract_chunks(three_pages, settings=cfg).chunks
    marker_page = {"alphaword": 1, "bravoword": 2, "charlieword": 3}
    seen = set()
    for c in chunks:
        assert c.page == c.page_end
        for marker, page in marker_page.items():
            if marker in c.text:
                assert c.page == page, (marker, c.page)
                seen.add(marker)
    assert seen == set(marker_page)


def test_pages_are_one_based_and_never_missing(three_pages, cfg):
    chunks = extract_chunks(three_pages, settings=cfg).chunks
    assert chunks and all(isinstance(c.page, int) and c.page >= 1 for c in chunks)
    assert {c.page for c in chunks} == {1, 2, 3}


def test_page_labels_come_from_config_ranges(three_pages, cfg):
    labels = [{"pdf_pages": [2, 3], "first_printed": 10}]
    chunks = extract_chunks(three_pages, page_labels=labels, settings=cfg).chunks
    by_page = {c.page: c.page_label for c in chunks}
    assert by_page == {1: "", 2: "10", 3: "11"}


def test_no_page_labels_config_means_empty_labels(three_pages, cfg):
    # The footer is NOT trusted on its own (on the real report it drops digits).
    chunks = extract_chunks(three_pages, settings=cfg).chunks
    assert {c.page_label for c in chunks} == {""}


def test_footer_disagreeing_with_config_is_reported(three_pages, cfg):
    labels = [{"pdf_pages": [2, 3], "first_printed": 20}]   # footers say 10, 11
    result = extract_chunks(three_pages, page_labels=labels, settings=cfg)
    assert len(result.label_warnings) == 2
    assert "PDF page 2" in result.label_warnings[0] and "10" in result.label_warnings[0]


def test_footer_agreeing_with_config_gives_no_warning(three_pages, cfg):
    labels = [{"pdf_pages": [2, 3], "first_printed": 10}]
    assert extract_chunks(three_pages, page_labels=labels, settings=cfg).label_warnings == []


def test_running_header_and_page_number_are_not_in_chunk_text(three_pages, cfg):
    for c in extract_chunks(three_pages, settings=cfg).chunks:
        assert "Statutory Reports" not in c.text
        assert c.text.strip() not in ("10", "11")


def test_section_comes_from_heading_and_carries_to_next_page(three_pages, cfg):
    chunks = extract_chunks(three_pages, settings=cfg).chunks
    by_page = {c.page: c.section for c in chunks}
    assert by_page == {1: "Alpha Section", 2: "Bravo Section", 3: "Bravo Section"}


def test_two_page_spread_is_split_and_labelled_per_half(tmp_path, cfg):
    pdf = build_pdf(tmp_path / "spread.pdf", [
        {"blocks": [("p", sentences("coverword", 3))]},
        {"left": [("h", "Left Story"), ("p", sentences("leftword", 5))],
         "right": [("h", "Right Story"), ("p", sentences("rightword", 5))],
         "footers": ("4", "5")},
    ])
    labels = [{"pdf_pages": [2, 2], "first_printed": 4, "per_pdf_page": 2}]
    result = extract_chunks(pdf, page_labels=labels, settings=cfg)
    left = [c for c in result.chunks if "leftword" in c.text]
    right = [c for c in result.chunks if "rightword" in c.text]
    assert left and right
    assert all(c.page == 2 and c.page_label == "4" and c.section == "Left Story" for c in left)
    assert all(c.page == 2 and c.page_label == "5" and c.section == "Right Story" for c in right)
    assert not any("rightword" in c.text for c in left)
    assert result.label_warnings == []


def test_long_section_is_split_with_overlap(tmp_path, cfg):
    pdf = build_pdf(tmp_path / "long.pdf", [
        {"blocks": [("h", "Long Section"), ("p", sentences("deltaword", 40))]},
    ])
    chunks = extract_chunks(pdf, settings=cfg).chunks
    assert len(chunks) >= 2
    limit = cfg["chunking"]["max_chars"]
    for a, b in zip(chunks, chunks[1:]):
        assert len(a.text) <= limit + 200      # a chunk may overrun by at most one line
        tail = a.text[-60:]
        assert tail in b.text                  # the end of one chunk starts the next
    assert all(c.section == "Long Section" for c in chunks)


def test_short_page_tail_joins_next_page_and_stores_range(tmp_path, cfg):
    pdf = build_pdf(tmp_path / "tail.pdf", [
        {"blocks": [("h", "First"), ("p", sentences("echoword", 12)),
                    ("h", "Carried Section"), ("p", "Short tailword start.")], "footer": "40"},
        {"blocks": [("p", sentences("foxtrotword", 4))], "footer": "41"},
    ])
    labels = [{"pdf_pages": [1, 2], "first_printed": 40}]
    chunks = extract_chunks(pdf, page_labels=labels, settings=cfg).chunks
    joined = [c for c in chunks if "tailword" in c.text]
    assert len(joined) == 1
    j = joined[0]
    assert (j.page, j.page_end, j.page_label, j.page_label_end) == (1, 2, "40", "41")
    assert "foxtrotword" in j.text and j.section == "Carried Section"


def test_new_heading_on_next_page_stops_the_join(tmp_path, cfg):
    pdf = build_pdf(tmp_path / "nojoin.pdf", [
        {"blocks": [("h", "First"), ("p", "Short tailword start.")]},
        {"blocks": [("h", "Second"), ("p", sentences("golfword", 4))]},
    ])
    chunks = extract_chunks(pdf, settings=cfg).chunks
    assert all(c.page == c.page_end for c in chunks)
    assert [c.page for c in chunks if "tailword" in c.text] == [1]


def test_numeric_table_page_is_flagged_table_heavy(tmp_path, cfg):
    rows = "\n".join(f"Line item {i}  1,23,{i:03d}  98,{i:03d}  (4,5{i % 10}0)  12.{i}%" for i in range(25))
    pdf = build_pdf(tmp_path / "table.pdf", [
        {"blocks": [("p", rows)]},
        {"blocks": [("p", sentences("prose", 8))]},
    ])
    chunks = extract_chunks(pdf, settings=cfg).chunks
    assert all(c.is_table_heavy for c in chunks if c.page == 1)
    assert not any(c.is_table_heavy for c in chunks if c.page == 2)


def test_empty_pages_produce_no_chunks(tmp_path, cfg):
    pdf = build_pdf(tmp_path / "empty.pdf", [{"blocks": []}, {"blocks": [("p", sentences("x", 3))]}])
    assert {c.page for c in extract_chunks(pdf, settings=cfg).chunks} == {2}


def test_bad_page_label_config_is_refused(three_pages, cfg):
    with pytest.raises(ValueError):
        extract_chunks(three_pages, page_labels=[{"pdf_pages": [3, 2], "first_printed": 1}], settings=cfg)
    with pytest.raises(ValueError):
        extract_chunks(three_pages, page_labels=[{"pdf_pages": [1, 2], "first_printed": 1},
                                                 {"pdf_pages": [2, 3], "first_printed": 5}], settings=cfg)


# --- Real annual report (skipped when the private PDF is not checked out) ---------------------

@pytest.fixture(scope="module")
def real_ar(cfg):
    if not REAL_AR.exists():
        pytest.skip("private annual report PDF not present in data/raw/")
    from erp.config import company_context
    labels = company_context("TCS").sources[REAL_AR.name]["page_labels"]
    return extract_chunks(REAL_AR, page_labels=labels, settings=cfg)


def test_real_ar_known_pages_have_known_labels(real_ar):
    by_page = {}
    for c in real_ar.chunks:
        by_page.setdefault(c.page, set()).add(c.page_label)
    assert by_page[167] == {"197"}      # Consolidated Statement of Profit and Loss
    assert by_page[41] == {"71"}        # Board's Report, item 17 Risk management
    assert by_page[4] == {"4", "5"}     # About the Report spread


def test_real_ar_footers_only_disagree_by_missing_digits(real_ar):
    # Some footer digits are not in the PDF text layer (e.g. "90" reads as "9"). Any other
    # disagreement would mean the configured page_labels are wrong.
    hard = [w for w in real_ar.label_warnings if not w.endswith("(config kept)")]
    assert hard == []


def test_real_ar_risk_heading_detected(real_ar):
    p41 = [c for c in real_ar.chunks if c.page == 41]
    assert any("Risk management" in c.section for c in p41)


def test_real_ar_statement_pages_are_table_heavy(real_ar):
    statement = [c for c in real_ar.chunks if c.page == 167 and "Revenue from operations" in c.text]
    assert statement and all(c.is_table_heavy for c in statement)
    p41 = [c for c in real_ar.chunks if c.page == 41]
    assert p41 and not any(c.is_table_heavy for c in p41)
