"""M5: Router v1, step 1 (the LLM picks tools and arguments from a fixed list) and route scoring.

The LLM is a scripted fake here; the real model is exercised by tests/run_provisional_dev.py.
"""
import json
import re

import pytest

from erp.agent.llm import load_agent_config
from erp.agent.route_score import RoutingTally, score_route
from erp.agent.router import (RoutePlan, build_catalog, metric_names, metrics_named_in, route, route_schema,
                              router_messages, search_year)
from erp.agent.tools import TOOL_NAMES, SearchArgs, ToolCall
from fakes import ScriptedLLM
from test_dcf_run import TOY_YAML

CFG = load_agent_config()


@pytest.fixture
def catalog(loaded, tmp_path):
    return build_catalog(loaded, "TCS", dcf_assumptions=TOY_YAML)


def plan_from(catalog, reply: dict | str, max_calls=4) -> RoutePlan:
    text = reply if isinstance(reply, str) else json.dumps(reply)
    return route("q?", catalog, ScriptedLLM(lambda m, s: text), max_calls=max_calls)


# ---------- catalog and schema: the fixed lists come from config and the database ----------

def test_catalog_lists_come_from_config_and_db(catalog):
    assert "revenue_from_operations" in catalog.metrics and "net_margin" in catalog.ratios
    assert catalog.periods == ["FY25", "FY26"]          # periods in the database, not invented
    assert {"base", "bear"} <= set(catalog.scenarios)     # scenario names from the assumptions file


def test_catalog_without_assumptions_file_has_no_scenarios(loaded, tmp_path):
    assert build_catalog(loaded, "TCS", dcf_assumptions=tmp_path / "none.yaml").scenarios == []


def test_schema_constrains_tools_and_arguments_to_the_fixed_lists(catalog):
    schema = route_schema(catalog, max_calls=4)
    item = schema["properties"]["calls"]["items"]["properties"]
    assert set(item["tool"]["enum"]) == set(TOOL_NAMES)
    assert set(catalog.metrics) <= set(item["metric_id"]["enum"])
    assert set(catalog.ratios) <= set(item["ratio_id"]["enum"])
    assert set(item["period"]["enum"]) - {None} == {"FY25", "FY26"}
    assert schema["properties"]["calls"]["maxItems"] == 4
    assert "out_of_scope" in schema["properties"]["question_type"]["enum"]


def test_router_prompt_names_every_option_and_has_no_advice_language(catalog):
    messages = router_messages("What was revenue in FY26?", catalog)
    system = messages[0]["content"]
    for name in [*TOOL_NAMES, *catalog.metrics, *catalog.ratios, *catalog.periods]:
        assert name in system
    for phrase in CFG["banned_phrases"]:
        assert not re.search(rf"\b{re.escape(phrase)}\b", system, re.I), phrase
    assert messages[-1] == {"role": "user", "content": "What was revenue in FY26?"}


# ---------- parsing the LLM's route ----------

def test_route_keeps_only_each_tools_own_arguments(catalog):
    plan = plan_from(catalog, {"question_type": "numeric", "refusal_reason": "none", "calls": [
        {"tool": "get_financial_fact", "metric_id": "revenue_from_operations", "period": "FY26",
         "basis": "consolidated", "ratio_id": "net_margin", "query": None},
        {"tool": "search_documents", "query": "cyber risk", "period": "FY26"}]})
    assert plan.calls == [
        ToolCall(tool="get_financial_fact",
                 args={"metric_id": "revenue_from_operations", "period": "FY26", "basis": "consolidated"}),
        ToolCall(tool="search_documents", args={"query": "cyber risk"})]
    assert not plan.refuse and plan.problems == []


def test_out_of_scope_route_runs_no_tools(catalog):
    plan = plan_from(catalog, {"question_type": "out_of_scope", "refusal_reason": "investment_advice",
                               "calls": [{"tool": "run_dcf", "scenario": "base"}]})
    assert plan.refuse and plan.refusal_reason == "investment_advice" and plan.calls == []


