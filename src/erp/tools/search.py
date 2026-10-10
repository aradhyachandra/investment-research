"""search_documents: similarity search over the indexed filings. Plain function, no LLM.

Every result carries source_id + page (and the printed page label), straight from the chunk's
stored metadata, so a citation is structural rather than generated text.

Scoring: score = 1 - cosine distance (higher is closer). A table-heavy chunk's score is
multiplied by tables.score_weight from config/ingest.yaml, so prose ranks above tables
for the same match: chunk text is for qualitative questions; numbers come from SQLite.

R1, prefer_latest=True (the agent's default when the question names no year): a chunk's score is
also multiplied by retrieval.recency.factor_per_year for each fiscal year it is behind the latest
document of its doc_type in the index, so near-copies in older annual reports do not crowd out the
latest one. Off when a fiscal_year or source_id filter picks the documents.
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
    score: float               # after the table-heavy and recency weights; higher is better
    recency_weight: float = 1.0  # 1.0 = latest document of its type, or no preference asked for


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


def _recency_factor(cfg) -> float:
    f = cfg.get("retrieval", {}).get("recency", {}).get("factor_per_year")
    if isinstance(f, bool) or not isinstance(f, (int, float)) or not 0 < f <= 1:
        raise SearchError(f"retrieval.recency.factor_per_year in config/ingest.yaml must be a number "
                          f"above 0 and at most 1, got {f!r}")
    return float(f)


def _latest_year_by_doc_type(collection) -> dict[str, int]:
    """Latest fiscal_year per doc_type over the whole index (not only this query's candidates)."""
    latest = {}
    for m in collection.get(include=["metadatas"])["metadatas"]:
        dt, fy = m.get("doc_type"), m.get("fiscal_year")
        if isinstance(fy, int):
            latest[dt] = max(latest.get(dt, fy), fy)
    return latest


def search_documents(query: str, top_k: int = 5, doc_type: str | None = None,
                     fiscal_year: int | None = None, source_id: int | None = None,
                     *, prefer_latest: bool = False, collection=None, embed_fn=embed_texts) -> list[SearchResult]:
    """Top-k chunks for a question, best first. Filters are exact matches on metadata.
    prefer_latest: down-weight older documents of the same type (ignored when fiscal_year or
    source_id is given)."""
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
    use_recency = prefer_latest and fiscal_year is None and source_id is None
    if use_recency:
        per_year = _recency_factor(cfg)
        latest = _latest_year_by_doc_type(collection)
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
        recency = 1.0
        if use_recency:
            behind = max(0, latest.get(meta["doc_type"], meta["fiscal_year"]) - meta["fiscal_year"])
            recency = per_year ** behind
            score *= recency
        results.append(SearchResult(
            text=text, source_id=meta["source_id"], doc_type=meta["doc_type"], doc_title=meta["doc_title"],
            fiscal_year=meta["fiscal_year"], page=page, page_end=meta.get("page_end", page),
            page_label=meta.get("page_label", ""), section=meta.get("section", ""), chunk_id=chunk_id,
            is_table_heavy=bool(meta.get("is_table_heavy")), score=score, recency_weight=recency,
        ))
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]
