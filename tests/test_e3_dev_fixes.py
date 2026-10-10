"""E3: fixes for the v1.1 dev failures (docs/E2_eval_v1_1.md). Written before the code.

1. Named ratio (V11-C05 pattern): the question uses exactly one ratio's own name and the plan does
   not call that ratio -> code replaces the plan with compute_ratio for it (same safeguards as E2's
   named-metric rule).
2. Ratios that span years (V11-C11 pattern): a CAGR or a year-on-year growth ratio is called once,
   for the period the question names, not once per year in the range.
3. Groups of metrics (V11-E01 pattern): a question asking about "the exceptional item(s)" of a year
   gets the stored exceptional_* facts for that year, not only a search.
4. H routing (V11-H01 pattern): a trend question is routed right only if its fact/ratio calls cover
   every fiscal year in the range the question names.

Every question here is a new phrasing: none is in eval/questions.jsonl or eval/questions_v1_1.jsonl
(checked by exact text when written). The LLM is a scripted fake.
"""
import json

import pytest

from erp.agent.loop import answer_question
from erp.agent.router import build_catalog, metric_groups, names_in, ratio_names, route
from erp.db.load_facts import load_rows
from erp.eval.score import load_eval_config, routing_check
from fakes import ScriptedLLM
from test_d3_history import all_rows
from test_dcf_run import TOY_YAML
from test_eval_harness import CFG, llm, q
from test_m5_acceptance import env  # noqa: F401  (fixture: sample DB, fake Chroma, TOY DCF)

ECFG = load_eval_config()


@pytest.fixture
def catalog(loaded):
    """Sample DB: FY25 and FY26."""
    return build_catalog(loaded, "TCS", dcf_assumptions=TOY_YAML)


@pytest.fixture
def full_catalog(conn, ctx):
    """The whole manual CSV: FY23-FY26, including the exceptional_* lines."""
    load_rows(conn, all_rows(), ctx, entry_method="llm_extracted")
    return build_catalog(conn, "TCS", dcf_assumptions=TOY_YAML)


def route_q(catalog, question, reply, max_calls=4):
    return route(question, catalog, ScriptedLLM(lambda m, s: json.dumps(reply)), max_calls=max_calls)


def fact(metric, period="FY26", basis="consolidated"):
    return {"tool": "get_financial_fact", "metric_id": metric, "period": period, "basis": basis}


def ratio(ratio_id, period="FY26", basis="consolidated"):
    return {"tool": "compute_ratio", "ratio_id": ratio_id, "period": period, "basis": basis}


def search(query):
    return {"tool": "search_documents", "query": query}


def reply(*calls, qtype="numeric"):
    return {"question_type": qtype, "refusal_reason": "none", "calls": list(calls)}


def shape(plan):
    return [(c.tool, c.args.get("metric_id") or c.args.get("ratio_id"), c.args.get("period")) for c in plan.calls]


# ---------- 1. named ratio ----------

def test_ratio_names_come_from_display_names_not_formula_openings(catalog):
    names = ratio_names(catalog)
    assert "effective tax rate" in names["effective_tax_rate"]
    assert "operating margin" in names["operating_margin"]           # "(EBIT margin)" qualifier dropped
    assert "revenue cagr" in names["revenue_cagr_3y"]
    assert "return on equity" in names["return_on_equity"]
    # A definition that opens with an input line ("Total tax expense ...", "Profit attributable to
    # shareholders of the Company ...") describes the formula, not the ratio: not a name.
    assert "total tax expense" not in names["effective_tax_rate"]
    assert not any("profit attributable" in n for n in names["net_margin"])