def test_refusal_reason_alone_also_refuses(catalog):
    plan = plan_from(catalog, {"question_type": "numeric", "refusal_reason": "other_company", "calls": []})
    assert plan.refuse and plan.refusal_reason == "other_company"


def test_out_of_scope_without_reason_gets_a_generic_reason(catalog):
    plan = plan_from(catalog, {"question_type": "out_of_scope", "refusal_reason": "none", "calls": []})
    assert plan.refuse and plan.refusal_reason == "outside_scope"


def test_unparseable_reply_is_a_routing_failure_not_a_guess(catalog):
    plan = plan_from(catalog, "Sure! I think revenue is the right tool.")
    assert plan.question_type == "routing_failed" and plan.calls == [] and plan.problems


def test_no_calls_and_no_refusal_is_a_routing_failure(catalog):
    plan = plan_from(catalog, {"question_type": "numeric", "refusal_reason": "none", "calls": []})
    assert plan.question_type == "routing_failed"


def test_too_many_calls_are_cut_and_reported(catalog):
    calls = [{"tool": "search_documents", "query": f"q{i}"} for i in range(6)]
    plan = plan_from(catalog, {"question_type": "qualitative", "refusal_reason": "none", "calls": calls},
                     max_calls=4)
    assert len(plan.calls) == 4 and any("cut" in p for p in plan.problems)


def test_router_sends_schema_and_question(catalog):
    llm = ScriptedLLM(lambda m, s: json.dumps({"question_type": "qualitative", "refusal_reason": "none",
                                                "calls": [{"tool": "search_documents", "query": "x"}]}))
    route("How is cyber risk managed?", catalog, llm, max_calls=4)
    (sent,) = llm.calls
    assert sent["schema"] == route_schema(catalog, max_calls=4)
    assert sent["messages"][-1]["content"] == "How is cyber risk managed?"


# ---------- scoring a route against the expected route ----------

def expected(refuse=False, calls=(), reason=None):
    return {"refuse": refuse, "refusal_reason": reason, "calls": list(calls)}


FACT = {"tool": "get_financial_fact", "metric_id": "revenue_from_operations", "period": "FY26", "basis": "consolidated"}


def plan(calls=(), refuse=False, reason="none"):
    return RoutePlan(question_type="out_of_scope" if refuse else "numeric", refusal_reason=reason,
                     calls=[ToolCall(tool=c["tool"], args={k: v for k, v in c.items() if k != "tool"}) for c in calls],
                     refuse=refuse)


def test_score_exact_match():
    s = score_route(plan([FACT]), expected(calls=[FACT]))
    assert s.tool_ok and s.full_ok


def test_score_right_tool_wrong_period():
    s = score_route(plan([{**FACT, "period": "FY25"}]), expected(calls=[FACT]))
    assert s.tool_ok and not s.full_ok


def test_score_search_query_text_is_not_compared():
    s = score_route(plan([{"tool": "search_documents", "query": "anything"}]),
                    expected(calls=[{"tool": "search_documents"}]))
    assert s.full_ok


def test_score_default_basis_counts_as_consolidated():
    s = score_route(plan([{k: v for k, v in FACT.items() if k != "basis"}]), expected(calls=[FACT]))
    assert s.full_ok


def test_score_extra_call_is_wrong():
    s = score_route(plan([FACT, {"tool": "search_documents", "query": "x"}]), expected(calls=[FACT]))
    assert not s.tool_ok and not s.full_ok


def test_score_call_order_does_not_matter():
    search = {"tool": "search_documents", "query": "x"}
    s = score_route(plan([search, FACT]), expected(calls=[FACT, {"tool": "search_documents"}]))
    assert s.full_ok


def test_score_refusal():
    assert score_route(plan(refuse=True, reason="investment_advice"),
                       expected(refuse=True, reason="investment_advice")).full_ok
    assert not score_route(plan([FACT]), expected(refuse=True, reason="investment_advice")).tool_ok
    wrong_reason = score_route(plan(refuse=True, reason="other_company"),
                               expected(refuse=True, reason="investment_advice"))
    assert wrong_reason.full_ok and not wrong_reason.reason_ok     # refusing is what is scored


