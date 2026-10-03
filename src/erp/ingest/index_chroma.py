"""Store document chunks in ChromaDB, with mandatory metadata, idempotently.

Rules enforced here:
- Only files registered in SQLite `source_document` are indexed (source_id comes from there),
  and only doc types listed in config/ingest.yaml (annual_report, fact_sheet,
  quarterly_results). generated_sample notes and anything under data/sample/generated/ are
  refused.
- The file on disk must match the sha256 registered for it.
- Every chunk is validated (ChunkMetadata) before anything is written; one bad chunk blocks
  the whole batch.
- Re-running on an unchanged file does nothing. A changed file (new registered sha256) or a
  changed embedding model deletes that document's chunks and indexes it again.
- Chroma never embeds anything itself: its built-in embedder downloads a model from the
  internet, so the collection gets an embedding function that refuses to run. Vectors always
  come from erp.ingest.embed.embed_texts (or a fake in tests).

Run from the repo root (needs the SQLite DB from load_facts and Ollama running):
    PYTHONPATH=src python -m erp.ingest.index_chroma --db data/db/sample.sqlite
"""
import argparse
import hashlib
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

import chromadb
from chromadb.api.types import EmbeddingFunction
from chromadb.config import Settings
from pydantic import BaseModel, Field, StrictBool, StrictInt, ValidationError, model_validator

from erp.ingest.embed import embed_texts, ollama_status
from erp.ingest.pdf_to_chunks import REPO, extract_chunks, load_ingest_config
from erp.periods import PeriodError, resolve_period


class ChunkError(ValueError):
    pass


class IngestError(ValueError):
    pass


class ChunkMetadata(BaseModel):
    """Metadata every stored chunk must carry. Chroma metadata cannot hold None, so a missing
    printed page number is stored as ""."""
    source_id: StrictInt = Field(ge=1)
    doc_type: str = Field(min_length=1)
    doc_title: str = Field(min_length=1)
    page: StrictInt = Field(ge=1)            # PDF page index, 1-based
    page_end: StrictInt = Field(ge=1)
    page_label: str                          # printed page number, "" if none
    page_label_end: str
    section: str
    fiscal_year: StrictInt
    chunk_id: str = Field(min_length=1)
    is_table_heavy: StrictBool
    file_sha256: str = Field(min_length=64, max_length=64)
    embed_model: str = Field(min_length=1)

    @model_validator(mode="after")
    def _page_range(self):
        if self.page_end < self.page:
            raise ValueError(f"page_end {self.page_end} is before page {self.page}")
        return self


def validate_chunk(text, meta: dict, allowed_doc_types=None) -> ChunkMetadata:
    if not isinstance(text, str) or not text.strip():
        raise ChunkError(f"chunk {meta.get('chunk_id')!r}: empty text")
    try:
        m = ChunkMetadata(**meta)
    except ValidationError as e:
        raise ChunkError(f"chunk {meta.get('chunk_id')!r} rejected: {e}") from None
    allowed = allowed_doc_types or load_ingest_config()["indexable_doc_types"]
    if m.doc_type not in allowed:
        raise ChunkError(f"chunk {m.chunk_id!r}: doc_type {m.doc_type!r} may not be indexed (allowed: {allowed})")
    return m


class _RefuseEmbedding(EmbeddingFunction):
    """Stops Chroma from ever embedding text itself (that would download a model)."""

    def __init__(self):
        pass

    def __call__(self, input):
        raise RuntimeError("refused: Chroma must not embed by itself; pass embeddings from erp.ingest.embed")

    @staticmethod
    def name():
        return "erp_refuse"

    def get_config(self):
        return {}

    @staticmethod
    def build_from_config(config):
        return _RefuseEmbedding()


