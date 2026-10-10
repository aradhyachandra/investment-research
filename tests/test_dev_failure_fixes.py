"""Fixes for the M7 dev-split failures (2026-10-04), with regression tests on NEW phrasings.

None of the questions or sentences here are copied from eval/questions.jsonl; they test the
same causes with different wording and different numbers (overfitting rule, PROGRESS.md):

1. Router over-refusal. A question about what a period label means had no tool to go to, and the
   router prompt said "a figure not in the allowed values -> outside_data", so a line item that is
   not a SQLite metric (it may still be printed in the filings) was refused or swapped for an
   unrelated metric. Fix: an `explain_period` tool (dates from the period resolver and the
   company config), router rules that send non-metric figures to search_documents, and
   outside_data decided by code for fact/ratio calls on periods with no data.
2. Verifier false rejection. "<growth figure>, which is lower than <another figure>" was read as
   "the growth figure says a decrease"; it is an ordering of two written figures. Fix: "higher /
   lower than <figure>" with a figure on each side compares the two figures as written.

Sample facts (INR crore): revenue FY26 267,021, FY25 255,324 -> revenue growth FY26 4.58%
((267021 - 255324) / 255324 x 100 = 4.5813). Passage c-cust says "10% or more of revenue".
"""
import json

import pytest

from erp.agent.llm import load_agent_config
from erp.agent.loop import answer_question
from erp.agent.router import build_catalog, route, route_schema, router_messages
from erp.agent.tools import TOOL_NAMES, ToolCall, ToolEnv, run_tool
from erp.agent.verifier import verify_answer
from erp.ingest.index_chroma import add_chunks, open_collection
from fakes import ScriptedLLM, fake_embed
from test_agent_tools import CHUNKS, DISPLAY
from test_dcf_run import TOY_YAML

CFG = load_agent_config()


@pytest.fixture
def env(loaded, tmp_path):
    col = open_collection(tmp_path / "chroma", "test_docs")
    add_chunks(col, CHUNKS, embed_fn=fake_embed)
    return ToolEnv(conn=loaded, ticker="TCS", display=DISPLAY, collection=col, embed_fn=fake_embed,
                   dcf_assumptions=TOY_YAML)


@pytest.fixture
def catalog(loaded):
    return build_catalog(loaded, "TCS", dcf_assumptions=TOY_YAML)


def run(env, tool, **args):
    return run_tool(ToolCall(tool=tool, args=args), env)


def plan_for(question, catalog, reply: dict, max_calls=4):
    llm = ScriptedLLM(lambda m, s: json.dumps(reply))
    return route(question, catalog, llm, max_calls=max_calls), llm


# ---------- 1a. explain_period: a deterministic tool for "what does this period mean" ----------

def test_explain_period_is_a_tool():
    assert "explain_period" in TOOL_NAMES


def test_explain_period_gives_fiscal_dates_from_config(env):
    r = run(env, "explain_period", period="FY25")
    assert r.ok and r.numbers == []                       # dates, not figures
    text = " ".join(r.notes)
    assert "1 April 2024" in text and "31 March 2025" in text
    assert "not calendar year 2025" in text               # the trap the question type is about
    (ev,) = r.evidence
    assert ev.kind == "config" and ev.evidence_id == "period:FY25"
    assert "fiscal_year_end_month" in ev.source_title     # the answer is traceable to the config


def test_explain_period_works_for_quarters_and_periods_without_data(env):
    r = run(env, "explain_period", period="Q3 FY24")     # no facts for it; the dates are still known
    assert r.ok
    text = " ".join(r.notes)
    assert "1 October 2023" in text and "31 December 2023" in text and "FY24" in text
    assert r.evidence[0].evidence_id == "period:Q3_FY24"   # no space inside an evidence id


@pytest.mark.parametrize("bad", ["FY2025", "calendar 2025", "fy25", ""])
def test_explain_period_refuses_labels_it_cannot_read(env, bad):
    r = run(env, "explain_period", period=bad)
    assert not r.ok and r.error


# ---------- 1b. router: period questions and non-metric figures are not refused ----------

