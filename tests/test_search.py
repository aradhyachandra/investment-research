"""M4: search_documents. Plain function, typed output, filters, sorted by score, page always set."""
import pytest

from erp.ingest.index_chroma import add_chunks, open_collection
from erp.ingest.pdf_to_chunks import load_ingest_config
from erp.tools.search import SearchError, SearchResult, search_documents
from fakes import fake_embed


def meta(chunk_id, source_id=1, doc_type="annual_report", fiscal_year=2026, page=5, table=False,
         section="Risks"):
    return {"source_id": source_id, "doc_type": doc_type, "doc_title": f"Doc {source_id}",
            "page": page, "page_end": page, "page_label": str(page + 30), "page_label_end": str(page + 30),
            "section": section, "fiscal_year": fiscal_year, "chunk_id": chunk_id,
            "is_table_heavy": table, "file_sha256": "ab" * 32, "embed_model": "fake"}


CHUNKS = [
    ("Client concentration risk: the top client accounts for a small share of revenue.",
     meta("ar26-1", page=60, section="Risk Management")),
    ("Capital allocation policy: dividends and buyback return cash to shareholders.",
     meta("ar26-2", page=44, section="Financial Capital")),
    ("Attrition and hiring of employees, talent development and reskilling.",
     meta("ar26-3", page=46, section="Human Capital")),
    ("Client concentration in the prior year annual report.",
     meta("ar25-1", source_id=2, fiscal_year=2025, page=58)),
    ("Quarter client metrics: clients above 100 million dollars.",
     meta("fs-1", source_id=3, doc_type="fact_sheet", fiscal_year=2027, page=10)),
]


@pytest.fixture
def collection(tmp_path):
    col = open_collection(tmp_path / "chroma", "test_docs")
    add_chunks(col, CHUNKS, embed_fn=fake_embed)
    return col


def search(collection, query, **kw):
    return search_documents(query, collection=collection, embed_fn=fake_embed, **kw)


def test_returns_typed_results_with_source_and_page(collection):
    results = search(collection, "client concentration risk")
    assert results and all(isinstance(r, SearchResult) for r in results)
    top = results[0]
    assert top.chunk_id == "ar26-1"
    assert (top.source_id, top.doc_title, top.page, top.page_label, top.section) == \
        (1, "Doc 1", 60, "90", "Risk Management")
    assert "Client concentration" in top.text


def test_results_sorted_by_score_descending(collection):
    scores = [r.score for r in search(collection, "client concentration", top_k=5)]
    assert scores == sorted(scores, reverse=True)
    assert len(scores) == 5


def test_top_k_limits_results(collection):
    assert len(search(collection, "client", top_k=2)) == 2


@pytest.mark.parametrize("top_k", [0, -1, 101])
def test_bad_top_k_is_refused(collection, top_k):
    with pytest.raises(SearchError):
        search(collection, "client", top_k=top_k)


def test_empty_query_is_refused(collection):
    with pytest.raises(SearchError):
        search(collection, "  ")


def test_filter_doc_type(collection):
    results = search(collection, "client", doc_type="fact_sheet")
    assert [r.chunk_id for r in results] == ["fs-1"]


def test_filter_fiscal_year(collection):
    results = search(collection, "client concentration", fiscal_year=2025)
    assert [r.chunk_id for r in results] == ["ar25-1"]


def test_filter_source_id(collection):
    results = search(collection, "client", source_id=1, top_k=5)
    assert {r.source_id for r in results} == {1} and len(results) == 3


def test_filters_combine(collection):
    assert search(collection, "client", doc_type="annual_report", fiscal_year=2027) == []
    results = search(collection, "client", doc_type="annual_report", fiscal_year=2026, source_id=1)
    assert {r.chunk_id for r in results} == {"ar26-1", "ar26-2", "ar26-3"}


def test_unknown_doc_type_filter_is_refused(collection):
    with pytest.raises(SearchError):
        search(collection, "client", doc_type="generated_sample")


def test_table_heavy_chunks_are_down_ranked(tmp_path):
    col = open_collection(tmp_path / "c", "test_docs")
    same = "Revenue by geography North America Europe India"
    add_chunks(col, [(same, meta("table", page=7, table=True)),
                     (same + ".", meta("prose", page=8))], embed_fn=fake_embed)
    results = search(col, same)
    assert [r.chunk_id for r in results] == ["prose", "table"]
    assert results[1].is_table_heavy and results[1].score < results[0].score


def test_stored_record_without_page_is_never_returned(collection):
    # Written straight into Chroma, bypassing validation, to simulate a corrupt record.
    bad = meta("nopage")
    del bad["page"]
    collection.add(ids=["nopage"], embeddings=fake_embed(["client concentration risk"]),
                   documents=["client concentration risk"], metadatas=[bad])
    with pytest.warns(UserWarning, match="nopage"):
        results = search(collection, "client concentration risk", top_k=6)
    assert "nopage" not in [r.chunk_id for r in results]
    assert all(r.page >= 1 for r in results)


