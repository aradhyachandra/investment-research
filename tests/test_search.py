"""M4: search_documents. Plain function, typed output, filters, sorted by score, page always set."""
import pytest

from erp.ingest.index_chroma import add_chunks, open_collection
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
