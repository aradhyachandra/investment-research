"""U1: friendlier fixed answers for meta questions and more accurate refusal reasons.

1. Help / about questions ("what can you do", "who made you") get a fixed answer from
   config/agent.yaml (`about`), decided by code before the router. Not a refusal.
2. Questions about the market price (share price, market capitalisation, P/E) for a past or current
   period get their own fixed reason, no_market_data. Price forecasts stay price_prediction.
3. A router "investment_advice" refusal of a plain factual question about dividends, shares or EPS
   is overridden by code (the filings are searched); the pattern pre-check never refused these.
   Advice questions still refuse.

All phrasings here are new (written for U1), not taken from the question files.
"""
import json
import re
import sqlite3

import pytest

from erp.agent.guardrails import about_intent, other_company_names, precheck
from erp.agent.llm import load_agent_config
from erp.agent.loop import REFUSAL_TEXT, answer_question
from erp.agent.router import advice_refusal_is_factual, build_catalog, route
from erp.config import REPO
from erp.ui import view_model as vm
from fakes import ScriptedLLM
from test_agent_tools import DISPLAY
from test_answer_loop import env  # noqa: F401  (fixture)
from test_dcf_run import TOY_YAML
from test_ui import FOOTER, UI_CFG

CFG = load_agent_config()
OTHER = other_company_names("TCS")
REAL_DB = REPO / "data" / "db" / "sample.sqlite"


def check(q):
    return precheck(q, CFG["guardrails"], OTHER)


def no_llm(messages, schema):
    raise AssertionError("the LLM must not be called")


# ---------- 1. help / about ----------

@pytest.mark.parametrize("question", [
    "what can you tell me?",
    "What can you do?",
    "help",
    "Help!",
    "  HELP  ",
    "Who are you?",
    "who made you",
    "Who created you?",
    "Who built this tool?",
    "How do you work?",
    "What can you tell me about yourself?",
    "What can you tell me about TCS?",
    "What questions can I ask?",
    "Can you help me?",
    "Tell me about this assistant.",
])
def test_about_questions_are_recognised(question):
    assert about_intent(question, CFG["about"]["patterns"])


@pytest.mark.parametrize("question", [
    "What can you tell me about TCS's dividends in FY25?",
    "Can you help me find TCS's FY26 revenue?",
    "How does TCS work with its largest clients?",
    "Who are TCS's statutory auditors?",
    "Who made the DCF assumptions?",
    "What was TCS's revenue in FY26? Help me understand it.",
])
def test_ordinary_questions_are_not_about_questions(question):
    assert not about_intent(question, CFG["about"]["patterns"])


def test_about_question_gets_the_fixed_answer_without_any_llm_call(env):  # noqa: F811
    llm = ScriptedLLM(no_llm)
    a = answer_question("What can you tell me?", env, llm)
    assert not a.refused and a.refusal_reason is None
    assert a.composed_by == "about"
    assert a.answer_text == CFG["about"]["text"].strip()
    assert llm.calls == [] and a.tool_results == [] and a.numbers_used == [] and a.citations == []


def test_about_text_says_what_was_asked_for():
    text = CFG["about"]["text"]
    for needle in ["TCS", "Aradhya Chandra", "portfolio project", "178", "FY23", "FY26", "page",
                   "investment advice", "price targets", "market prices", "other companies", "quarterly"]:
        assert needle.lower() in text.lower(), needle
    examples = [line for line in text.splitlines() if line.lstrip().startswith("- ")]
    assert len(examples) == 5
    for phrase in CFG["banned_phrases"]:
        assert not re.search(rf"\b{re.escape(phrase)}\b", text, re.I), phrase


def test_about_examples_pass_the_precheck_and_are_not_about_questions():
    examples = [line.lstrip()[2:] for line in CFG["about"]["text"].splitlines() if line.lstrip().startswith("- ")]
    for q in examples:
        assert check(q) is None, q
        assert not about_intent(q, CFG["about"]["patterns"]), q


