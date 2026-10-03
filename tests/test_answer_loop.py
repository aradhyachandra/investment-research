"""M5: the agent loop (route -> run tools in code -> compose) and the structured Answer.

The LLM is a scripted fake. It answers the router step or the composer step depending on
which JSON schema it is sent.
"""
import json
import re

import pytest

from erp.agent.answer_schema import Answer
from erp.agent.llm import load_agent_config
from erp.agent.loop import REFUSAL_TEXT, answer_question, compose_messages, compose_schema
from erp.agent.tools import ToolCall, ToolEnv, run_tool
from fakes import ScriptedLLM, fake_embed
from test_agent_tools import CHUNKS, DISPLAY
from test_dcf_run import TOY_YAML
from erp.ingest.index_chroma import add_chunks, open_collection

CFG = load_agent_config()
FACT_REV26 = {"tool": "get_financial_fact", "metric_id": "revenue_from_operations", "period": "FY26",
              "basis": "consolidated"}


@pytest.fixture
def env(loaded, tmp_path):
    col = open_collection(tmp_path / "chroma", "test_docs")
    add_chunks(col, CHUNKS, embed_fn=fake_embed)
    return ToolEnv(conn=loaded, ticker="TCS", display=DISPLAY, collection=col, embed_fn=fake_embed,
                   dcf_assumptions=TOY_YAML)


def fake_llm(route: dict, compose=None):
    """route: the router's JSON. compose: function(user_prompt) -> composer JSON dict."""
    def reply(messages, schema):
        if "question_type" in schema["properties"]:
            return json.dumps(route)
        return json.dumps(compose(messages[-1]["content"]) if compose else {})
    return ScriptedLLM(reply)


def numeric_route(*calls):
    return {"question_type": "numeric", "refusal_reason": "none", "calls": list(calls)}


def ids_in(prompt: str, prefix: str) -> list[str]:
    return re.findall(rf"\[({prefix}[^\]#]*(?:#[a-z_0-9]+)?)\]", prompt)


# ---------- the happy path ----------

def test_numeric_answer_has_numbers_pointing_at_evidence(env):
    def compose(prompt):
        (nid,) = ids_in(prompt, "fact:")
        return {"answer_text": f"TCS's consolidated revenue from operations in FY26 was INR 267,021 crore "
                               f"[{nid.split('#')[0]}].", "used_number_ids": [nid],
                "cited_evidence_ids": [nid.split("#")[0]]}
    a = answer_question("What was revenue in FY26?", env, fake_llm(numeric_route(FACT_REV26), compose))
    assert isinstance(a, Answer)
    assert not a.refused and a.composed_by == "llm"
    (n,) = a.numbers_used
    assert n.display == "INR 267,021 crore" and n.evidence_id.startswith("fact:")
    assert [c.evidence_id for c in a.citations] == [n.evidence_id]
    assert a.citations[0].page == 167 and a.citations[0].period == "FY26" and a.citations[0].basis == "consolidated"
    assert any("Not yet checked by a human" in x for x in a.limitations)
    assert "not investment advice" in a.disclaimer.lower()
    assert a.model == "scripted-fake"


def test_ratio_citations_include_the_input_facts(env):
    route = numeric_route({"tool": "compute_ratio", "ratio_id": "net_margin", "period": "FY26"})

    def compose(prompt):
        nid = ids_in(prompt, "calc:")[0]
        return {"answer_text": f"Net margin in FY26 was 18.43% [{nid.split('#')[0]}].",
                "used_number_ids": [nid], "cited_evidence_ids": []}
    a = answer_question("Net margin FY26?", env, fake_llm(route, compose))
    (n,) = a.numbers_used
    assert n.evidence_id.startswith("calc:")
    kinds = [c.kind for c in a.citations]
    assert kinds == ["calc", "fact", "fact"]          # the calculation, then the two facts it used
    assert a.citations[0].formula and a.citations[0].input_evidence_ids == [c.evidence_id for c in a.citations[1:]]


def test_qualitative_answer_cites_chunks(env):
    route = {"question_type": "qualitative", "refusal_reason": "none",
             "calls": [{"tool": "search_documents", "query": "cyber attacks"}]}

    def compose(prompt):
        return {"answer_text": "TCS runs security operations centres [chunk:c-cyber].",
                "used_number_ids": [], "cited_evidence_ids": ["chunk:c-cyber"]}
    a = answer_question("How does TCS manage cyber risk?", env, fake_llm(route, compose))
    assert a.numbers_used == [] and [c.evidence_id for c in a.citations] == ["chunk:c-cyber"]
    assert a.citations[0].page == 64 and a.citations[0].source_id == 1


# ---------- the LLM is held to the tool output ----------

def test_unknown_number_ids_from_the_llm_are_dropped(env):
    def compose(prompt):
        (nid,) = ids_in(prompt, "fact:")
        return {"answer_text": "Revenue was INR 267,021 crore.", "used_number_ids": [nid, "fact:999#value"],
                "cited_evidence_ids": ["chunk:made-up"]}
    a = answer_question("Revenue FY26?", env, fake_llm(numeric_route(FACT_REV26), compose))
    assert [n.number_id for n in a.numbers_used] == [n.number_id for n in a.tool_results[0].numbers]
    assert all(c.evidence_id != "chunk:made-up" for c in a.citations)
    assert any("fact:999#value" in w for w in a.warnings) and any("chunk:made-up" in w for w in a.warnings)


