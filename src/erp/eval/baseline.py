"""Naive-RAG baseline (plan 6.3): same local LLM, same questions, retrieval over the same PDFs
(the existing Chroma index) and nothing else.

No SQLite (this function is never given a database connection), no tools, no refusal
pre-check, no advice-word guard, no verifier. The question itself is the search query; the top
chunks go to the LLM with a short generic prompt; the LLM's text is returned as written. Its
output uses the same Answer shape as the full system, so both are scored by the same code.

The baseline exists to be measured. Its answers can contain anything a small model writes
(including advice wording, which is counted as a metric); they stay in eval/results.
"""
import json

import yaml

from erp.agent.answer_schema import Answer
from erp.agent.llm import LLMError
from erp.agent.tools import Evidence, Passage, ToolResult
from erp.config import REPO
from erp.tools.search import search_documents

BASELINE_RULES = """You answer questions about {company} using only the context passages below, taken from its filings.
Cite the passage ids you used in square brackets, e.g. [chunk:abc].
If the passages do not contain the answer, say that it is not available.
At most 150 words.
Reply with JSON: answer_text, cited_evidence_ids (the passage ids you relied on)."""


def company_name(ticker: str) -> str:
    with open(REPO / "config" / "companies" / f"{ticker.lower()}.yaml") as f:
        return yaml.safe_load(f)["company"]["name"]


def naive_rag_answer(question: str, *, ticker: str, collection, embed_fn, llm_fn, top_k: int,
                     passage_chars: int) -> Answer:
    hits = search_documents(question, top_k=top_k, collection=collection, embed_fn=embed_fn)
    evidence, passages = [], []
    for h in hits:
        eid = f"chunk:{h.chunk_id}"
        evidence.append(Evidence(evidence_id=eid, kind="doc_chunk", source_id=h.source_id, source_title=h.doc_title,
                                 page=h.page, page_end=h.page_end, page_label=h.page_label or None,
                                 note=f"section: {h.section}; score {h.score:.3f}"))
        passages.append(Passage(evidence_id=eid, section=h.section, text=h.text[:passage_chars]))
    search = ToolResult(tool="search_documents", args={"query": question}, ok=bool(hits),
                        error=None if hits else "no passages found", evidence=evidence, passages=passages)

    context = "\n\n".join(f"[{p.evidence_id}] (PDF page {e.page}; section: {p.section})\n{p.text}"
                          for p, e in zip(passages, evidence)) or "(no passages found)"
    messages = [{"role": "system", "content": BASELINE_RULES.format(company=company_name(ticker))},
                {"role": "user", "content": f"Question: {question}\n\nCONTEXT PASSAGES:\n{context}"}]
    ids = [e.evidence_id for e in evidence]
    schema = {"type": "object",
              "properties": {"answer_text": {"type": "string"},
                             "cited_evidence_ids": {"type": "array", "items": {"enum": ids}} if ids
                             else {"type": "array", "maxItems": 0}},
              "required": ["answer_text", "cited_evidence_ids"]}

    warnings, text, cited, model = [], "", [], None
    try:
        reply = llm_fn(messages, schema=schema)
        model = reply.model
        data = json.loads(reply.text)
        if isinstance(data, dict):
            text = data.get("answer_text") or ""
            cited = [i for i in data.get("cited_evidence_ids") or [] if i in ids]
    except (LLMError, json.JSONDecodeError) as e:
        warnings.append(f"baseline LLM reply unusable ({type(e).__name__}: {str(e)[:200]})")
    if not cited:
        if evidence:
            warnings.append("baseline cited no passage; all retrieved passages are attached")
        cited = ids
    return Answer(question=question, ticker=ticker, answer_text=text, numbers_used=[],
                  citations=[e for e in evidence if e.evidence_id in cited], refused=False, route=None,
                  tool_results=[search], composed_by="llm", model=model, warnings=warnings)