@pytest.mark.skipif(not REAL_DB.exists(), reason="the real sample database is not present")
def test_about_text_counts_match_the_real_database():
    conn = sqlite3.connect(REAL_DB)
    n_facts = conn.execute("SELECT count(*) FROM fact").fetchone()[0]
    n_verified = conn.execute("SELECT count(*) FROM fact WHERE verified_by IS NOT NULL").fetchone()[0]
    years = [r[0] for r in conn.execute(
        "SELECT DISTINCT p.label FROM fact JOIN period p USING (period_id) ORDER BY p.label")]
    reports = [r[0] for r in conn.execute(
        "SELECT DISTINCT s.period_covered FROM fact f JOIN source_document s USING (source_id) "
        "WHERE s.doc_type = 'annual_report' ORDER BY 1")]
    text = CFG["about"]["text"]
    assert n_facts == n_verified
    assert f"{n_facts} verified facts" in text
    assert f"{years[0]} to {years[-1]}" in text
    assert all(r in text for r in reports)


def test_about_answer_shows_as_an_answer_with_its_own_badge(env):  # noqa: F811
    a = answer_question("help", env, ScriptedLLM(no_llm))
    view = vm.build_view(a, display=DISPLAY, ui_cfg=UI_CFG, assumptions_file=TOY_YAML, dcf_footer=FOOTER)
    assert vm.answer_badge(view) == ("About this assistant", "blue")
    assert not view.refused and not view.verification.fallback_used
    assert "fixed" in view.verification.status


def test_a_help_me_advice_question_is_not_an_about_question(env):  # noqa: F811
    q = "Help me decide whether to buy TCS shares"
    assert not about_intent(q, CFG["about"]["patterns"])
    llm = ScriptedLLM(lambda m, s: json.dumps({"question_type": "out_of_scope", "refusal_reason": "investment_advice",
                                               "calls": []}))
    a = answer_question(q, env, llm)
    assert a.refused and a.refusal_reason == "investment_advice" and len(llm.calls) == 1


# ---------- 2. no market price data ----------

@pytest.mark.parametrize("question", [
    "What was TCS's share price at the end of FY25?",
    "What is the current stock price of TCS?",
    "What is TCS's market capitalisation?",
    "What was TCS's market cap in FY26?",
    "What was TCS's market value in FY24?",
    "What is TCS's P/E ratio?",
    "What is TCS's price-to-earnings multiple today?",
    "What is the dividend yield on TCS shares?",
    "At what price is TCS trading?",
    "What was the closing price of TCS on 31 March 2026?",
])
def test_market_price_questions_get_their_own_reason(question):
    assert check(question) == "no_market_data"


@pytest.mark.parametrize("question", [
    "Will the share price go up?",
    "Will TCS's stock price rise next year?",
    "What will the share price be in March?",
    "Forecast TCS's stock price.",
])
def test_price_forecasts_keep_the_price_prediction_reason(question):
    assert check(question) == "price_prediction"


@pytest.mark.parametrize("question", [
    "At what price did TCS buy back shares in FY24?",
    "What was the buyback price per share?",
    "What does the annual report say about the share price or market capitalisation?",
    "What is the face value of one TCS share?",
    "What was the fair value of TCS's investments in FY26?",
])
def test_filing_questions_that_mention_prices_are_not_market_data_refusals(question):
    assert check(question) is None


def test_another_companys_share_price_is_an_other_company_question():
    assert check("What is Infosys's share price?") == "other_company"


def test_market_price_refusal_text_and_no_llm_call(env):  # noqa: F811
    llm = ScriptedLLM(no_llm)
    a = answer_question("What is TCS's share price today?", env, llm)
    assert a.refused and a.refusal_reason == "no_market_data" and llm.calls == []
    assert a.answer_text.startswith("I don't have market price data; this tool works from TCS's annual reports")


def test_share_price_versus_dcf_is_still_advice():
    assert check("Is the share price below the DCF value per share?") == "investment_advice"


# ---------- 3. factual dividend / share / EPS questions are not advice ----------

FACTUAL = [
    "How much dividend per share did TCS pay for FY24?",
    "What was the final dividend TCS recommended for FY26?",
    "List the dividends TCS declared in FY25.",
    "How many equity shares did TCS have at the end of FY25?",
    "What was TCS's basic EPS in FY25?",
    "When did TCS pay its special dividend in FY25?",
    "Did TCS declare an interim dividend in FY26?",
    "What can you tell me about TCS's dividends in FY25?",
    "Which dividend did the Board recommend for FY26?",
]