def test_no_number_ids_listed_attaches_all_tool_numbers_with_a_warning(env):
    a = answer_question("Revenue FY26?", env, fake_llm(numeric_route(FACT_REV26), lambda p: {
        "answer_text": "Revenue was INR 267,021 crore.", "used_number_ids": [], "cited_evidence_ids": []}))
    assert len(a.numbers_used) == 1 and a.citations
    assert any("did not list" in w for w in a.warnings)


@pytest.mark.parametrize("bad", ["You should buy TCS now.", "At this level TCS looks undervalued.",
                                 "A target price of 5000 seems fair."])
def test_advice_language_is_replaced_by_the_template_answer(env, bad):
    a = answer_question("Revenue FY26?", env, fake_llm(numeric_route(FACT_REV26), lambda p: {
        "answer_text": bad, "used_number_ids": [], "cited_evidence_ids": []}))
    assert a.composed_by == "template" and bad not in a.answer_text
    assert "INR 267,021 crore" in a.answer_text and a.numbers_used and a.citations
    assert any("advice" in w.lower() for w in a.warnings)


def test_unparseable_composer_reply_falls_back_to_template(env):
    llm = ScriptedLLM(lambda m, s: json.dumps(numeric_route(FACT_REV26)) if "question_type" in s["properties"]
                      else "not json")
    a = answer_question("Revenue FY26?", env, llm)
    assert a.composed_by == "template" and "INR 267,021 crore" in a.answer_text and a.numbers_used


def test_composer_schema_only_allows_known_ids(env):
    llm = fake_llm(numeric_route(FACT_REV26), lambda p: {"answer_text": "x", "used_number_ids": [],
                                                         "cited_evidence_ids": []})
    answer_question("Revenue FY26?", env, llm)
    schema = llm.calls[1]["schema"]["properties"]
    (nid,) = schema["used_number_ids"]["items"]["enum"]
    assert nid.startswith("fact:") and nid.endswith("#value")


def test_composer_schema_never_has_an_empty_enum(env):
    # Ollama answers HTTP 400 to an empty enum; a search-only answer has no number ids.
    results = [run_tool(ToolCall(tool="search_documents", args={"query": "cyber attacks"}), env)]
    schema = compose_schema(results)["properties"]
    assert schema["used_number_ids"] == {"type": "array", "maxItems": 0}
    assert schema["cited_evidence_ids"]["items"]["enum"]


def test_composer_prompt_has_display_strings_and_no_advice_language(env):
    results = [run_tool(ToolCall(tool="get_financial_fact", args={"metric_id": "revenue_from_operations",
                                                                 "period": "FY26"}), env)]
    messages = compose_messages("Revenue FY26?", "TCS", results, [])
    text = " ".join(m["content"] for m in messages)
    assert "INR 267,021 crore" in text and "267021" not in text     # only the code-formatted figure
    for phrase in CFG["banned_phrases"]:
        assert not re.search(rf"\b{re.escape(phrase)}\b", messages[0]["content"], re.I), phrase


# ---------- refusals and failures ----------

@pytest.mark.parametrize("reason", ["investment_advice", "price_prediction", "other_company", "outside_data"])
def test_refusal_runs_no_tools_and_no_composer(env, reason):
    llm = fake_llm({"question_type": "out_of_scope", "refusal_reason": reason, "calls": []})
    a = answer_question("?", env, llm)
    assert a.refused and a.refusal_reason == reason and a.composed_by == "refusal"
    assert a.tool_results == [] and a.numbers_used == [] and a.citations == []
    assert len(llm.calls) == 1                       # router only
    assert a.answer_text == REFUSAL_TEXT[reason]


def test_refusal_texts_have_no_advice_language():
    for text in REFUSAL_TEXT.values():
        for phrase in CFG["banned_phrases"]:
            assert not re.search(rf"\b{re.escape(phrase)}\b", text, re.I), (phrase, text)


def test_every_tool_failing_is_a_refusal_with_the_reasons(env):
    llm = fake_llm(numeric_route({**FACT_REV26, "period": "FY22"}))
    a = answer_question("Revenue FY22?", env, llm)
    assert a.refused and a.refusal_reason == "data_not_available"
    assert "FY22" in a.answer_text and a.numbers_used == []
    assert len(llm.calls) == 1                       # nothing to compose from


def test_partial_failure_answers_with_what_worked_and_lists_the_gap(env):
    route = numeric_route(FACT_REV26, {**FACT_REV26, "period": "FY22"})

    def compose(prompt):
        assert "NOT AVAILABLE" in prompt and "FY22" in prompt
        (nid,) = ids_in(prompt, "fact:")
        return {"answer_text": "FY26 revenue was INR 267,021 crore; FY22 is not available.",
                "used_number_ids": [nid], "cited_evidence_ids": []}
    a = answer_question("Revenue FY26 and FY22?", env, fake_llm(route, compose))
    assert not a.refused and len(a.numbers_used) == 1
    assert any("FY22" in x for x in a.limitations)


def test_routing_failure_is_a_refusal(env):
    a = answer_question("?", env, ScriptedLLM(lambda m, s: "no json here"))
    assert a.refused and a.refusal_reason == "routing_failed" and a.tool_results == []
