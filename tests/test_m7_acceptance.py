"""M7 acceptance (plan Section 9): run_eval.py outputs per-category and headline metrics for dev;
the test split runs once; results saved.

Deterministic plumbing check on the real dev split of eval/questions.jsonl (read only), with a
scripted LLM: the router always fetches FY26 revenue and searches the question, the composer
writes every figure it is offered, the baseline says "not available". The numbers this produces
say nothing about the real model; they only prove that every system runs on every dev question
and that the metrics, per-category table and saved files come out. The real dev run (Ollama,
qwen2.5:3b) is recorded in PROGRESS.md. "Test split runs once" is covered by the safety tests in
test_eval_harness.py on a synthetic file; the real test run is the author's to start.
"""
import hashlib
import json
import re

from erp.eval import cli
from erp.eval.questions import QUESTIONS_PATH, load_questions
from fakes import ScriptedLLM
from test_m5_acceptance import env  # noqa: F401  (fixture)


def scripted():
    def reply(messages, schema):
        props = schema["properties"]
        question = messages[-1]["content"]
        if "question_type" in props:
            return json.dumps({"calls": [{"tool": "get_financial_fact", "metric_id": "revenue_from_operations",
                                          "period": "FY26"}, {"tool": "search_documents", "query": question}],
                               "question_type": "mixed", "refusal_reason": "none"})
        if "used_number_ids" not in props:
            return json.dumps({"answer_text": "The passages do not contain this; it is not available.",
                               "cited_evidence_ids": []})
        figures = re.findall(r"^- \[[^\]]+\] ([^:\n]+): (.+)$", question, re.M)
        text = " ".join(f"{label}: {shown}." for label, shown in figures)
        return json.dumps({"answer_text": text, "used_number_ids": [], "cited_evidence_ids": []})
    return ScriptedLLM(reply)


def test_run_eval_outputs_per_category_and_headline_metrics_for_dev(env, tmp_path):
    before = hashlib.sha256(QUESTIONS_PATH.read_bytes()).hexdigest()
    out = cli.main([], input_fn=lambda p: "", make_env=lambda: env, llm_fn=scripted(), results_root=tmp_path)
    assert hashlib.sha256(QUESTIONS_PATH.read_bytes()).hexdigest() == before

    dev = load_questions(split="dev")
    metrics = json.loads((out / "metrics.json").read_text())
    for system in ("full", "full_no_verifier", "naive_rag"):
        m = metrics[system]
        rows = [json.loads(x) for x in (out / f"{system}.jsonl").read_text().splitlines()]
        assert [r["question_id"] for r in rows] == [x.id for x in dev]
        assert set(m["by_category"]) == {x.category for x in dev}
        for key in ("numeric_accuracy", "citation_numeric", "citation_numeric_gold_claims"):
            assert re.fullmatch(r"\d+ of \d+", m["headline"][key]["text"])
        for key in ("refusal_G", "over_refusal", "unsupported_claims", "advice_language"):
            assert re.fullmatch(r"\d+ of \d+", m["secondary"][key]["text"])
        assert m["headline"]["numeric_accuracy"]["n"] == sum(x.gold_value is not None for x in dev)

    full = {r["question_id"]: r for r in map(json.loads, (out / "full.jsonl").read_text().splitlines())}
    assert full["EV-A01"]["score"]["numeric_correct"]                        # FY26 revenue from SQLite
    assert full["EV-A01"]["score"]["gold_citing_claims"] >= 1               # cites PDF p.167
    assert full["EV-G01"]["answer"]["refused"] and full["EV-G03"]["answer"]["refused"]
    assert metrics["full"]["secondary"]["routing_tools"]["n"] > 0
    assert metrics["naive_rag"]["secondary"]["routing_tools"] is None       # the baseline has no router

    report = (out / "report.md").read_text()
    for cat in sorted({x.category for x in dev}):
        assert f"| {cat} |" in report
    assert "Known expected failures" in report and "EV-B02" in report and "EV-B06" in report
    meta = json.loads((out / "run.json").read_text())
    assert meta["split"] == "dev" and meta["status"] == "finished" and meta["git_sha"]