def test_router_prompt_sends_non_metric_figures_to_search_and_limits_outside_data(catalog):
    system = router_messages("x", catalog)[0]["content"]
    assert "explain_period" in system
    # the old rule refused any figure missing from the metric list
    assert "needs a period or figure that is not in the allowed values" not in system
    assert "Never substitute a different metric_id" in system


def test_periods_named_in_the_question_become_allowed_values(catalog):
    q = "Which months does Q3 FY24 cover?"
    plan, llm = plan_for(q, catalog, {"calls": [{"tool": "explain_period", "period": "Q3 FY24"}],
                                      "question_type": "period", "refusal_reason": "none"})
    schema = llm.calls[0]["schema"]
    assert "Q3 FY24" in schema["properties"]["calls"]["items"]["properties"]["period"]["enum"]
    assert not plan.refuse and plan.calls[0].tool == "explain_period"
    assert plan.calls[0].args == {"period": "Q3 FY24"}


def test_schema_without_question_periods_is_unchanged(catalog):
    enum = route_schema(catalog, max_calls=4)["properties"]["calls"]["items"]["properties"]["period"]["enum"]
    assert set(enum) - {None} == {"FY25", "FY26"}


def test_fact_call_for_a_period_with_no_data_is_refused_by_code(catalog):
    # e.g. "What was TCS's cash in FY21?": the model may now pick FY21 (named in the question);
    # code, not the model, decides that this is outside the data.
    plan, _ = plan_for("What was TCS's cash in FY21?", catalog, {
        "calls": [{"tool": "get_financial_fact", "metric_id": "cash_and_equivalents", "period": "FY21"}],
        "question_type": "numeric", "refusal_reason": "none"})
    assert plan.refuse and plan.refusal_reason == "outside_data" and plan.calls == []


def test_one_missing_period_next_to_a_good_call_keeps_the_good_call(catalog):
    plan, _ = plan_for("Revenue in FY21 and FY26?", catalog, {
        "calls": [{"tool": "get_financial_fact", "metric_id": "revenue_from_operations", "period": "FY21"},
                  {"tool": "get_financial_fact", "metric_id": "revenue_from_operations", "period": "FY26"}],
        "question_type": "numeric", "refusal_reason": "none"})
    assert not plan.refuse and len(plan.calls) == 2      # the FY21 lookup fails in the tool and is reported


# ---------- 1c. end to end: a period question is answered from config, with a citation ----------

def period_llm(text):
    def reply(messages, schema):
        if "question_type" in schema["properties"]:
            return json.dumps({"calls": [{"tool": "explain_period", "period": "FY25"}],
                               "question_type": "period", "refusal_reason": "none"})
        return json.dumps({"answer_text": text, "used_number_ids": [], "cited_evidence_ids": ["period:FY25"]})
    return ScriptedLLM(reply)


def test_period_question_is_answered_with_config_evidence(env):
    a = answer_question("Does FY25 mean calendar 2025?", env, period_llm(
        "No. FY25 is TCS's fiscal year from 1 April 2024 to 31 March 2025, not calendar year 2025 [period:FY25]."))
    assert not a.refused and a.composed_by == "llm", a.warnings
    assert [c.evidence_id for c in a.citations] == ["period:FY25"]


def test_period_answer_with_a_wrong_date_is_rejected(env):
    a = answer_question("Does FY25 mean calendar 2025?", env, period_llm(
        "FY25 runs from 1 January 2025 to 31 December 2025 [period:FY25]."))
    assert a.composed_by == "template"                    # the verifier caught the made-up dates
    assert "1 April 2024" in a.answer_text                # the template carries the config dates
    assert [c.evidence_id for c in a.citations] == ["period:FY25"]


# ---------- 2. verifier: "lower/higher than <figure>" orders two written figures ----------

def verify(text, results):
    return verify_answer(text, results, cfg=CFG)


def errors(report):
    return [i.check for i in report.issues if i.severity == "error"]


def test_true_figure_comparison_with_a_growth_rate_passes(env):
    # Same shape as the false rejection: a positive growth rate "lower than" a larger passage figure.
    g = run(env, "compute_ratio", ratio_id="revenue_growth_yoy", period="FY26")
    s = run(env, "search_documents", query="single customer revenue")
    rep = verify(f"Revenue growth was 4.58% in FY26 [{g.numbers[0].evidence_id}], which is lower than the 10% "
                 f"threshold the notes use for a single customer [chunk:c-cust].", [g, s])
    assert rep.ok, rep.issues


