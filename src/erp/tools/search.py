"""search_documents: similarity search over the indexed filings. Plain function, no LLM.

Every result carries source_id + page (and the printed page label), straight from the chunk's
stored metadata, so a citation is structural rather than generated text.

Scoring: score = 1 - cosine distance (higher is closer). A table-heavy chunk's score is
multiplied by tables.score_weight from config/ingest.yaml, so prose ranks above tables
for the same match: chunk text is for qualitative questions; numbers come from SQLite.
"""
import warnings

from pydantic import BaseModel

from erp.ingest.embed import embed_texts
from erp.ingest.index_chroma import open_collection
from erp.ingest.pdf_to_chunks import load_ingest_config

MAX_TOP_K = 100


class SearchError(ValueError):
    pass


class SearchResult(BaseModel):
    text: str
    source_id: int
    doc_type: str
    doc_title: str
    fiscal_year: int
    page: int                  # PDF page index, 1-based (first page if the chunk spans pages)
    page_end: int
    page_label: str            # printed page number, "" if none is printed
    section: str
    chunk_id: str
    is_table_heavy: bool
    score: float               # after the table-heavy weight; higher is better


def _where(doc_type, fiscal_year, source_id):
    clauses = []
    if doc_type is not None:
        clauses.append({"doc_type": doc_type})
    if fiscal_year is not None:
        clauses.append({"fiscal_year": int(fiscal_year)})
    if source_id is not None:
        clauses.append({"source_id": int(source_id)})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def search_documents(query: str, top_k: int = 5, doc_type: str | None = None,
                     fiscal_year: int | None = None, source_id: int | None = None,
                     *, collection=None, embed_fn=embed_texts) -> list[SearchResult]:
    """Top-k chunks for a question, best first. Filters are exact matches on metadata."""
    cfg = load_ingest_config()
    if not isinstance(query, str) or not query.strip():
        raise SearchError("query is empty")
    if not isinstance(top_k, int) or not 1 <= top_k <= MAX_TOP_K:
        raise SearchError(f"top_k must be a whole number from 1 to {MAX_TOP_K}, got {top_k!r}")
    if doc_type is not None and doc_type not in cfg["indexable_doc_types"]:
        raise SearchError(f"doc_type {doc_type!r} is not indexed (indexed: {cfg['indexable_doc_types']})")

    collection = collection if collection is not None else open_collection()
    total = collection.count()
    if total == 0:
        return []
    # Fetch extra candidates so the table-heavy weight can reorder before cutting to top_k.
    n = min(total, top_k * 3 + 5)
    vector = embed_fn([query], "query")[0]
    found = collection.query(query_embeddings=[vector], n_results=n, where=_where(doc_type, fiscal_year, source_id),
                             include=["documents", "metadatas", "distances"])

    weight = cfg["tables"]["score_weight"]
    results = []
    for chunk_id, text, meta, distance in zip(found["ids"][0], found["documents"][0],
                                              found["metadatas"][0], found["distances"][0]):
        page = meta.get("page")
        if not isinstance(page, int) or page < 1 or not meta.get("source_id"):
            warnings.warn(f"chunk {chunk_id} has no valid page/source_id; left out of results")
            continue
        score = 1.0 - distance
        if meta.get("is_table_heavy"):
            score *= weight
        results.append(SearchResult(
            text=text, source_id=meta["source_id"], doc_type=meta["doc_type"], doc_title=meta["doc_title"],
            fiscal_year=meta["fiscal_year"], page=page, page_end=meta.get("page_end", page),
            page_label=meta.get("page_label", ""), section=meta.get("section", ""), chunk_id=chunk_id,
            is_table_heavy=bool(meta.get("is_table_heavy")), score=score,
        ))
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]