@pytest.mark.parametrize("question,named", [
    ("Give me the effective tax rate TCS paid for FY25.", {("ratio", "effective_tax_rate")}),
    ("What return on equity did TCS earn in FY26?", {("ratio", "return_on_equity")}),
    ("Show TCS's tax expense and its effective tax rate for FY26.",
     {("ratio", "effective_tax_rate"), ("metric", "tax_expense")}),
    ("Compare TCS's net margin and operating margin for FY26.", {("ratio", "net_margin"), ("ratio", "operating_margin")}),
    ("How much total tax expense did TCS record in FY26?", {("metric", "tax_expense")}),
])
def test_names_in_the_question_cover_metrics_and_ratios(catalog, question, named):
    assert names_in(question, catalog) == named


@pytest.mark.parametrize("question,plan_reply,expected", [
    # the C05 pattern: two input facts instead of the ratio
    ("Give me the effective tax rate TCS paid for FY25.",
     reply(fact("tax_expense", "FY25"), fact("profit_before_tax", "FY25")),
     [("compute_ratio", "effective_tax_rate", "FY25")]),
    # the wrong ratio, model says "ratio"
    ("What return on equity did TCS earn in FY26?",
     reply(ratio("net_margin"), qtype="ratio"),
     [("compute_ratio", "return_on_equity", "FY26")]),
    # one call per period of the plan, in order
    ("Tell me TCS's operating margin in FY25 and in FY26.",
     reply(ratio("net_margin", "FY25"), ratio("net_margin", "FY26"), qtype="ratio"),
     [("compute_ratio", "operating_margin", "FY25"), ("compute_ratio", "operating_margin", "FY26")]),
])
def test_named_ratio_replaces_the_plan(catalog, question, plan_reply, expected):
    plan = route_q(catalog, question, plan_reply)
    assert shape(plan) == expected
    assert any("names" in p and expected[0][1] in p for p in plan.problems)


def test_named_ratio_keeps_the_basis(catalog):
    plan = route_q(catalog, "Standalone effective tax rate for FY26?",
                   reply(fact("tax_expense", "FY26", "standalone"), fact("profit_after_tax", "FY26", "standalone")))
    assert [(c.args["ratio_id"], c.args["basis"]) for c in plan.calls] == [("effective_tax_rate", "standalone")]


@pytest.mark.parametrize("question,plan_reply", [
    # the model already calls the named ratio
    ("Give me the effective tax rate TCS paid for FY25.", reply(ratio("effective_tax_rate", "FY25"), qtype="ratio")),
    # two ratios named: code does not choose
    ("Compare TCS's net margin and operating margin for FY26.", reply(ratio("return_on_equity"), qtype="ratio")),
    # a ratio and a metric named: the plan may need both
    ("Show TCS's tax expense and its effective tax rate for FY26.",
     reply(fact("tax_expense"), fact("profit_before_tax"))),
    # a search in the plan, or a mixed / why question: left to the model
    ("Give me the effective tax rate TCS paid for FY25.",
     reply(fact("tax_expense", "FY25"), search("tax rate"), qtype="mixed")),
    ("Why did the effective tax rate move in FY26?", reply(fact("tax_expense"), fact("profit_before_tax"), qtype="mixed")),
    # no ratio named
    ("How much total tax expense did TCS record in FY26?", reply(fact("tax_expense"))),
])
def test_named_ratio_rule_leaves_other_plans_alone(catalog, question, plan_reply):
    plan = route_q(catalog, question, plan_reply)
    assert shape(plan)[:len(plan_reply["calls"])] == [
        (c["tool"], c.get("metric_id") or c.get("ratio_id"), c.get("period")) for c in plan_reply["calls"]]
    assert not any("compute_ratio" in p or "the question names" in p for p in plan.problems)


# ---------- 2. ratios that span years: one call, for the named period ----------

def test_catalog_knows_which_ratios_span_years(full_catalog):
    assert full_catalog.ratio_spans["revenue_cagr_3y"] == 3
    assert full_catalog.ratio_spans["revenue_growth_yoy"] == 1
    assert "net_margin" not in full_catalog.ratio_spans


