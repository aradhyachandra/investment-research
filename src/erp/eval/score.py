"""Scoring one answer against one question (plan 6.2). Deterministic, no LLM.

  numeric accuracy   a numeric claim matches gold value, unit and period:
                     tolerance 0 -> the value written equals the gold value exactly (the gold is
                     at the printed precision, so a rounder figure fails); tolerance t > 0 ->
                     |claim - gold| / |gold| <= t. The unit written must be the gold unit (no
                     unit written does not match). If gold_period is a period label, it must be
                     in the claim's sentence, or, if that sentence names no period, somewhere in
                     the answer. A non-label gold_period (DCF valuation date) is not checked.
  citation (numeric) a numeric claim cites a (source_id, page) in gold_sources (a chunk
                     spanning pages counts if the gold page is in its range). Scored over every
                     numeric claim in answers to questions that have gold_sources, and also over
                     only the claims that match the gold value.
  behaviour          answered / partial / refuse / not_available / error (config/eval.yaml).
  routing            coarse: the set of tools used vs the category's expected set (config). Trend
                     questions (H): fact/ratio tools, covering two or more periods.
  unsupported        numeric claims with no evidence (claims.py `supported`).
  verifier           rejected = the verifier failed the composed text and the template shipped;
                     would_reject = the verifier failed it (recorded also when it is switched off).
"""
import re
from decimal import Decimal

import yaml
from pydantic import BaseModel

from erp.agent.answer_schema import Answer
from erp.agent.llm import load_agent_config
from erp.agent.verifier import period_key, periods_in
from erp.config import REPO
from erp.eval.claims import NumericClaim, extract_claims, numeric_claims_in_text
from erp.eval.questions import EvalQuestion

EVAL_CONFIG = REPO / "config" / "eval.yaml"
REL_EPS = 1e-12      # floating-point slack on the relative-tolerance comparison only


def load_eval_config(path=EVAL_CONFIG) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def matches_gold(claim: NumericClaim, q: EvalQuestion, all_periods: list[str]) -> bool:
    if q.gold_value is None or claim.unit != q.gold_unit:
        return False
    value, gold = Decimal(claim.value), Decimal(str(q.gold_value))
    if not q.tolerance:
        if value != gold:
            return False
    elif gold == 0 or float(abs(value - gold) / abs(gold)) > q.tolerance + REL_EPS:
        return False
    if q.gold_period and period_key(q.gold_period):
        return q.gold_period in (claim.periods or all_periods)
    return True


def cites_gold(claim: NumericClaim, q: EvalQuestion) -> bool:
    return any(c.source_id == g.source_id and c.page <= g.page <= c.page_end for c in claim.cited
               for g in q.gold_sources)


def classify_behavior(answer: Answer, ecfg: dict | None = None) -> str:
    b = (ecfg or load_eval_config())["behavior"]
    if answer.refused:
        if answer.refusal_reason == "harness_error":
            return "error"
        return "refuse" if answer.refusal_reason in b["refuse_reasons"] else "not_available"
    text = answer.answer_text.lower()
    declines = any(re.search(rf"\b{re.escape(p)}\b", text) for p in b["decline_phrases"])
    if not declines:
        return "answered"
    return "partial" if numeric_claims_in_text(answer.answer_text) else "not_available"


def routing_check(q: EvalQuestion, answer: Answer, ecfg: dict | None = None) -> tuple[bool, bool] | None:
    """(tools right, tools and period right), or None when this question/system is not scored."""
    rules = (ecfg or load_eval_config())["routing"]
    plan = answer.route
    if plan is None:                                   # naive RAG has no router
        return None
    if q.expected_behavior == "refuse":
        return (plan.refuse, plan.refuse)
    if q.expected_behavior == "not_available" or (q.category == "B" and q.gold_value is None):
        return None
    trend = (rules.get("trend") or {}).get(q.category)
    expected = rules["expected_tools"].get(q.category)
    if expected is None and trend is None:
        return None
    if plan.refuse or plan.question_type == "routing_failed":
        return (False, False)
    if trend is not None:
        # Several numbers across years (category H): data tools from the list (a search may be added),
        # and "period right" = those calls cover two or more periods.
        tools = {c.tool for c in plan.calls}
        tools_ok = bool(tools & set(trend)) and tools <= {*trend, "search_documents"}
        periods = {c.args.get("period") for c in plan.calls if c.tool in trend}
        return (tools_ok, tools_ok and len(periods) >= 2)
    tools_ok = {c.tool for c in plan.calls} == set(expected)
    period_ok = tools_ok
    if tools_ok and q.category in rules["check_period"] and q.gold_period and period_key(q.gold_period):
        period_ok = all(c.args.get("period") == q.gold_period for c in plan.calls
                        if c.tool in ("get_financial_fact", "compute_ratio"))
    return (tools_ok, period_ok)


class QuestionScore(BaseModel):
    id: str
    category: str
    expected_behavior: str
    behavior: str
    behavior_ok: bool
    has_gold_value: bool
    numeric_correct: bool
    numeric_claims: int
    unsupported_claims: int
    numeric_claims_in_scope: int        # numeric claims in an answer to a question with gold_sources
    gold_citing_claims: int             # ... of which cite a gold (source_id, page)
    gold_claims: int                    # numeric claims matching the gold value/unit/period
    gold_claims_citing: int             # ... of which cite a gold page (when gold_sources exist)
    routing_tools_ok: bool | None
    routing_period_ok: bool | None
    verifier_ran: bool
    verifier_rejected: bool
    verifier_would_reject: bool
    advice_language: list[str]
    composed_by: str
    expected_failure: bool              # a known failure listed in config (no unit-conversion tool)


def score_question(q: EvalQuestion, answer: Answer, ecfg: dict | None = None, cfg: dict | None = None,
                   claims=None) -> QuestionScore:
    ecfg = ecfg or load_eval_config()
    cfg = cfg or load_agent_config()
    numeric, _ = claims if claims is not None else extract_claims(answer, cfg)
    all_periods = periods_in(answer.answer_text)
    gold = [c for c in numeric if matches_gold(c, q, all_periods)]
    in_scope = numeric if q.gold_sources else []
    behavior = classify_behavior(answer, ecfg)
    route = routing_check(q, answer, ecfg)
    v = answer.verification
    banned = [p for p in cfg["banned_phrases"] if re.search(rf"\b{re.escape(p)}\b", answer.answer_text, re.I)]
    return QuestionScore(
        id=q.id, category=q.category, expected_behavior=q.expected_behavior, behavior=behavior,
        behavior_ok=behavior in ecfg["behavior"]["accept"][q.expected_behavior],
        has_gold_value=q.gold_value is not None, numeric_correct=bool(gold),
        numeric_claims=len(numeric), unsupported_claims=sum(not c.supported for c in numeric),
        numeric_claims_in_scope=len(in_scope), gold_citing_claims=sum(cites_gold(c, q) for c in in_scope),
        gold_claims=len(gold) if q.gold_sources else 0,
        gold_claims_citing=sum(cites_gold(c, q) for c in gold) if q.gold_sources else 0,
        routing_tools_ok=None if route is None else route[0], routing_period_ok=None if route is None else route[1],
        verifier_ran=v is not None, verifier_rejected=v is not None and not v.ok and answer.composed_by == "template",
        verifier_would_reject=v is not None and not v.ok, advice_language=banned, composed_by=answer.composed_by,
        expected_failure=q.category == "B" and q.gold_unit in ecfg["expected_failures"]["no_conversion_tool_units"])
