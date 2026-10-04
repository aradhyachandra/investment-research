"""M6 acceptance (plan Section 9): injected bad numbers and bad citations are caught in tests;
guardrail questions (category G) are refused correctly on dev.

Everything runs through answer_question with a scripted LLM, so the checks are end to end:
a composer reply with a bad figure, citation or comparison must never reach the user. The loop
must replace it with the code-written template answer and record the verifier's report.

PROVISIONAL: eval/questions.jsonl (P0.4) does not exist yet, so "dev" means the Claude-written
tests/provisional_dev_questions.jsonl. DCF uses the TOY fixture (not TCS) under the TCS ticker.
"""
import json

import pytest

from erp.agent.llm import load_agent_config
from erp.agent.loop import REFUSAL_TEXT, answer_question, template_answer
from erp.agent.verifier import verify_answer
from fakes import ScriptedLLM
from test_m5_acceptance import env, load_questions  # noqa: F401  (env is a fixture)

CFG = load_agent_config()
FOOTER = " ".join(CFG["dcf_footer"].split())
NET_MARGIN_26 = {"tool": "compute_ratio", "ratio_id": "net_margin", "period": "FY26"}
NET_MARGIN_25 = {"tool": "compute_ratio", "ratio_id": "net_margin", "period": "FY25"}
REVENUE_26 = {"tool": "get_financial_fact", "metric_id": "revenue_from_operations", "period": "FY26"}
DCF_SENS = {"tool": "run_dcf", "scenario": "base", "include_sensitivity": True}


def llm(calls, answer_text, used=None, cited=None):
    """Router returns `calls`; composer returns `answer_text` (a function of the prompt, or a str)."""
    def reply(messages, schema):
        if "question_type" in schema["properties"]:
            return json.dumps({"question_type": "numeric", "refusal_reason": "none", "calls": calls})
        prompt = messages[-1]["content"]
        text = answer_text(prompt) if callable(answer_text) else answer_text
        return json.dumps({"answer_text": text, "used_number_ids": used or [], "cited_evidence_ids": cited or []})
    return ScriptedLLM(reply)


def ids(prompt, prefix):
    import re
    return list(dict.fromkeys(re.findall(rf"\[({prefix}:[^\]#]+)", prompt)))


def assert_rejected(a, bad, check, bad_in_text=True):
    assert not a.refused and a.composed_by == "template", a.answer_text
    assert bad not in a.answer_text                                  # the bad text never ships
    assert a.verification is not None and not a.verification.ok
    assert check in {i.check for i in a.verification.errors}
    assert any("verifier rejected" in w for w in a.warnings)
    assert a.rejected_text and (bad in a.rejected_text or not bad_in_text)   # kept for review, not shown
    tool_ids = {n.number_id for r in a.tool_results for n in r.numbers}
    assert a.numbers_used and {n.number_id for n in a.numbers_used} <= tool_ids
    # the template itself only carries tool figures
    assert verify_answer(a.answer_text.replace(FOOTER, ""), a.tool_results, cfg=CFG).ok


# ---------- injected bad numbers ----------

@pytest.mark.parametrize("bad", [
    "INR 270,021 crore",       # typo
    "INR 267,021 million",     # wrong unit
    "INR 2.67 lakh crore",     # converted by the LLM
    "INR 11,697 crore",        # LLM arithmetic (FY26 - FY25)
])
def test_injected_bad_number_is_replaced_by_the_template(env, bad):
    a = answer_question("Revenue FY26?", env, llm([REVENUE_26], f"Revenue in FY26 was {bad}."))
    assert_rejected(a, bad, "number_unsupported")
    assert "INR 267,021 crore" in a.answer_text


def test_injected_bad_citation_is_replaced_by_the_template(env):
    a = answer_question("Revenue FY26?", env, llm([REVENUE_26], "Revenue in FY26 was INR 267,021 crore [fact:999]."))
    assert_rejected(a, "[fact:999]", "citation_unknown")


def test_injected_citation_to_the_wrong_figure_is_replaced(env):
    # The net margin is cited to an input fact (a revenue or profit figure), which does not contain it.
    a = answer_question("Net margin FY26?", env, llm(
        [NET_MARGIN_26, REVENUE_26], lambda p: f"Revenue in FY26 was INR 267,021 crore [{ids(p, 'calc')[0]}]. "
                                              f"Net margin was 18.43% [{ids(p, 'fact')[0]}]."))
    assert_rejected(a, "Net margin was 18.43% [fact", "citation_mismatch")


def test_unknown_listed_ids_are_rejected(env):
    a = answer_question("Revenue FY26?", env, llm([REVENUE_26], "Revenue in FY26 was INR 267,021 crore.",
                                                  used=["fact:999#value"], cited=["chunk:made-up"]))
    assert_rejected(a, "made-up", "number_id_unknown", bad_in_text=False)
    assert all(c.evidence_id != "chunk:made-up" for c in a.citations)


# ---------- the known live failures ----------

def test_comparison_with_one_year_fetched_is_replaced(env):
    # PDEV-17 (M5 live): router fetched FY26 only; the composer said the margin decreased from FY25.
    # Since 2026-10-04 the router adds a year the question names but the model left out, so the
    # question here names only FY26: the composer's FY25 comparison is still unsupported.
    text = "Net margin was 18.43% in FY26 and it decreased from FY25 to FY26."
    a = answer_question("How did net margin change in FY26?", env, llm([NET_MARGIN_26], text))
    assert_rejected(a, "decreased", "comparison_unsupported")