def open_collection(path=None, name=None):
    """The Chroma collection (created if missing). Cosine distance; score = 1 - distance."""
    chroma_cfg = load_ingest_config()["chroma"]
    path = Path(path) if path else REPO / chroma_cfg["path"]
    client = chromadb.PersistentClient(path=str(path), settings=Settings(anonymized_telemetry=False))
    return client.get_or_create_collection(
        name or chroma_cfg["collection"],
        embedding_function=_RefuseEmbedding(),
        metadata={"hnsw:space": "cosine"},
    )


def add_chunks(collection, chunks, embed_fn=embed_texts, batch_size=None, allowed_doc_types=None) -> int:
    """Validate every (text, metadata) pair, then embed and store them in small batches."""
    cfg = load_ingest_config()
    checked = [(text, validate_chunk(text, meta, allowed_doc_types).model_dump()) for text, meta in chunks]
    ids = [m["chunk_id"] for _, m in checked]
    if len(set(ids)) != len(ids):
        raise ChunkError("duplicate chunk_id in batch")
    size = batch_size or cfg["embedding"]["batch_size"]
    for start in range(0, len(checked), size):
        batch = checked[start:start + size]
        texts = [t for t, _ in batch]
        vectors = embed_fn(texts, "document")
        if len(vectors) != len(texts):
            raise ChunkError(f"embedder returned {len(vectors)} vectors for {len(texts)} texts")
        collection.add(ids=[m["chunk_id"] for _, m in batch], embeddings=vectors,
                       documents=texts, metadatas=[m for _, m in batch])
    return len(checked)


@dataclass
class IngestReport:
    file: str
    status: str                 # indexed | reindexed | skipped
    source_id: int
    n_chunks: int
    n_table_heavy: int = 0
    label_warnings: list = field(default_factory=list)