@pytest.mark.parametrize("question", FACTUAL)
def test_factual_dividend_share_eps_questions_pass_the_precheck(question):
    assert check(question) is None
    assert advice_refusal_is_factual(question)


@pytest.mark.parametrize("question", [
    "Should I buy TCS for the dividend?",
    "Should I hold TCS shares for dividends?",
    "Is TCS a good investment for dividend income?",
    "Is TCS undervalued given its EPS?",
    "Is TCS stock worth buying for the dividend?",
    "Would you buy TCS shares at this EPS?",
])
def test_advice_about_dividends_and_eps_is_still_refused_by_the_precheck(question):
    assert check(question) == "investment_advice"


@pytest.mark.parametrize("question", [
    "What should I do with my TCS shares?",
    "What do you think of TCS's dividend?",
    "Is TCS's dividend attractive?",
    "What is the best way to earn TCS dividends?",
    "Is TCS a safe dividend stock?",
    "What do you recommend I do with TCS shares?",
])
def test_personal_or_judging_wording_keeps_the_router_refusal(question):
    assert not advice_refusal_is_factual(question)


@pytest.fixture
def catalog(loaded):
    return build_catalog(loaded, "TCS", dcf_assumptions=TOY_YAML)


def advice_refusal(calls=()):
    text = json.dumps({"question_type": "out_of_scope", "refusal_reason": "investment_advice",
                       "calls": list(calls)})
    return ScriptedLLM(lambda m, s: text)


def test_router_advice_refusal_of_a_dividend_question_becomes_a_search(catalog):
    # As seen live: the model refused and also listed an unrelated fact call.
    llm = advice_refusal([{"tool": "get_financial_fact", "metric_id": "total_equity", "period": "FY25",
                           "basis": "consolidated"}])
    plan = route("How much dividend per share did TCS pay for FY25?", catalog, llm, max_calls=4)
    assert not plan.refuse and plan.refusal_reason == "none"
    assert [c.tool for c in plan.calls] == ["search_documents"]
    assert plan.calls[0].args["fiscal_year"] == 2025
    assert any("investment_advice" in p and "factual" in p for p in plan.problems)


def test_router_advice_refusal_of_a_named_metric_question_also_looks_up_the_fact(catalog):
    plan = route("What was TCS's basic EPS in FY25?", catalog, advice_refusal(), max_calls=4)
    assert not plan.refuse
    assert [(c.tool, c.args.get("metric_id"), c.args.get("period")) for c in plan.calls] == [
        ("search_documents", None, None), ("get_financial_fact", "eps_basic", "FY25")]


@pytest.mark.parametrize("question", [
    "What should I do with my TCS shares?",
    "Is TCS's dividend attractive?",
])
def test_router_advice_refusal_stands_for_advice_wording(catalog, question):
    plan = route(question, catalog, advice_refusal(), max_calls=4)
    assert plan.refuse and plan.refusal_reason == "investment_advice"


def test_other_router_refusal_reasons_are_not_overridden(catalog):
    llm = ScriptedLLM(lambda m, s: json.dumps({"question_type": "out_of_scope", "refusal_reason": "other_company",
                                                "calls": []}))
    plan = route("How much dividend per share did TCS pay for FY25?", catalog, llm, max_calls=4)
    assert plan.refuse and plan.refusal_reason == "other_company"


def test_dividend_question_is_answered_end_to_end(env):  # noqa: F811
    def reply(messages, schema):
        if "question_type" in schema["properties"]:
            return json.dumps({"question_type": "out_of_scope", "refusal_reason": "investment_advice", "calls": []})
        return json.dumps({"answer_text": "", "used_number_ids": [], "cited_evidence_ids": []})
    a = answer_question("What total dividend per share did TCS declare in FY25?", env, ScriptedLLM(reply))
    assert not a.refused
    assert [r.tool for r in a.tool_results] == ["search_documents"]


def test_every_precheck_reason_has_a_fixed_text():
    for reason in CFG["guardrails"]:
        assert reason in REFUSAL_TEXT
