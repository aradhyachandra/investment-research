"""M6: refusal handling. A deterministic pre-check (config patterns, no LLM) refuses advice,
price-prediction and other-company questions before the router runs; the router's own refusal
stays as a second line. Refusal texts are fixed in code.
"""
import json
import re

import pytest

from erp.agent.guardrails import latest_period, other_company_names, precheck
from erp.agent.llm import load_agent_config
from erp.agent.loop import REFUSAL_TEXT, answer_question
from fakes import ScriptedLLM
from test_answer_loop import env  # noqa: F401  (fixture)
from test_m5_acceptance import load_questions

CFG = load_agent_config()
OTHER = other_company_names("TCS")


def check(q):
    return precheck(q, CFG["guardrails"], OTHER)


@pytest.mark.parametrize("question,reason", [
    # the provisional dev guardrail questions (category G)
    ("Should I buy TCS shares now?", "investment_advice"),
    ("Where will TCS's share price be a year from now?", "price_prediction"),
    ("Compare TCS's FY26 revenue with Infosys's FY26 revenue.", "other_company"),
    # tricky phrasings
    ("Is TCS undervalued?", "investment_advice"),
    ("is tcs overvalued at these levels", "investment_advice"),
    ("Does the DCF show TCS is undervalued?", "investment_advice"),
    ("Is TCS a buy?", "investment_advice"),
    ("Is TCS a good investment?", "investment_advice"),
    ("Is now a good time to invest in TCS?", "investment_advice"),
    ("Is TCS stock cheap right now?", "investment_advice"),
    ("What is your target price for TCS?", "investment_advice"),
    ("Is the share price below the DCF value per share?", "investment_advice"),
    ("Should I sell or hold my TCS shares?", "investment_advice"),
    ("Would you buy TCS at today's price?", "investment_advice"),
    ("Will it hit 5000?", "price_prediction"),
    ("will TCS hit 5000 by March?", "price_prediction"),
    ("Will the stock go up after results?", "price_prediction"),
    ("Predict TCS's share price for next year.", "price_prediction"),
    ("TCS vs Infosys margins", "other_company"),
    ("How does TCS's net margin compare with Wipro's?", "other_company"),
    ("Is HCLTech growing faster than TCS?", "other_company"),
])
def test_guardrail_questions_are_refused(question, reason):
    assert check(question) == reason


@pytest.mark.parametrize("question", [
    "What does the DCF imply?",
    "What does the base-case DCF imply per share?",
    "What is the DCF value per share in the bear case?",
    "How sensitive is the DCF value per share to WACC and terminal growth?",
    "What is TCS's practice for returning surplus cash to shareholders through dividends and buybacks?",
    "Did TCS buy back shares in FY26?",
    "How much did TCS spend on share buy-backs?",
    "Does any single customer account for 10% or more of TCS's revenue?",
    "What was TCS's net margin in FY26?",
    "Which risks does TCS hold insurance against?",
    "What does the annual report say about the share price or market capitalisation?",
    "How does TCS manage the risk of cyber attacks?",
    "How did TCS's net margin change from FY25 to FY26?",
    "Can you tell me how much TCS spent to buy back shares?",
    "Could you summarise how TCS plans to invest in AI?",
    "Should I read the risk section or the MD&A first to understand client concentration?",
])
def test_legitimate_questions_that_sound_like_advice_are_not_refused(question):
    assert check(question) is None


def test_precheck_refuses_before_any_llm_call(env):  # noqa: F811
    # A router that would happily answer: the pre-check must stop the question first.
    llm = ScriptedLLM(lambda m, s: json.dumps({"question_type": "numeric", "refusal_reason": "none", "calls": [
        {"tool": "get_financial_fact", "metric_id": "revenue_from_operations", "period": "FY26"}]}))
    a = answer_question("Is TCS undervalued?", env, llm)
    assert a.refused and a.refusal_reason == "investment_advice"
    assert a.answer_text == REFUSAL_TEXT["investment_advice"]
    assert llm.calls == [] and a.tool_results == [] and a.numbers_used == []
    assert a.route.refuse and a.route.model is None and "pre-check" in a.route.problems[0]


@pytest.mark.parametrize("q", [q for q in load_questions() if q["category"] == "G"], ids=lambda q: q["id"])
def test_dev_guardrail_questions_get_the_fixed_refusal_text(env, q):  # noqa: F811
    llm = ScriptedLLM(lambda m, s: json.dumps({"question_type": "numeric", "refusal_reason": "none", "calls": []}))
    a = answer_question(q["question"], env, llm)
    reason = q["expected_route"]["refusal_reason"]
    assert a.refused and a.refusal_reason == reason and a.answer_text == REFUSAL_TEXT[reason]


def test_router_refusal_still_works_when_the_precheck_passes(env):  # noqa: F811
    llm = ScriptedLLM(lambda m, s: json.dumps({"question_type": "out_of_scope",
                                                "refusal_reason": "price_prediction", "calls": []}))
    a = answer_question("What happens to TCS next year?", env, llm)
    assert a.refused and a.answer_text == REFUSAL_TEXT["price_prediction"] and len(llm.calls) == 1


def test_guard_patterns_are_valid_regexes_and_texts_have_no_advice_words():
    for reason, patterns in CFG["guardrails"].items():
        assert reason in REFUSAL_TEXT
        for p in patterns:
            re.compile(p)
    for text in REFUSAL_TEXT.values():
        for phrase in CFG["banned_phrases"]:
            assert not re.search(rf"\b{re.escape(phrase)}\b", text, re.I)


# ---------- periods after the latest data are forecasts ----------

@pytest.mark.parametrize("question,expected", [
    ("What will TCS's revenue be in FY28?", "outside_data"),
    ("What is the expected net margin for fiscal 2028?", "outside_data"),
    ("Revenue in Q3 FY27?", "outside_data"),
    ("What was revenue in FY26?", None),
    ("How did net margin change from FY25 to FY26?", None),
    ("What does the Q1 FY27 fact sheet say about deal wins?", None),
])
def test_periods_after_the_latest_data_are_refused(question, expected):
    assert precheck(question, CFG["guardrails"], OTHER, latest="Q1 FY27") == expected


def test_latest_period_comes_from_facts_and_documents(loaded):
    # Sample facts are FY25/FY26; the Q1 FY27 fact sheet is a registered document.
    assert latest_period(loaded, "TCS") == "Q1 FY27"
