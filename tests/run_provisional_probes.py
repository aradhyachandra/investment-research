"""Report recall@k of search_documents on the PROVISIONAL retrieval probes (real index).

PROVISIONAL: these probes were written by Claude from its own reading of the FY26 annual report
to get a first baseline in M4. They are NOT the eval set and NOT gold; the author writes the
real category E questions in P0.4 (eval/questions.jsonl). No pass threshold is set.

A probe is a hit at k if any of the top-k results comes from the expected document and covers
one of the expected PDF pages (page..page_end).

Run from the repo root after indexing (needs Ollama running):
    PYTHONPATH=src .venv/bin/python tests/run_provisional_probes.py
"""
import json
import sqlite3
import sys
from pathlib import Path

from erp.ingest.embed import ollama_status
from erp.ingest.pdf_to_chunks import REPO, parse_page_labels
from erp.config import company_context
from erp.tools.search import search_documents

PROBES = Path(__file__).with_name("provisional_retrieval_probes.jsonl")


def load_probes(path=PROBES):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def is_hit(result, source_id, pages) -> bool:
    return result.source_id == source_id and any(result.page <= p <= result.page_end for p in pages)


def main(db="data/db/sample.sqlite", ticker="TCS", ks=(5, 10)) -> int:
    status = ollama_status()
    if not status.ok:
        print(f"Cannot run probes: {status.reason}", file=sys.stderr)
        return 2
    conn = sqlite3.connect(REPO / db)
    ctx = company_context(ticker)
    probes = load_probes()
    hits = {k: 0 for k in ks}
    # D3: with several annual reports indexed, show which report each top-5 result comes from.
    period_of = dict(conn.execute("SELECT source_id, period_covered FROM source_document").fetchall())
    from_other = 0
    for probe in probes:
        local_path = f"data/raw/{probe['source_file']}"
        source_id = conn.execute("SELECT source_id FROM source_document WHERE local_path = ?",
                                 (local_path,)).fetchone()[0]
        labels = parse_page_labels(ctx.sources[probe["source_file"]].get("page_labels"))
        results = search_documents(probe["question"], top_k=max(ks))
        first_hit = next((i + 1 for i, r in enumerate(results) if is_hit(r, source_id, probe["expected_pdf_pages"])), None)
        for k in ks:
            if first_hit is not None and first_hit <= k:
                hits[k] += 1
        expected = ", ".join(f"{p} ({'/'.join(labels.get(p, [])) or '-'})" for p in probe["expected_pdf_pages"])
        print(f"{probe['id']} [{probe['topic']}] {'HIT @' + str(first_hit) if first_hit else 'MISS'}")
        print(f"    Q: {probe['question']}")
        print(f"    expected PDF page (printed): {expected}")
        top = ", ".join(f"{period_of.get(r.source_id, r.source_id)}:{r.page}{'*' if r.is_table_heavy else ''}"
                        f"({r.score:.3f})" for r in results[:5])
        from_other += sum(r.source_id != source_id for r in results[:5])
        print(f"    top-5 document:PDF page (score; * = table-heavy): {top}")
    n = len(probes)
    print()
    for k in ks:
        print(f"recall@{k}: {hits[k]} of {n} provisional probes")
    print(f"top-5 results from a document other than the expected one: {from_other} of {5 * n}")
    print("PROVISIONAL baseline only: not the eval set, no threshold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