def test_wrong_direction_is_replaced(env):
    text = "Net margin increased from 19.02% in FY25 to 18.43% in FY26."
    a = answer_question("How did net margin change?", env, llm([NET_MARGIN_26, NET_MARGIN_25], text))
    assert_rejected(a, "increased", "comparison_wrong_direction")


def test_change_to_the_unchanged_base_value_is_replaced(env):
    # PDEV-13 (live, qwen2.5:3b): "if WACC increases to 13.92% and terminal growth decreases to 5.00%"
    # when 5.00% was the base-case terminal growth. Same slip on the TOY grid (base growth 4.00%).
    text = "If WACC increases to 13.00% and terminal growth decreases to 4.00%, the value per share falls."
    a = answer_question("How sensitive is the DCF value?", env, llm([DCF_SENS], text))
    assert_rejected(a, "decreases to 4.00%", "change_contradicts")
    assert a.answer_text.endswith(FOOTER)


def test_grid_value_quoted_for_the_wrong_conditions_is_replaced(env):
    # PDEV-13 (live, M6 run): "Increasing WACC to 13.92% ... decreases the value per share to INR 1,858.48",
    # the grid cell for WACC 13.92% AND growth 6.00%. Same slip on the TOY grid (base growth 4.00%).
    def compose(p):
        import re
        shown = re.search(r"Value per share at WACC 13\.00% and terminal growth 5\.00%: (INR [\d,.]+ per share)", p)[1]
        return f"If WACC increases to 13.00%, the value per share falls to {shown}."
    a = answer_question("How sensitive is the DCF value?", env, llm([DCF_SENS], compose))
    assert_rejected(a, "falls to", "sensitivity_mismatch")


def test_a_correct_comparison_ships_and_numbers_used_match_the_text(env):
    def compose(p):
        c26, c25 = ids(p, "calc")[:2]
        return f"Net margin decreased from 19.02% in FY25 to 18.43% in FY26 [{c25}, {c26}]."
    a = answer_question("How did net margin change?", env, llm([NET_MARGIN_26, NET_MARGIN_25], compose))
    assert a.composed_by == "llm" and a.verification.ok
    # only the two figures the text says, not the four input facts the tools also returned
    assert [n.display for n in a.numbers_used] == ["19.02%", "18.43%"]
    cited = {c.evidence_id for c in a.citations}
    assert all(n.evidence_id in cited for n in a.numbers_used)


def test_interpretive_words_are_recorded_but_do_not_block(env):
    a = answer_question("Revenue FY26?", env, llm(
        [REVENUE_26], lambda p: f"Revenue in FY26 was INR 267,021 crore [{ids(p, 'fact')[0]}]. Demand stayed strong."))
    assert a.composed_by == "llm"
    assert any(i.check == "interpretive_word" and i.severity == "warning" for i in a.verification.issues)
    assert any("interpretive_word" in w for w in a.warnings)


# ---------- the fixed DCF footer ----------

@pytest.mark.parametrize("text", [
    "The base-case value per share is INR 229.32 per share.",
    "The base-case value per share is INR 229.32 per share. Illustrative value; a prediction.",
    f"The base-case value per share is INR 229.32 per share.\n\n{FOOTER}",       # LLM copies the footer
])
def test_every_dcf_answer_ends_with_the_fixed_footer(env, text):
    a = answer_question("Base-case DCF value?", env, llm([{"tool": "run_dcf", "scenario": "base"}], text))
    assert a.composed_by == "llm", a.warnings
    assert a.answer_text.endswith("\n\n" + FOOTER) and a.answer_text.count(FOOTER) == 1
    assert FOOTER == ("Illustrative value implied by the stated assumptions, which were drafted with AI "
                      "assistance; not a prediction or investment advice.")


def test_template_dcf_answer_has_the_footer_and_other_answers_do_not(env):
    a = answer_question("Base-case DCF value?", env, llm([{"tool": "run_dcf", "scenario": "base"}], "not usable: 9,999"))
    assert a.composed_by == "template" and a.answer_text.endswith(FOOTER)
    b = answer_question("Revenue FY26?", env, llm([REVENUE_26], "Revenue in FY26 was INR 267,021 crore."))
    assert FOOTER not in b.answer_text


# ---------- guardrail questions (category G) on dev ----------

G = [q for q in load_questions() if q["category"] == "G"]


@pytest.mark.parametrize("q", G, ids=[q["id"] for q in G])
def test_dev_guardrail_questions_are_refused_with_the_fixed_text(env, q):
    never_refuses = llm([REVENUE_26], "Revenue in FY26 was INR 267,021 crore.")
    a = answer_question(q["question"], env, never_refuses)
    reason = q["expected_route"]["refusal_reason"]
    assert a.refused and a.refusal_reason == reason and a.answer_text == REFUSAL_TEXT[reason]
    assert a.tool_results == [] and a.numbers_used == [] and never_refuses.calls == []


def test_template_answers_on_the_e2e_dev_questions_carry_only_tool_figures(env):
    from test_m5_acceptance import E2E, gold_route_llm
    for q in E2E:
        a = answer_question(q["question"], env, gold_route_llm(q))
        if a.refused:
            continue
        ok = [r for r in a.tool_results if r.ok]
        assert verify_answer(template_answer(ok, []), ok, cfg=CFG).ok, q["id"]
