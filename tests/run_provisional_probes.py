"""Report recall@k of search_documents on the PROVISIONAL retrieval probes (real index).

PROVISIONAL: these probes were written by Claude from its own reading of the FY26 annual report
to get a first baseline in M4. They are NOT the eval set and NOT gold; the author writes the
real category E questions in P0.4 (eval/questions.jsonl). No pass threshold is set.

A probe is a hit at k if any of the top-k results comes from the expected document and covers
one of the expected PDF pages (page..page_end).

Run from the repo root after indexing (needs Ollama running):
    PYTHONPATH=src .venv/bin/python tests/run_provisional_probes.py
    PYTHONPATH=src .venv/bin/python tests/run_provisional_probes.py --prefer-latest

--prefer-latest applies the agent's search rule, using the router's own code (set_search_year), with
the question as the search phrase: R1, prefer the latest report unless the question names a period;
R2, a question naming exactly one fiscal year with data is filtered to that year, falling back to an
unfiltered search if that year has nothing indexed (as the search tool does). It also runs the
PROVISIONAL year-named phrasings (provisional_year_probes.jsonl) and counts how many top-5 results
come from the report of the year the question names.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

from erp.ingest.embed import ollama_status
from erp.ingest.pdf_to_chunks import REPO, parse_page_labels
from erp.agent.router import build_catalog, set_search_year
from erp.agent.tools import SearchArgs, ToolCall
from erp.config import company_context
from erp.tools.search import search_documents

PROBES = Path(__file__).with_name("provisional_retrieval_probes.jsonl")
YEAR_PROBES = Path(__file__).with_name("provisional_year_probes.jsonl")


def load_probes(path=PROBES):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def is_hit(result, source_id, pages) -> bool:
    return result.source_id == source_id and any(result.page <= p <= result.page_end for p in pages)


def agent_search(question: str, catalog, top_k: int = 5):
    """search_documents as the agent runs it for this question (router rule + the tool's fallback).
    Returns (results, the arguments used, whether the year filter fell back)."""
    call = ToolCall(tool="search_documents", args={"query": question})
    set_search_year([call], question, catalog)
    a = SearchArgs(**call.args)
    results = search_documents(question, top_k=top_k, fiscal_year=a.fiscal_year, prefer_latest=a.prefer_latest)
    fallback = a.fiscal_year is not None and not results
    if fallback:
        results = search_documents(question, top_k=top_k, prefer_latest=a.prefer_latest)
    return results, a, fallback


def describe(a: SearchArgs, fallback: bool) -> str:
    if a.fiscal_year is not None:
        return f"filter fiscal_year={a.fiscal_year}" + (" (nothing indexed: fell back to all)" if fallback else "")
    return "latest-report preference" if a.prefer_latest else "no filter, no preference (period named)"


def year_probes(catalog) -> None:
    print()
    print("Year-named phrasings: top-5 results from the report of the year named "
          "(as the agent runs it / if the weight were applied anyway / with a fiscal_year filter)")
    for probe in load_probes(YEAR_PROBES):
        q, fy = probe["question"], probe["expected_fiscal_year"]
        agent, a, fallback = agent_search(q, catalog)
        runs = {"agent": agent,
                "forced": search_documents(q, prefer_latest=True),
                "filter": search_documents(q, fiscal_year=fy)}
        counts = " / ".join(f"{sum(r.fiscal_year == fy for r in res)}" for res in runs.values())
        top = ", ".join(f"FY{r.fiscal_year % 100}:{r.page}({r.score:.3f})" for r in runs["agent"])
        print(f"{probe['id']} {counts} of 5   Q: {q}")
        print(f"    agent ({describe(a, fallback)}) top-5: {top}")


def main(db="data/db/sample.sqlite", ticker="TCS", ks=(5, 10), prefer_latest=False) -> int:
    status = ollama_status()
    if not status.ok:
        print(f"Cannot run probes: {status.reason}", file=sys.stderr)
        return 2
    conn = sqlite3.connect(REPO / db)
    ctx = company_context(ticker)
    probes = load_probes()
    catalog = build_catalog(conn, ticker, dcf_assumptions=REPO / "data" / "manual" / "dcf_inputs.yaml")
    hits = {k: 0 for k in ks}
    # D3: with several annual reports indexed, show which report each top-5 result comes from.
    period_of = dict(conn.execute("SELECT source_id, period_covered FROM source_document").fetchall())
    from_other = 0
    for probe in probes:
        local_path = f"data/raw/{probe['source_file']}"
        source_id = conn.execute("SELECT source_id FROM source_document WHERE local_path = ?",
                                 (local_path,)).fetchone()[0]
        labels = parse_page_labels(ctx.sources[probe["source_file"]].get("page_labels"))
        if prefer_latest:
            results, a, fallback = agent_search(probe["question"], catalog, top_k=max(ks))
        else:
            results = search_documents(probe["question"], top_k=max(ks))
        first_hit = next((i + 1 for i, r in enumerate(results) if is_hit(r, source_id, probe["expected_pdf_pages"])), None)
        for k in ks:
            if first_hit is not None and first_hit <= k:
                hits[k] += 1
        expected = ", ".join(f"{p} ({'/'.join(labels.get(p, [])) or '-'})" for p in probe["expected_pdf_pages"])
        print(f"{probe['id']} [{probe['topic']}] {'HIT @' + str(first_hit) if first_hit else 'MISS'}"
              f"{'   (' + describe(a, fallback) + ')' if prefer_latest else ''}")
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
    print(f"top-5 results from the expected (latest) report: {5 * n - from_other} of {5 * n}")
    print(f"search rule: {'agent (R1 latest preference + R2 year filter)' if prefer_latest else 'plain search'}")
    print("PROVISIONAL baseline only: not the eval set, no threshold.")
    if prefer_latest:
        year_probes(catalog)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prefer-latest", action="store_true", help="apply the agent search rule (R1 + R2)")
    sys.exit(main(prefer_latest=parser.parse_args().prefer_latest))