def test_search_uses_query_purpose(collection):
    seen = []

    def spy(texts, purpose="document"):
        seen.append(purpose)
        return fake_embed(texts, purpose)

    search_documents("client", collection=collection, embed_fn=spy)
    assert seen == ["query"]


# ---------- R1: prefer the latest report when no year is asked for ----------
# The same passage repeated in the FY24, FY25 and FY26 annual reports (as the real reports do),
# plus a later fact sheet (fiscal_year 2027) that must not count as "a newer annual report".

SAME = "Cyber attacks risk: security operations centres and cyber insurance."
REPEATED = [
    (SAME, meta("ar24-cyber", source_id=4, fiscal_year=2024, page=79)),
    (SAME, meta("ar25-cyber", source_id=3, fiscal_year=2025, page=93)),
    (SAME, meta("ar26-cyber", source_id=1, fiscal_year=2026, page=64)),
    (SAME, meta("fs27-cyber", source_id=5, doc_type="fact_sheet", fiscal_year=2027, page=2)),
]


@pytest.fixture
def repeated(tmp_path):
    col = open_collection(tmp_path / "chroma", "test_docs")
    add_chunks(col, REPEATED, embed_fn=fake_embed)
    return col


def factor():
    return load_ingest_config()["retrieval"]["recency"]["factor_per_year"]


def test_recency_factor_is_configured_between_0_and_1():
    assert 0 < factor() <= 1


def test_default_search_is_unchanged_no_recency_weight(repeated):
    results = search(repeated, SAME, top_k=4)
    assert {round(r.score, 9) for r in results} == {1.0}
    assert all(r.recency_weight == 1.0 for r in results)


def test_prefer_latest_ranks_the_latest_annual_report_first(repeated):
    results = search(repeated, SAME, top_k=4, prefer_latest=True)
    order = [r.chunk_id for r in results if r.doc_type == "annual_report"]
    assert order == ["ar26-cyber", "ar25-cyber", "ar24-cyber"]


def test_prefer_latest_weight_is_factor_per_year_behind(repeated):
    by_id = {r.chunk_id: r for r in search(repeated, SAME, top_k=4, prefer_latest=True)}
    f = factor()
    assert by_id["ar26-cyber"].recency_weight == 1.0
    assert by_id["ar25-cyber"].recency_weight == pytest.approx(f)
    assert by_id["ar24-cyber"].recency_weight == pytest.approx(f * f)
    assert by_id["ar24-cyber"].score == pytest.approx(f * f)


def test_latest_year_is_per_document_type(repeated):
    # The FY27 fact sheet is the latest fact sheet; it does not make the FY26 annual report "older".
    by_id = {r.chunk_id: r for r in search(repeated, SAME, top_k=4, prefer_latest=True)}
    assert by_id["fs27-cyber"].recency_weight == 1.0
    assert by_id["ar26-cyber"].recency_weight == 1.0


def test_doc_type_filter_keeps_the_preference(repeated):
    results = search(repeated, SAME, prefer_latest=True, doc_type="annual_report", top_k=3)
    assert [r.chunk_id for r in results] == ["ar26-cyber", "ar25-cyber", "ar24-cyber"]


@pytest.mark.parametrize("filters", [{"fiscal_year": 2024}, {"source_id": 4}])
def test_no_recency_weight_when_a_year_or_document_is_chosen(repeated, filters):
    results = search(repeated, SAME, prefer_latest=True, **filters)
    assert [r.chunk_id for r in results] == ["ar24-cyber"]
    assert results[0].recency_weight == 1.0 and results[0].score == pytest.approx(1.0)


def test_recency_and_table_weights_multiply(tmp_path):
    col = open_collection(tmp_path / "c", "test_docs")
    add_chunks(col, [(SAME, meta("t25", fiscal_year=2025, table=True)),
                     (SAME, meta("p26", fiscal_year=2026, page=6))], embed_fn=fake_embed)
    by_id = {r.chunk_id: r for r in search(col, SAME, prefer_latest=True)}
    table = load_ingest_config()["tables"]["score_weight"]
    assert by_id["t25"].score == pytest.approx(table * factor())


def test_factor_one_means_no_preference(repeated, monkeypatch):
    cfg = load_ingest_config()
    cfg = {**cfg, "retrieval": {"recency": {"factor_per_year": 1.0}}}
    monkeypatch.setattr("erp.tools.search.load_ingest_config", lambda: cfg)
    results = search(repeated, SAME, top_k=4, prefer_latest=True)
    assert all(r.recency_weight == 1.0 for r in results)


@pytest.mark.parametrize("bad", [0, -0.5, 1.5, "0.9", None])
def test_bad_recency_factor_is_refused(repeated, monkeypatch, bad):
    cfg = {**load_ingest_config(), "retrieval": {"recency": {"factor_per_year": bad}}}
    monkeypatch.setattr("erp.tools.search.load_ingest_config", lambda: cfg)
    with pytest.raises(SearchError, match="factor_per_year"):
        search(repeated, SAME, prefer_latest=True)
