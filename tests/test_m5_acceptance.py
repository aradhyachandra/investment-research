"""M5 acceptance (plan Section 9): end-to-end answers for 10 dev questions with evidence IDs
filled; routing accuracy measured.

PROVISIONAL: eval/questions.jsonl (P0.4) does not exist yet, so the questions are the
Claude-written ones in tests/provisional_dev_questions.jsonl (rows with "e2e": true).

This test is deterministic: the LLM is a scripted fake that returns each question's expected
route and lists every id it is offered. It proves the plumbing (route -> tools in code ->
structured Answer with evidence). The real model's routing accuracy is measured separately by
tests/run_provisional_dev.py (needs Ollama), and recorded in PROGRESS.md.

DCF: the TOY fixture with its ticker set to TCS (made-up numbers, NOT a TCS valuation), because
the real assumptions file (data/manual/dcf_inputs.yaml, P0.3) does not exist yet.
"""
import json
import re
from pathlib import Path

import pytest
import yaml

from erp.agent.loop import answer_question
from erp.agent.route_score import RoutingTally, score_route
from erp.agent.tools import ToolEnv
from erp.ingest.index_chroma import add_chunks, open_collection
from fakes import ScriptedLLM, fake_embed
from test_agent_tools import CHUNKS, DISPLAY
from test_dcf_run import TOY_YAML

QUESTIONS = Path(__file__).parent / "provisional_dev_questions.jsonl"


def load_questions():
    return [json.loads(line) for line in QUESTIONS.read_text().splitlines() if line.strip()]


E2E = [q for q in load_questions() if q["e2e"]]


@pytest.fixture
def env(loaded, tmp_path):
    col = open_collection(tmp_path / "chroma", "test_docs")
    add_chunks(col, CHUNKS, embed_fn=fake_embed)
    toy = yaml.safe_load(TOY_YAML.read_text())
    toy["ticker"] = "TCS"          # toy numbers under the TCS ticker, only inside this test
    toy_path = tmp_path / "toy_as_tcs.yaml"
    toy_path.write_text(yaml.safe_dump(toy))
    return ToolEnv(conn=loaded, ticker="TCS", display=DISPLAY, collection=col, embed_fn=fake_embed,
                   dcf_assumptions=toy_path)


def gold_route_llm(q):
    """Returns the expected route. The composer writes each offered figure exactly as displayed,
    with its evidence id in brackets, and lists every number and evidence id offered.
    (Since M6 the verifier derives numbers_used from the text, so the text must contain figures.)"""
    exp = q["expected_route"]
    route = {"question_type": "out_of_scope" if exp["refuse"] else "numeric",
             "refusal_reason": exp["refusal_reason"] or "none",
             "calls": [c if c["tool"] != "search_documents" else {"tool": "search_documents", "query": q["question"]}
                       for c in exp["calls"]]}

    def reply(messages, schema):
        if "question_type" in schema["properties"]:
            return json.dumps(route)
        props = schema["properties"]

        def offered(field):          # an empty choice is sent as {"maxItems": 0}, without items
            return props[field].get("items", {}).get("enum", [])
        figures = re.findall(r"^- \[([^\]#]+)#[^\]]+\] ([^:\n]+): (.+)$", messages[-1]["content"], re.M)
        text = " ".join(f"{label}: {shown} [{eid}]." for eid, label, shown in figures) or \
            "Answer written from the passages only."
        return json.dumps({"answer_text": text,
                           "used_number_ids": offered("used_number_ids"),
                           "cited_evidence_ids": offered("cited_evidence_ids")})
    return ScriptedLLM(reply)


def test_there_are_ten_e2e_questions_covering_every_route_type():
    assert len(E2E) == 10
    assert all(q["status"] == "PROVISIONAL" for q in load_questions())
    tools = {c["tool"] for q in E2E for c in q["expected_route"]["calls"]}
    assert tools == {"get_financial_fact", "compute_ratio", "run_dcf", "search_documents"}
    assert any(q["expected_route"]["refuse"] for q in E2E)


@pytest.mark.parametrize("q", E2E, ids=[q["id"] for q in E2E])
def test_end_to_end_answer_has_evidence_ids_filled(env, q):
    a = answer_question(q["question"], env, gold_route_llm(q))
    if q["expected_route"]["refuse"]:
        assert a.refused and a.numbers_used == [] and a.citations == []
        return
    assert not a.refused, a.answer_text
    assert a.answer_text and a.citations
    cited = {c.evidence_id: c for c in a.citations}
    tool_numbers = {n.number_id for r in a.tool_results for n in r.numbers}
    for n in a.numbers_used:
        assert n.number_id in tool_numbers            # every number came from a tool result
        assert n.evidence_id in cited                 # ... and points at a citation
    for c in a.citations:
        if c.kind in ("fact", "doc_chunk"):
            assert c.source_id is not None and c.page is not None and c.period
        if c.kind == "fact":
            assert c.basis == "consolidated"
        if c.kind == "calc":
            assert c.formula and c.input_evidence_ids and set(c.input_evidence_ids) <= set(cited)
        if c.kind == "dcf_run":
            assert c.period                            # valuation date
    numeric = [x for x in q["expected_route"]["calls"] if x["tool"] != "search_documents"]
    assert bool(a.numbers_used) == bool(numeric)


def test_routing_accuracy_is_measured_on_the_dev_questions(env):
    tally = RoutingTally()
    for q in load_questions():
        a = answer_question(q["question"], env, gold_route_llm(q))
        tally.add(q["id"], score_route(a.route, q["expected_route"]))
    assert tally.n == 20 and tally.full_correct == 20    # the scripted LLM returns the gold route
    assert "20 of 20" in tally.summary()
