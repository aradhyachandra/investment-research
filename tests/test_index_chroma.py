"""M4: chunks -> ChromaDB. Registered documents only, mandatory metadata, idempotent."""
import hashlib

import pytest

from erp.ingest.index_chroma import (
    ChunkError, IngestError, add_chunks, ingest_source, open_collection, validate_chunk,
)
from fakes import CountingEmbedder, fake_embed
from pdf_fixtures import build_pdf, sentences


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def register(conn, rel_path, sha, doc_type="annual_report", title="Test Annual Report", period="FY26"):
    with conn:
        cur = conn.execute(
            "INSERT INTO source_document (company_id, doc_type, title, publisher, local_path,"
            " period_covered, sha256, retrieved_on) VALUES (1, ?, ?, 'Test', ?, ?, ?, '2026-10-04')",
            (doc_type, title, rel_path, period, sha))
    return cur.lastrowid


@pytest.fixture
def root(tmp_path):
    (tmp_path / "data" / "raw").mkdir(parents=True)
    (tmp_path / "data" / "sample" / "generated").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def collection(tmp_path):
    return open_collection(tmp_path / "chroma", "test_docs")


@pytest.fixture
def report_pdf(root):
    return build_pdf(root / "data" / "raw" / "report.pdf", [
        {"blocks": [("h", "Risks"), ("p", sentences("riskword", 8))], "footer": "10"},
        {"blocks": [("h", "Strategy"), ("p", sentences("strategyword", 8))], "footer": "11"},
    ])


@pytest.fixture
def registered(conn, report_pdf):
    return register(conn, "data/raw/report.pdf", sha256(report_pdf))


def all_metadata(collection):
    return collection.get(include=["metadatas"])["metadatas"]


MANDATORY = ("source_id", "doc_type", "doc_title", "page", "page_label", "section",
             "fiscal_year", "chunk_id", "is_table_heavy")


def test_every_stored_chunk_has_all_mandatory_metadata(conn, collection, root, registered):
    report = ingest_source(conn, collection, "data/raw/report.pdf", root=root,
                           page_labels=[{"pdf_pages": [1, 2], "first_printed": 10}], embed_fn=fake_embed)
    assert report.status == "indexed" and report.n_chunks > 0
    metas = all_metadata(collection)
    assert len(metas) == report.n_chunks
    for m in metas:
        for key in MANDATORY:
            assert key in m, key
        assert m["source_id"] == registered
        assert m["doc_type"] == "annual_report"
        assert m["doc_title"] == "Test Annual Report"
        assert m["fiscal_year"] == 2026            # from period_covered FY26
        assert m["page"] in (1, 2) and m["page_label"] == str(m["page"] + 9)
        assert m["section"] in ("Risks", "Strategy")
        assert m["is_table_heavy"] is False


def test_chunk_ids_are_unique_and_stable(conn, tmp_path, root, registered):
    a = open_collection(tmp_path / "c1", "test_docs")
    b = open_collection(tmp_path / "c2", "test_docs")
    ingest_source(conn, a, "data/raw/report.pdf", root=root, embed_fn=fake_embed)
    ingest_source(conn, b, "data/raw/report.pdf", root=root, embed_fn=fake_embed)
    ids_a, ids_b = sorted(a.get()["ids"]), sorted(b.get()["ids"])
    assert ids_a == ids_b and len(set(ids_a)) == len(ids_a)
    assert [m["chunk_id"] for m in a.get(ids=ids_a, include=["metadatas"])["metadatas"]] == ids_a


def good_meta(**over):
    m = {"source_id": 1, "doc_type": "annual_report", "doc_title": "T", "page": 3, "page_end": 3,
         "page_label": "33", "page_label_end": "33", "section": "Risks", "fiscal_year": 2026,
         "chunk_id": "c1", "is_table_heavy": False, "file_sha256": "ab" * 32,
         "embed_model": "fake"}
    m.update(over)
    return m


@pytest.mark.parametrize("missing", ["source_id", "page"])
def test_chunk_missing_source_id_or_page_is_rejected(missing):
    meta = good_meta()
    del meta[missing]
    with pytest.raises(ChunkError, match=missing):
        validate_chunk("some text", meta)


@pytest.mark.parametrize("bad", [
    {"page": 0}, {"page": -1}, {"page": "3"}, {"source_id": 0}, {"source_id": None},
    {"page_end": 2},                       # ends before it starts
    {"doc_type": "generated_sample"}, {"doc_title": ""}, {"chunk_id": ""},
])
def test_chunk_with_bad_metadata_is_rejected(bad):
    with pytest.raises(ChunkError):
        validate_chunk("some text", good_meta(**bad))