@pytest.mark.parametrize("question,plan_reply,expected", [
    # the C11 pattern: a CAGR asked "from A to B", called for every year in the range
    ("What compound annual growth rate did TCS's revenue achieve between FY23 and FY26?",
     reply(ratio("revenue_cagr_3y", "FY23"), ratio("revenue_cagr_3y", "FY24"), ratio("revenue_cagr_3y", "FY25"),
           qtype="ratio"),
     [("compute_ratio", "revenue_cagr_3y", "FY26")]),
    # one period named, the model also asked for the year before
    ("By how much did TCS's revenue grow year on year in FY25?",
     reply(ratio("revenue_growth_yoy", "FY24"), ratio("revenue_growth_yoy", "FY25"), qtype="ratio"),
     [("compute_ratio", "revenue_growth_yoy", "FY25")]),
    ("Three-year revenue CAGR ending FY26, please.",
     reply(ratio("revenue_cagr_3y", "FY24"), ratio("revenue_cagr_3y", "FY25"), ratio("revenue_cagr_3y", "FY26"),
           qtype="numeric"),
     [("compute_ratio", "revenue_cagr_3y", "FY26")]),
])
def test_span_ratio_is_called_once_for_the_named_period(full_catalog, question, plan_reply, expected):
    plan = route_q(full_catalog, question, plan_reply)
    assert shape(plan) == expected
    assert any("spans" in p for p in plan.problems)


@pytest.mark.parametrize("question,plan_reply", [
    # a trend over a range longer than the ratio's own span: one value per year is the point
    ("How did TCS's year-on-year revenue growth move between FY24 and FY26?",
     reply(ratio("revenue_growth_yoy", "FY24"), ratio("revenue_growth_yoy", "FY25"),
           ratio("revenue_growth_yoy", "FY26"), qtype="ratio")),
    # two adjacent years and a one-year ratio: may be a comparison of two growth rates, so left alone
    ("Set TCS's FY25 revenue growth beside its FY26 revenue growth.",
     reply(ratio("revenue_growth_yoy", "FY25"), ratio("revenue_growth_yoy", "FY26"), qtype="ratio")),
    # a ratio that does not span years
    ("What net margin did TCS report in FY26?", reply(ratio("net_margin", "FY25"), ratio("net_margin", "FY26"),
                                                      qtype="ratio")),
    # a "why" question may compare years on purpose
    ("Why did TCS's revenue growth slow in FY26?",
     reply(ratio("revenue_growth_yoy", "FY25"), ratio("revenue_growth_yoy", "FY26"), search("growth"), qtype="mixed")),
])
def test_span_rule_leaves_other_plans_alone(full_catalog, question, plan_reply):
    plan = route_q(full_catalog, question, plan_reply)
    want = [(c["tool"], c.get("metric_id") or c.get("ratio_id"), c.get("period")) for c in plan_reply["calls"]]
    assert shape(plan) == want
    assert not any("spans" in p for p in plan.problems)


# ---------- 3. a group of metrics named by its family name ----------

def test_metric_groups_come_from_display_names(full_catalog):
    groups = metric_groups(full_catalog)
    assert groups == {"exceptional item": {"exceptional_restructuring_expenses", "exceptional_labour_codes_impact",
                                           "exceptional_legal_claim_provision",
                                           "exceptional_legal_claim_settlement"}}


@pytest.mark.parametrize("question,plan_reply,facts", [
    # the E01 pattern: a search only
    ("Did TCS book any exceptional item in FY24?", reply(search("exceptional item FY24"), qtype="qualitative"),
     [("exceptional_legal_claim_settlement", "FY24")]),
    ("Which exceptional items hit TCS's FY26 profit?", reply(search("exceptional items"), qtype="qualitative"),
     [("exceptional_restructuring_expenses", "FY26"), ("exceptional_labour_codes_impact", "FY26"),
      ("exceptional_legal_claim_provision", "FY26")]),
])
def test_group_question_fetches_the_stored_facts_and_keeps_the_search(full_catalog, question, plan_reply, facts):
    plan = route_q(full_catalog, question, plan_reply)
    got = [(c.args["metric_id"], c.args["period"]) for c in plan.calls if c.tool == "get_financial_fact"]
    assert sorted(got) == sorted(facts)                     # lines that are not zero in that year
    assert any(c.tool == "search_documents" for c in plan.calls)
    assert len(plan.calls) <= 4
    assert any("exceptional item" in p for p in plan.problems)