@pytest.mark.parametrize("text", [
    "Revenue growth was 4.58% in FY26, which is higher than the 10% threshold for a single customer.",
    "The 10% threshold for a single customer is lower than revenue growth of 4.58% in FY26.",
])
def test_false_figure_comparison_is_caught(env, text):
    g = run(env, "compute_ratio", ratio_id="revenue_growth_yoy", period="FY26")
    s = run(env, "search_documents", query="single customer revenue")
    assert "comparison_wrong_direction" in errors(verify(text, [g, s]))


def test_figure_comparison_across_units_is_caught(env):
    g = run(env, "compute_ratio", ratio_id="revenue_growth_yoy", period="FY26")
    rep = verify("Revenue growth of 4.58% in FY26 was lower than revenue of INR 267,021 crore.", [g])
    assert "comparison_unsupported" in errors(rep)


def test_figure_comparison_between_two_tool_figures(env):
    r26 = run(env, "get_financial_fact", metric_id="revenue_from_operations", period="FY26")
    r25 = run(env, "get_financial_fact", metric_id="revenue_from_operations", period="FY25")
    assert verify("Revenue of INR 267,021 crore in FY26 was higher than INR 255,324 crore in FY25.", [r26, r25]).ok
    rep = verify("Revenue of INR 255,324 crore in FY25 was higher than INR 267,021 crore in FY26.", [r26, r25])
    assert "comparison_wrong_direction" in errors(rep)


def test_other_direction_words_in_the_sentence_are_still_checked(env):
    # The ordering rule covers only "lower/higher than <figure>"; "fell" still has to match the sign.
    g = run(env, "compute_ratio", ratio_id="revenue_growth_yoy", period="FY26")
    s = run(env, "search_documents", query="single customer revenue")
    assert verify("Revenue grew 4.58% in FY26, which is lower than the 10% customer threshold.", [g, s]).ok
    rep = verify("Revenue fell 4.58% in FY26, which is lower than the 10% customer threshold.", [g, s])
    assert "comparison_wrong_direction" in errors(rep)


# ---------- 1d. a figure that is not a listed metric goes to the filings, not a substitute ----------

def test_not_listed_is_a_metric_choice(catalog):
    enum = route_schema(catalog, max_calls=4)["properties"]["calls"]["items"]["properties"]["metric_id"]["enum"]
    assert "not_listed" in enum
    assert "not_listed" in router_messages("x", catalog)[0]["content"]


def test_not_listed_fact_call_becomes_a_search_with_the_question(catalog):
    q = "What did TCS spend on rent in FY26?"
    plan, _ = plan_for(q, catalog, {"calls": [{"tool": "get_financial_fact", "metric_id": "not_listed",
                                               "period": "FY26"}],
                                    "question_type": "numeric", "refusal_reason": "none"})
    assert not plan.refuse
    # R1/R2: the question names FY26 (which has data), so the search is filtered to FY26, no recency weight.
    assert [(c.tool, c.args) for c in plan.calls] == [
        ("search_documents", {"query": q, "fiscal_year": 2026, "prefer_latest": False})]
    assert any("not_listed" in p for p in plan.problems)


@pytest.mark.parametrize("reason", ["outside_data", "investment_advice", "price_prediction"])
def test_refusal_that_contradicts_a_not_listed_call_is_overridden(catalog, reason):
    # Seen live (2026-10-04): a lease-cost question -> not_listed + out_of_scope / investment_advice.
    plan, _ = plan_for("What did TCS spend on rent in FY26?", catalog, {
        "calls": [{"tool": "get_financial_fact", "metric_id": "not_listed", "period": "FY26"}],
        "question_type": "out_of_scope", "refusal_reason": reason})
    assert not plan.refuse and plan.calls[0].tool == "search_documents"
    assert any("refused" in p for p in plan.problems)