def test_tally_reports_counts():
    t = RoutingTally()
    t.add("Q1", score_route(plan([FACT]), expected(calls=[FACT])))
    t.add("Q2", score_route(plan([{**FACT, "period": "FY25"}]), expected(calls=[FACT])))
    assert (t.n, t.tool_correct, t.full_correct) == (2, 2, 1)
    assert "1 of 2" in t.summary() and "2 of 2" in t.summary()


def test_schema_asks_for_calls_before_the_question_type(catalog):
    # Ollama fills fields in schema order; type-first made small models refuse plain lookups (P0.6).
    assert list(route_schema(catalog, max_calls=4)["properties"])[0] == "calls"


def test_examples_only_use_ids_the_company_has(catalog):
    system = router_messages("q", catalog)[0]["content"]
    assert '"metric_id": "total_equity"' in system
    reduced = catalog.model_copy(update={"metrics": {"revenue_from_operations": "Revenue from operations"}})
    assert '"metric_id": "total_equity"' not in router_messages("q", reduced)[0]["content"]


def test_dcf_example_only_when_a_scenario_exists(catalog):
    assert '"tool": "run_dcf"' in router_messages("q", catalog)[0]["content"]
    assert '"tool": "run_dcf"' not in router_messages("q", catalog.model_copy(update={"scenarios": []}))[0]["content"]


# ---------- R1: prefer the latest report unless the question names a year (decided by code) ----------

SEARCH_REPLY = {"question_type": "qualitative", "refusal_reason": "none",
                "calls": [{"tool": "search_documents", "query": "employee attrition"}]}


def route_q(catalog, question, reply=SEARCH_REPLY):
    return route(question, catalog, ScriptedLLM(lambda m, s: json.dumps(reply)), max_calls=4)


def test_search_without_a_year_prefers_the_latest_report(catalog):
    plan = route_q(catalog, "How does TCS retain talent?")
    assert plan.calls == [ToolCall(tool="search_documents", args={"query": "employee attrition"})]
    assert SearchArgs(**plan.calls[0].args).prefer_latest is True


@pytest.mark.parametrize("question", ["What did TCS say about attrition in FY24?",
                                      "How did TCS describe attrition in fiscal 2024?",
                                      "What was attrition in 2023-24?"])
def test_question_naming_a_year_turns_the_preference_off(catalog, question):
    plan = route_q(catalog, question)
    assert plan.calls == [ToolCall(tool="search_documents",
                                   args={"query": "employee attrition", "prefer_latest": False})]


def test_year_in_the_search_phrase_also_turns_it_off(catalog):
    reply = {**SEARCH_REPLY, "calls": [{"tool": "search_documents", "query": "attrition FY24"}]}
    plan = route_q(catalog, "How has attrition moved?", reply)
    assert plan.calls[0].args == {"query": "attrition FY24", "prefer_latest": False}


def test_the_model_cannot_set_the_preference(catalog):
    reply = {**SEARCH_REPLY, "calls": [{"tool": "search_documents", "query": "attrition", "prefer_latest": False}]}
    assert route_q(catalog, "How does TCS retain talent?", reply).calls[0].args == {"query": "attrition"}


def test_preference_only_touches_search_calls(catalog):
    reply = {"question_type": "mixed", "refusal_reason": "none", "calls": [
        {"tool": "get_financial_fact", "metric_id": "revenue_from_operations", "period": "FY26",
         "basis": "consolidated"},
        {"tool": "search_documents", "query": "revenue drivers"}]}
    plan = route_q(catalog, "What was revenue in FY26 and what drove it?", reply)
    assert plan.calls[0].args == {"metric_id": "revenue_from_operations", "period": "FY26", "basis": "consolidated"}
    # R2: the question names one fiscal year with data, so the search is also filtered to it.
    assert plan.calls[1].args == {"query": "revenue drivers", "fiscal_year": 2026, "prefer_latest": False}


# ---------- R2: a question naming one fiscal year filters the search to it (decided by code) ----------
# The test catalog has data for FY25 and FY26 only (sample facts).

