"""Manual labelling of qualitative citations (plan 6.2, part 2). Not graded by code.

sample_claims picks about 20 qualitative claims (claims.py) that cite at least one passage,
from one saved run, with a fixed seed so the sample can be re-drawn. write_sample_csv writes
them with the cited passage text and an empty `supports` column for the author to fill:

  supports = yes     the cited passage says what the claim says
             partly  it supports part of the claim
             no      it does not support the claim (or says something else)

tally_labels counts the filled-in labels ("k of n" goes in the results note by hand).
"""
import csv
import random
from collections import Counter
from pathlib import Path

from erp.agent.answer_schema import Answer
from erp.eval.claims import extract_claims

FIELDS = ["sample_id", "system", "question_id", "category", "question", "claim", "cited_by", "cited_pages",
          "gold_pages", "cited_text", "supports", "labeller_notes"]


def _gold(record) -> str:
    return "; ".join(f"src{g['source_id']} p.{g['page']}" for g in record.get("gold_sources") or [])


def sample_claims(records: list[dict], n: int = 20, seed: int = 0) -> list[dict]:
    pool = []
    for r in records:
        answer = Answer.model_validate(r["answer"])
        passages = {p.evidence_id: p.text for t in answer.tool_results for p in t.passages}
        for i, c in enumerate(extract_claims(answer)[1]):
            if not c.cited:
                continue
            pool.append({
                "system": r["system"], "question_id": r["question_id"], "category": r.get("category", ""),
                "question": r.get("question", answer.question), "claim": c.text, "cited_by": c.cited_by,
                "cited_pages": "; ".join(f"{p.evidence_id} (src{p.source_id} p.{p.page}"
                                         + (f"-{p.page_end}" if p.page_end != p.page else "") + ")" for p in c.cited),
                "gold_pages": _gold(r),
                "cited_text": "\n---\n".join(" ".join(passages.get(p.evidence_id, "(text not saved)").split())
                                             for p in c.cited),
                "_key": (r["system"], r["question_id"], i)})
    pool.sort(key=lambda x: x["_key"])
    chosen = random.Random(seed).sample(pool, min(n, len(pool)))
    chosen.sort(key=lambda x: x["_key"])
    return [{**{k: v for k, v in x.items() if k != "_key"}, "sample_id": f"Q{j + 1:02d}", "supports": "",
             "labeller_notes": ""} for j, x in enumerate(chosen)]


def write_sample_csv(rows: list[dict], path: Path) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows({k: row.get(k, "") for k in FIELDS} for row in rows)


def tally_labels(path: Path) -> dict[str, int]:
    with open(path, newline="") as f:
        labels = [(r.get("supports") or "").strip().lower() or "unlabelled" for r in csv.DictReader(f)]
    return dict(Counter(labels))