def test_other_company_refusal_still_stands_with_a_not_listed_call(catalog):
    plan, _ = plan_for("What did a rival spend on rent?", catalog, {
        "calls": [{"tool": "get_financial_fact", "metric_id": "not_listed", "period": "FY26"}],
        "question_type": "out_of_scope", "refusal_reason": "other_company"})
    assert plan.refuse and plan.refusal_reason == "other_company"


def test_refusal_without_a_not_listed_call_still_stands(catalog):
    plan, _ = plan_for("Is this a sensible holding?", catalog, {
        "calls": [{"tool": "get_financial_fact", "metric_id": "total_equity", "period": "FY26"}],
        "question_type": "out_of_scope", "refusal_reason": "investment_advice"})
    assert plan.refuse and plan.refusal_reason == "investment_advice"


# ---------- 1e. a future period: refused as a forecast unless the question is what it means ----------

def routed_llm(route_reply: dict, text: str = ""):
    def reply(messages, schema):
        if "question_type" in schema["properties"]:
            return json.dumps(route_reply)
        return json.dumps({"answer_text": text, "used_number_ids": [], "cited_evidence_ids": []})
    return ScriptedLLM(reply)


def test_dates_of_a_period_after_the_latest_data_are_explained(env):
    # Latest data in the sample DB is Q1 FY27 (fact sheet); Q3 FY27 is later.
    llm = routed_llm({"calls": [{"tool": "explain_period", "period": "Q3 FY27"}], "question_type": "period",
                      "refusal_reason": "none"},
                     "Q3 FY27 runs from 1 October 2026 to 31 December 2026 [period:Q3_FY27].")
    a = answer_question("Which months make up Q3 FY27?", env, llm)
    assert not a.refused and a.composed_by == "llm", (a.answer_text, a.warnings)


@pytest.mark.parametrize("route_reply", [
    # the model substitutes a period that has data: still a forecast question
    {"calls": [{"tool": "get_financial_fact", "metric_id": "revenue_from_operations", "period": "FY26"}],
     "question_type": "numeric", "refusal_reason": "none"},
    # a period explanation next to a figure lookup is not "explain only"
    {"calls": [{"tool": "explain_period", "period": "FY29"},
               {"tool": "get_financial_fact", "metric_id": "revenue_from_operations", "period": "FY26"}],
     "question_type": "mixed", "refusal_reason": "none"},
    {"calls": [], "question_type": "out_of_scope", "refusal_reason": "outside_data"},
])
def test_figures_for_a_period_after_the_latest_data_are_still_refused(env, route_reply):
    llm = routed_llm(route_reply)
    a = answer_question("How big will TCS's revenue be in FY29?", env, llm)
    assert a.refused and a.refusal_reason == "outside_data" and a.tool_results == []
    assert len(llm.calls) == 1                            # the router only; no tool, no composer


# ---------- a change between two named years needs both years (enforced in code) ----------

def test_year_the_router_left_out_is_added(catalog):
    plan, _ = plan_for("Did net margin improve between FY25 and FY26?", catalog, {
        "calls": [{"tool": "compute_ratio", "ratio_id": "net_margin", "period": "FY26"}],
        "question_type": "ratio", "refusal_reason": "none"})
    assert sorted(c.args["period"] for c in plan.calls) == ["FY25", "FY26"]
    assert all(c.args["ratio_id"] == "net_margin" for c in plan.calls)
    assert any("added compute_ratio for FY25" in p for p in plan.problems)


def test_no_year_is_added_for_one_named_period_or_beyond_max_calls(catalog):
    plan, _ = plan_for("What was net margin in FY26?", catalog, {
        "calls": [{"tool": "compute_ratio", "ratio_id": "net_margin", "period": "FY26"}],
        "question_type": "ratio", "refusal_reason": "none"})
    assert len(plan.calls) == 1
    plan, _ = plan_for("Revenue and equity, FY25 versus FY26?", catalog, {
        "calls": [{"tool": "get_financial_fact", "metric_id": "revenue_from_operations", "period": "FY26"},
                  {"tool": "get_financial_fact", "metric_id": "total_equity", "period": "FY26"}],
        "question_type": "numeric", "refusal_reason": "none"}, max_calls=3)
    assert len(plan.calls) == 3                          # one year added, the next would exceed max_calls