def test_catalog_carries_the_fiscal_year_end_month(catalog):
    assert catalog.fiscal_year_end_month == 3            # from the company table, not hard-coded


@pytest.mark.parametrize("question", ["What did TCS say about attrition in FY25?",
                                      "How did TCS describe attrition in its FY 2025 annual report?",
                                      "How did TCS describe attrition in fiscal 2025?",
                                      "What was attrition in 2024-25?",
                                      "What did TCS say about attrition in FY25, compared with FY25 targets?"])
def test_question_naming_one_year_filters_the_search_to_it(catalog, question):
    plan = route_q(catalog, question)
    assert plan.calls == [ToolCall(tool="search_documents",
                                   args={"query": "employee attrition", "fiscal_year": 2025, "prefer_latest": False})]
    assert SearchArgs(**plan.calls[0].args).fiscal_year == 2025


def test_search_year_comes_from_the_period_resolver(catalog):
    # Same rule as the agent; fiscal_year = the year the fiscal year ends in (resolver), not the label's digits.
    assert search_year("Attrition in FY26?", catalog) == 2026
    assert search_year("Attrition?", catalog) is None


@pytest.mark.parametrize("question", ["How did attrition change between FY25 and FY26?",
                                      "Compare attrition in fiscal 2025 with 2025-26."])
def test_two_years_named_no_filter_and_no_preference(catalog, question):
    plan = route_q(catalog, question)
    assert plan.calls[0].args == {"query": "employee attrition", "prefer_latest": False}
    assert search_year(question, catalog) is None


@pytest.mark.parametrize("question", ["What did TCS say about attrition in FY22?",   # a year with no data
                                      "What did TCS say about attrition in Q1 FY27?",  # a quarter, not a year
                                      "Attrition in FY26 and in Q1 FY27?"])            # a year and a quarter
def test_no_filter_unless_exactly_one_known_fiscal_year(catalog, question):
    plan = route_q(catalog, question)
    assert plan.calls[0].args == {"query": "employee attrition", "prefer_latest": False}


def test_year_only_in_the_search_phrase_does_not_filter(catalog):
    reply = {**SEARCH_REPLY, "calls": [{"tool": "search_documents", "query": "attrition FY25"}]}
    assert route_q(catalog, "How has attrition moved?", reply).calls[0].args == \
        {"query": "attrition FY25", "prefer_latest": False}


def test_the_model_cannot_set_the_year_filter(catalog):
    reply = {**SEARCH_REPLY, "calls": [{"tool": "search_documents", "query": "attrition", "fiscal_year": 2025}]}
    assert route_q(catalog, "How does TCS retain talent?", reply).calls[0].args == {"query": "attrition"}
    assert "fiscal_year" not in route_schema(catalog, max_calls=4)["properties"]["calls"]["items"]["properties"]


def test_year_filter_only_touches_search_calls(catalog):
    reply = {"question_type": "numeric", "refusal_reason": "none", "calls": [
        {"tool": "get_financial_fact", "metric_id": "revenue_from_operations", "period": "FY25", "basis": "consolidated"}]}
    plan = route_q(catalog, "What was revenue in FY25?", reply)
    assert plan.calls[0].args == {"metric_id": "revenue_from_operations", "period": "FY25", "basis": "consolidated"}


# ---------- E2: a metric the question names by its own name (decided by code) ----------
# PDEV-07 pattern: "profit for the year, including non-controlling interests" was routed to
# profit_attributable_to_owners + non_controlling_interests (the inputs, not the line asked for).

PAT_QUESTIONS = ["What was TCS's profit for the year in FY26, including non-controlling interests?",
                 "What was TCS's profit for the year, including non-controlling interests, in FY26?"]


def fact(metric, period="FY26", basis="consolidated"):
    return {"tool": "get_financial_fact", "metric_id": metric, "period": period, "basis": basis}


def facts_reply(*calls, qtype="numeric"):
    return {"question_type": qtype, "refusal_reason": "none", "calls": list(calls)}