def test_group_year_with_only_zero_lines_fetches_those_lines(full_catalog):
    # FY25: every exceptional line is printed as "-" (stored 0). The facts say so; nothing is invented.
    plan = route_q(full_catalog, "Were there any exceptional items in TCS's FY25 accounts?",
                   reply(search("exceptional items FY25"), qtype="qualitative"))
    got = {c.args["metric_id"] for c in plan.calls if c.tool == "get_financial_fact"}
    assert got and got <= metric_groups(full_catalog)["exceptional item"]
    assert len(plan.calls) <= 4


@pytest.mark.parametrize("question,plan_reply", [
    # "exceptional items" as a qualifier of another line, not the subject
    ("What was TCS's profit before exceptional items in FY26?",
     reply(fact("profit_before_exceptional_items_and_tax"))),
    ("Profit before exceptional items and tax for FY24?", reply(fact("profit_before_exceptional_items_and_tax", "FY24"))),
    # one member named by its own name: the named-metric rule's business, not the group's
    ("How large were the re-structuring expenses in FY26?", reply(fact("exceptional_restructuring_expenses"))),
    # no period named: code does not pick a year
    ("What exceptional items has TCS disclosed?", reply(search("exceptional items"), qtype="qualitative")),
])
def test_group_rule_leaves_other_questions_alone(full_catalog, question, plan_reply):
    plan = route_q(full_catalog, question, plan_reply)
    want = [(c["tool"], c.get("metric_id") or c.get("ratio_id"), c.get("period")) for c in plan_reply["calls"]]
    assert shape(plan) == want
    assert not any("exceptional item" in p and "group" in p for p in plan.problems)


def test_group_facts_already_in_the_plan_are_not_repeated(full_catalog):
    plan = route_q(full_catalog, "Did TCS book any exceptional item in FY24?",
                   reply(fact("exceptional_legal_claim_settlement", "FY24")))
    assert shape(plan) == [("get_financial_fact", "exceptional_legal_claim_settlement", "FY24")]


# ---------- 4. H routing: every fiscal year in the named range ----------

def h(question):
    return q(id="SYN-H9", category="H", question=question, gold_value=None, gold_unit="PERCENT",
             gold_period=None, tolerance=None, gold_sources=[{"source_id": 1, "page": 167}])


NM = {"tool": "compute_ratio", "ratio_id": "net_margin"}


@pytest.mark.parametrize("question,periods,expected", [
    ("How did TCS's net margin evolve from FY23 to FY26?", ["FY23", "FY26"], (True, False)),       # ends only
    ("How did TCS's net margin evolve from FY23 to FY26?", ["FY23", "FY24", "FY26"], (True, False)),
    ("How did TCS's net margin evolve from FY23 to FY26?", ["FY23", "FY24", "FY25", "FY26"], (True, True)),
    ("Trace net margin across fiscal 2024 to fiscal 2026.", ["FY24", "FY25", "FY26"], (True, True)),
    # no range named: two or more periods, as before
    ("Has TCS's net margin been rising or falling lately?", ["FY25", "FY26"], (True, True)),
    ("Has TCS's net margin been rising or falling lately?", ["FY26"], (True, False)),
])
def test_h_period_right_needs_every_year_in_the_named_range(env, question, periods, expected):
    # The question given to the system names no period, so the router adds nothing; the plan's
    # periods are exactly the scripted ones. Scoring reads the eval question's text.
    a = answer_question("How has net margin moved?", env,
                        llm([{**NM, "period": p} for p in periods], "Net margin moved."), cfg=CFG)
    assert [c.args["period"] for c in a.route.calls] == periods
    assert routing_check(h(question), a, ECFG) == expected