def test_empty_chunk_text_is_rejected():
    with pytest.raises(ChunkError):
        validate_chunk("   ", good_meta())


def test_one_bad_chunk_blocks_the_whole_batch(collection):
    good = ("fine text", good_meta(chunk_id="ok"))
    bad_meta = good_meta(chunk_id="bad")
    del bad_meta["page"]
    with pytest.raises(ChunkError):
        add_chunks(collection, [good, ("bad text", bad_meta)], embed_fn=fake_embed)
    assert collection.count() == 0


def test_reingest_unchanged_file_is_skipped(conn, collection, root, registered):
    first = CountingEmbedder()
    r1 = ingest_source(conn, collection, "data/raw/report.pdf", root=root, embed_fn=first)
    ids_before = sorted(collection.get()["ids"])
    second = CountingEmbedder()
    r2 = ingest_source(conn, collection, "data/raw/report.pdf", root=root, embed_fn=second)
    assert r1.status == "indexed" and r2.status == "skipped"
    assert second.texts == 0
    assert sorted(collection.get()["ids"]) == ids_before


def test_changed_hash_triggers_reindex(conn, collection, root, report_pdf, registered):
    ingest_source(conn, collection, "data/raw/report.pdf", root=root, embed_fn=fake_embed)
    old_ids = set(collection.get()["ids"])
    build_pdf(report_pdf, [{"blocks": [("h", "Outlook"), ("p", sentences("outlookword", 8))]}])
    with conn:
        conn.execute("UPDATE source_document SET sha256 = ? WHERE source_id = ?", (sha256(report_pdf), registered))
    r = ingest_source(conn, collection, "data/raw/report.pdf", root=root, embed_fn=fake_embed)
    assert r.status == "reindexed"
    metas = all_metadata(collection)
    assert len(metas) == r.n_chunks
    assert not (set(collection.get()["ids"]) & old_ids)
    assert {m["section"] for m in metas} == {"Outlook"}
    assert {m["file_sha256"] for m in metas} == {sha256(report_pdf)}


def test_file_not_matching_registered_hash_is_refused(conn, collection, root, report_pdf, registered):
    build_pdf(report_pdf, [{"blocks": [("p", sentences("changed", 4))]}])
    with pytest.raises(IngestError, match="sha256"):
        ingest_source(conn, collection, "data/raw/report.pdf", root=root, embed_fn=fake_embed)
    assert collection.count() == 0


def test_unregistered_file_is_refused(conn, collection, root):
    build_pdf(root / "data" / "raw" / "stray.pdf", [{"blocks": [("p", sentences("stray", 4))]}])
    with pytest.raises(IngestError, match="not registered"):
        ingest_source(conn, collection, "data/raw/stray.pdf", root=root, embed_fn=fake_embed)
    assert collection.count() == 0


def test_generated_sample_document_is_refused(conn, collection, root):
    pdf = build_pdf(root / "data" / "raw" / "notes.pdf", [{"blocks": [("p", sentences("gen", 4))]}])
    register(conn, "data/raw/notes.pdf", sha256(pdf), doc_type="generated_sample")
    with pytest.raises(IngestError, match="generated_sample"):
        ingest_source(conn, collection, "data/raw/notes.pdf", root=root, embed_fn=fake_embed)
    assert collection.count() == 0


def test_anything_under_generated_folder_is_refused_even_if_registered(conn, collection, root):
    pdf = build_pdf(root / "data" / "sample" / "generated" / "x.pdf", [{"blocks": [("p", sentences("gen", 4))]}])
    register(conn, "data/sample/generated/x.pdf", sha256(pdf), doc_type="annual_report")
    with pytest.raises(IngestError, match="data/sample/generated"):
        ingest_source(conn, collection, "data/sample/generated/x.pdf", root=root, embed_fn=fake_embed)
    assert collection.count() == 0


def test_path_escaping_the_root_is_refused(conn, collection, root):
    with pytest.raises(IngestError):
        ingest_source(conn, collection, "../outside.pdf", root=root, embed_fn=fake_embed)


def test_collection_never_embeds_by_itself(collection):
    # Chroma's built-in embedder downloads a model from the internet; it must never run.
    with pytest.raises(Exception, match="refused"):
        collection.query(query_texts=["anything"], n_results=1)
    with pytest.raises(Exception, match="refused"):
        collection.add(ids=["x"], documents=["no embedding given"])


def test_embedding_in_small_batches(conn, collection, root, registered):
    emb = CountingEmbedder()
    r = ingest_source(conn, collection, "data/raw/report.pdf", root=root, embed_fn=emb, batch_size=2)
    assert emb.texts == r.n_chunks
    assert emb.calls == -(-r.n_chunks // 2)