def test_metric_names_come_from_display_name_and_definition_opening(catalog):
    names = metric_names(catalog)
    assert {"profit after tax", "profit for the year including non controlling interests"} <= names["profit_after_tax"]
    assert "non controlling interests" in names["non_controlling_interests"]
    assert "equity" not in names["non_controlling_interests"]          # bracketed qualifiers are not names
    assert names["current_investments"] == set()                       # one word ("investments") is too loose
    assert "revenue from operations" in names["revenue_from_operations"]


@pytest.mark.parametrize("question,named", [
    (PAT_QUESTIONS[0], {"profit_after_tax"}),
    (PAT_QUESTIONS[1], {"profit_after_tax"}),
    ("What were non-controlling interests at the end of FY26?", {"non_controlling_interests"}),
    ("What was profit attributable to shareholders of the Company in FY26?", {"profit_attributable_to_owners"}),
    ("What were revenue from operations and total assets in FY26?", {"revenue_from_operations", "total_assets"}),
    ("What was TCS's equity in FY26?", set()),
    ("What was TCS's profit in FY26?", set()),
    ("What were lease liabilities at the end of FY26?", {"lease_liabilities_current", "lease_liabilities_non_current"}),
])
def test_metrics_named_in_the_question(catalog, question, named):
    assert metrics_named_in(question, catalog) == named


@pytest.mark.parametrize("question", PAT_QUESTIONS)
def test_named_metric_replaces_the_models_other_metrics(catalog, question):
    plan = route_q(catalog, question, facts_reply(fact("profit_attributable_to_owners"),
                                                  fact("non_controlling_interests")))
    assert plan.calls == [ToolCall(tool="get_financial_fact",
                                   args={"metric_id": "profit_after_tax", "period": "FY26", "basis": "consolidated"})]
    assert any("profit_after_tax" in p and "names" in p for p in plan.problems)


def test_named_metric_keeps_each_period_and_basis(catalog):
    q = "What was the profit for the year, including non-controlling interests, in FY25 and FY26 (standalone)?"
    plan = route_q(catalog, q, facts_reply(fact("profit_attributable_to_owners", "FY25", "standalone"),
                                           fact("non_controlling_interests", "FY25", "standalone"),
                                           fact("profit_attributable_to_owners", "FY26", "standalone")))
    assert [(c.args["metric_id"], c.args["period"], c.args["basis"]) for c in plan.calls] == [
        ("profit_after_tax", "FY25", "standalone"), ("profit_after_tax", "FY26", "standalone")]


@pytest.mark.parametrize("question,reply", [
    # the model already uses the named metric: unchanged
    (PAT_QUESTIONS[0], facts_reply(fact("profit_after_tax"))),
    # two metrics named: code does not choose between them
    ("What were revenue from operations and total assets in FY26?", facts_reply(fact("revenue_from_operations"))),
    # nothing named: the model's choice stands
    ("What was TCS's profit in FY26?", facts_reply(fact("profit_attributable_to_owners"))),
    # not a plain lookup (a search or a ratio is in the plan): unchanged
    (PAT_QUESTIONS[0], facts_reply(fact("profit_attributable_to_owners"),
                                   {"tool": "search_documents", "query": "profit"}, qtype="mixed")),
    (PAT_QUESTIONS[0], facts_reply({"tool": "compute_ratio", "ratio_id": "net_margin", "period": "FY26",
                                    "basis": "consolidated"}, qtype="ratio")),
    # fact lookups, but the model calls it mixed (e.g. a "why" question fetching related lines): unchanged
    ("Why was profit before tax lower than profit before exceptional items in FY26?",
     facts_reply(fact("profit_before_exceptional_items_and_tax"), fact("exceptional_legal_claim_provision"),
                 qtype="mixed")),
])
def test_named_metric_rule_leaves_other_plans_alone(catalog, question, reply):
    plan = route_q(catalog, question, reply)
    assert [(c.tool, c.args.get("metric_id") or c.args.get("ratio_id")) for c in plan.calls] == \
        [(c["tool"], c.get("metric_id") or c.get("ratio_id")) for c in reply["calls"]]
    assert not any("names" in p for p in plan.problems)