def sha256_of(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _registered(conn, rel_path):
    rows = conn.execute(
        "SELECT s.source_id, s.doc_type, s.title, s.period_covered, s.sha256, c.fiscal_year_end_month"
        " FROM source_document s JOIN company c USING (company_id) WHERE s.local_path = ?",
        (rel_path,)).fetchall()
    if not rows:
        raise IngestError(f"{rel_path}: not registered in source_document (add it to the company config and reload)")
    if len(rows) > 1:
        raise IngestError(f"{rel_path}: registered more than once in source_document")
    return rows[0]


def ingest_source(conn, collection, rel_path, *, root=REPO, page_labels=None, embed_fn=embed_texts,
                  batch_size=None, cfg=None) -> IngestReport:
    """Index one registered document. Returns what happened (indexed / reindexed / skipped)."""
    cfg = cfg or load_ingest_config()
    root = Path(root).resolve()
    path = (root / rel_path).resolve()
    if not path.is_relative_to(root):
        raise IngestError(f"{rel_path}: outside the data root {root}")
    rel = path.relative_to(root).as_posix()
    for forbidden in cfg["forbidden_dirs"]:
        if rel == forbidden or rel.startswith(forbidden.rstrip("/") + "/"):
            raise IngestError(f"{rel}: files under {forbidden} are never indexed")

    source_id, doc_type, title, period_covered, registered_sha, fy_end = _registered(conn, rel)
    if doc_type not in cfg["indexable_doc_types"]:
        raise IngestError(f"{rel}: doc_type {doc_type} is not indexable (allowed: {cfg['indexable_doc_types']})")
    if not path.exists():
        raise IngestError(f"{rel}: file not found")
    sha = sha256_of(path)
    if sha != registered_sha:
        raise IngestError(f"{rel}: file sha256 {sha[:12]}... does not match the registered {str(registered_sha)[:12]}...")
    try:
        fiscal_year = resolve_period(period_covered, fy_end).fiscal_year
    except PeriodError as e:
        raise IngestError(f"{rel}: period_covered {period_covered!r} gives no fiscal year: {e}") from None

    model = cfg["embedding"]["model"] if embed_fn is embed_texts else getattr(
        embed_fn, "__name__", type(embed_fn).__name__)
    existing = collection.get(where={"source_id": source_id}, include=["metadatas"])["metadatas"]
    if existing and all(m.get("file_sha256") == sha and m.get("embed_model") == model for m in existing):
        return IngestReport(rel, "skipped", source_id, len(existing),
                            n_table_heavy=sum(1 for m in existing if m.get("is_table_heavy")))

    result = extract_chunks(path, page_labels=page_labels, settings=cfg)
    chunks = []
    for i, c in enumerate(result.chunks):
        meta = {
            "source_id": source_id, "doc_type": doc_type, "doc_title": title,
            "page": c.page, "page_end": c.page_end, "page_label": c.page_label,
            "page_label_end": c.page_label_end, "section": c.section, "fiscal_year": fiscal_year,
            "chunk_id": f"src{source_id}-{sha[:12]}-p{c.page:04d}-{i:04d}",
            "is_table_heavy": c.is_table_heavy, "file_sha256": sha, "embed_model": model,
        }
        chunks.append((c.text, meta))
    # Validate everything before touching the stored copy.
    for text, meta in chunks:
        validate_chunk(text, meta, cfg["indexable_doc_types"])

    if existing:
        collection.delete(where={"source_id": source_id})
    try:
        n = add_chunks(collection, chunks, embed_fn=embed_fn, batch_size=batch_size,
                       allowed_doc_types=cfg["indexable_doc_types"])
    except Exception:
        collection.delete(where={"source_id": source_id})   # never leave half a document behind
        raise
    return IngestReport(rel, "reindexed" if existing else "indexed", source_id, n,
                        n_table_heavy=sum(1 for _, m in chunks if m["is_table_heavy"]),
                        label_warnings=result.label_warnings)


def ingest_registered(conn, collection, ctx, *, root=REPO, embed_fn=embed_texts, cfg=None) -> list:
    """Index every indexable source in the company config. Missing files are reported, not fatal."""
    cfg = cfg or load_ingest_config()
    reports = []
    for source in ctx.sources.values():
        if source["doc_type"] not in cfg["indexable_doc_types"]:
            continue
        if not (Path(root) / source["local_path"]).exists():
            reports.append(IngestReport(source["local_path"], "missing", 0, 0))
            continue
        reports.append(ingest_source(conn, collection, source["local_path"], root=root,
                                     page_labels=source.get("page_labels"), embed_fn=embed_fn, cfg=cfg))
    return reports


def main(argv=None) -> int:
    from erp.config import company_context

    ap = argparse.ArgumentParser(description="Index registered source PDFs into ChromaDB.")
    ap.add_argument("--db", default="data/db/sample.sqlite", help="SQLite DB with source_document rows")
    ap.add_argument("--ticker", default="TCS")
    args = ap.parse_args(argv)

    status = ollama_status()
    if not status.ok:
        print(f"Cannot embed: {status.reason}", file=sys.stderr)
        return 2
    db = Path(args.db)
    if not db.exists():
        print(f"{db} not found. Build it first with erp.db.load_facts (it registers the source documents).",
              file=sys.stderr)
        return 2
    conn = sqlite3.connect(db)
    collection = open_collection()
    try:
        reports = ingest_registered(conn, collection, company_context(args.ticker))
    except (IngestError, ChunkError) as e:
        print(e, file=sys.stderr)
        return 1
    finally:
        conn.close()
    for r in reports:
        print(f"{r.status:<10} {r.file}  source_id={r.source_id}  chunks={r.n_chunks}"
              f"  table_heavy={r.n_table_heavy}")
        if r.label_warnings:
            soft = sum(1 for w in r.label_warnings if w.endswith("(config kept)"))
            print(f"           page-label check: {soft} footers unreadable or missing digits (config kept), "
                  f"{len(r.label_warnings) - soft} disagreements")
            for w in r.label_warnings:
                if not w.endswith("(config kept)"):
                    print(f"           {w}")
    print(f"Collection now holds {collection.count()} chunks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
