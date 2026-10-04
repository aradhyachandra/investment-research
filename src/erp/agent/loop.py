"""The agent loop, Router v1 (two-step), the default design (plan 3.3):

  1. route:   the LLM picks tools and arguments from fixed lists (router.py). No tool runs.
  2. tools:   code runs each call (tools.py). Numbers, evidence and passages come from here only.
  3. compose: the LLM writes the answer from the tool output only, and lists which number ids and
              evidence ids it used, chosen from enums of the ids it was given.

Code, not the LLM, decides: refusals (fixed texts; a pattern pre-check runs before the router),
what counts as a number used (the tool numbers the verifier finds in the text), citations
(evidence of those numbers and their inputs, plus cited chunks), and the fallback answer when
the LLM's reply cannot be used or fails the verifier (a template built from the tool results).
Answers that used run_dcf end with a fixed footer line added by code.
No arithmetic happens in the LLM: every figure it sees is already formatted by code.

CLI:  PYTHONPATH=src .venv/bin/python -m erp.agent.loop "What was TCS's revenue in FY26?"
"""
import argparse
import json
import re
import sqlite3
import sys

from erp.agent.answer_schema import Answer
from erp.agent.guardrails import latest_period, other_company_names, precheck
from erp.agent.llm import LLMError, call_llm, load_agent_config
from erp.agent.router import RoutePlan, build_catalog, route
from erp.agent.tools import ToolEnv, ToolResult, run_tool
from erp.agent.verifier import verify_answer
from erp.config import REPO

# Fixed refusal texts, written by code. They describe what the tool can do instead.
_CAN_DO = ("I can report TCS's published figures, ratios computed from them, what a DCF model's stated "
           "assumptions imply, and what the filings say, each with its source.")
REFUSAL_TEXT = {
    "investment_advice": "I can't give personal investment advice or say what anyone should do with "
                         "TCS shares. " + _CAN_DO,
    "price_prediction": "I can't forecast share prices or market movements. " + _CAN_DO,
    "other_company": "This version covers TCS only, so I can't answer about other companies or compare "
                     "TCS with them. " + _CAN_DO,
    "outside_data": "That figure or period is not in the data loaded so far, so I can't answer it "
                    "without guessing. " + _CAN_DO,
    "outside_scope": "That question is outside what this research tool covers. " + _CAN_DO,
    "routing_failed": "I could not work out which data to use for this question. Try naming the figure "
                      "and the fiscal year, for example \"revenue in FY26\".",
}

COMPOSE_RULES = """You write the answer to a question about {company}, using ONLY the tool results given.
Rules:
1. Every number you write must be copied exactly from the NUMBERS list, as shown there. Do not
   calculate, round, convert units, or combine numbers. If a figure is not listed, say it is not available.
2. PASSAGES are for describing what the filings say. Do not take numbers from passages.
3. After each statement, give its id in square brackets, e.g. [fact:12] or [chunk:abc].
4. Say which period a figure is for, and that it is consolidated when the basis says so.
5. Use plain, neutral language. Describe what the data shows; do not judge whether the company is
   a good investment and do not predict prices.
6. If NOTES or NOT AVAILABLE say something the reader needs (e.g. a figure is not yet checked by a
   human, or a lookup failed), mention it briefly.
7. At most 150 words.
Reply with JSON: answer_text, used_number_ids (ids of the numbers you wrote), cited_evidence_ids
(evidence and chunk ids you relied on)."""


# ---------- step 3: compose ----------

def _evidence_sheet(results: list[ToolResult], failures: list[str]) -> str:
    lines = []
    numbers = [n for r in results for n in r.numbers]
    if numbers:
        lines.append("NUMBERS (write exactly as shown):")
        lines += [f"- [{n.number_id}] {n.label}: {n.display}" for n in numbers]
    passages = [(p, e) for r in results for p in r.passages for e in r.evidence if e.evidence_id == p.evidence_id]
    if passages:
        lines.append("\nPASSAGES:")
        for p, e in passages:
            printed = f", printed page {e.page_label}" if e.page_label else ""
            lines.append(f"[{p.evidence_id}] ({e.source_title}, PDF page {e.page}{printed}; section: {p.section})\n"
                         f"{p.text}\n")
    notes = [x for r in results for x in r.notes]
    calcs = [e for r in results for e in r.evidence if e.formula]
    if notes or calcs:
        lines.append("\nNOTES:")
        lines += [f"- {e.evidence_id} = {e.formula}" for e in calcs]
        lines += [f"- {x}" for x in dict.fromkeys(notes)]
    if failures:
        lines.append("\nNOT AVAILABLE:")
        lines += [f"- {f}" for f in failures]
    return "\n".join(lines)


def compose_messages(question: str, company: str, results: list[ToolResult], failures: list[str]) -> list[dict]:
    return [{"role": "system", "content": COMPOSE_RULES.format(company=company)},
            {"role": "user", "content": f"Question: {question}\n\n{_evidence_sheet(results, failures)}"}]


def compose_schema(results: list[ToolResult]) -> dict:
    number_ids = [n.number_id for r in results for n in r.numbers]
    evidence_ids = list(dict.fromkeys(e.evidence_id for r in results for e in r.evidence))
    def id_list(ids):
        # Ollama refuses an empty enum (HTTP 400), so an empty choice is "an empty list" instead.
        return {"type": "array", "items": {"enum": ids}} if ids else {"type": "array", "maxItems": 0}
    return {"type": "object",
            "properties": {"answer_text": {"type": "string"},
                           "used_number_ids": id_list(number_ids),
                           "cited_evidence_ids": id_list(evidence_ids)},
            "required": ["answer_text", "used_number_ids", "cited_evidence_ids"]}


def template_answer(results: list[ToolResult], failures: list[str]) -> str:
    """Code-written answer from the tool results: used when the LLM's text cannot be used."""
    lines = []
    for r in results:
        if r.tool == "explain_period":          # period dates written by code (tools.py)
            lines += [f"{x} [{r.evidence[0].evidence_id}]" for x in r.notes]
        lines += [f"{n.label}: {n.display} [{n.evidence_id}]." for n in r.numbers]
        for p in r.passages[:3]:
            ev = next(e for e in r.evidence if e.evidence_id == p.evidence_id)
            excerpt = " ".join(p.text.split())[:200]
            lines.append(f"From {ev.source_title}, PDF page {ev.page} ({p.section}): \"{excerpt}...\" [{p.evidence_id}]")
    lines += [f"Not available: {f}" for f in failures]
    return "\n".join(lines)


def _banned(text: str, phrases: list[str]) -> list[str]:
    return [p for p in phrases if re.search(rf"\b{re.escape(p)}\b", text, re.I)]


def _cite(results: list[ToolResult], evidence_ids: list[str]) -> list:
    """Evidence for the given ids, plus (recursively) the inputs of any calculation, in order."""
    by_id = {e.evidence_id: e for r in results for e in r.evidence}
    out, seen = [], set()

    def add(eid):
        if eid in seen or eid not in by_id:
            return
        seen.add(eid)
        out.append(by_id[eid])
        for i in by_id[eid].input_evidence_ids:
            add(i)
    for eid in evidence_ids:
        add(eid)
    return out


# ---------- the loop ----------

def _refusal(question, env, plan, reason, text, results=(), limitations=(), model=None) -> Answer:
    return Answer(question=question, ticker=env.ticker, answer_text=text, numbers_used=[], citations=[],
                  refused=True, refusal_reason=reason, route=plan, tool_results=list(results),
                  limitations=list(limitations), composed_by="refusal", model=model)


def _with_dcf_footer(text: str, results: list[ToolResult], cfg: dict) -> str:
    """Fixed last line for any answer that used run_dcf. Added by code after verification, so
    the LLM cannot remove or edit it (an LLM-written copy is taken out to avoid a duplicate)."""
    if not any(r.tool == "run_dcf" and r.ok for r in results):
        return text
    footer = " ".join(cfg["dcf_footer"].split())
    return f"{text.replace(footer, '').rstrip()}\n\n{footer}"


def answer_question(question: str, env: ToolEnv, llm_fn=call_llm, *, cfg: dict | None = None,
                    verify: bool = True) -> Answer:
    """verify=False is only for the eval ablation (M7, verifier off): the verifier still runs and
    its report is recorded, but an answer it would reject is shipped as written."""
    cfg = cfg or load_agent_config()

    # 0. refusal pre-check: fixed patterns and a future-period check, no LLM (guardrails.py)
    reason = precheck(question, cfg["guardrails"], other_company_names(env.ticker),
                      latest_period(env.conn, env.ticker))
    if reason and reason != "outside_data":
        plan = RoutePlan(question_type="out_of_scope", refusal_reason=reason, refuse=True,
                         problems=["refused by the pattern pre-check (guardrails.py); the router was not called"])
        return _refusal(question, env, plan, reason, REFUSAL_TEXT[reason])

    catalog = build_catalog(env.conn, env.ticker, env.dcf_assumptions)

    # 1. route
    plan: RoutePlan = route(question, catalog, llm_fn, max_calls=cfg["router"]["max_tool_calls"])
    if reason == "outside_data" and not (plan.calls and all(c.tool == "explain_period" for c in plan.calls)):
        # A period after the latest data is a forecast, whatever the router chose; only a question
        # about what that period means (explain_period alone, no figures) goes ahead.
        refused = RoutePlan(question_type="out_of_scope", refusal_reason=reason, refuse=True, raw=plan.raw,
                            model=plan.model, problems=["refused by the pre-check (guardrails.py): a period after "
                                                        "the latest data, and the route was not explain_period only"])
        return _refusal(question, env, refused, reason, REFUSAL_TEXT[reason], model=plan.model)
    if plan.question_type == "routing_failed":
        return _refusal(question, env, plan, "routing_failed", REFUSAL_TEXT["routing_failed"],
                        limitations=plan.problems, model=plan.model)
    if plan.refuse:
        return _refusal(question, env, plan, plan.refusal_reason, REFUSAL_TEXT[plan.refusal_reason],
                        model=plan.model)

    # 2. run the tools in code
    results = [run_tool(c, env) for c in plan.calls]
    ok = [r for r in results if r.ok]
    failures = [f"{r.tool}({', '.join(f'{k}={v}' for k, v in r.args.items())}): {r.error}" for r in results if not r.ok]
    limitations = [*plan.problems, *failures, *dict.fromkeys(x for r in ok for x in r.notes)]
    if not ok:
        return _refusal(question, env, plan, "data_not_available",
                        "I could not answer this from the available data.\n" + "\n".join(failures),
                        results, limitations, plan.model)

    # 3. compose from the tool output only
    warnings = []
    all_numbers = {n.number_id: n for r in ok for n in r.numbers}
    chunk_ids = [p.evidence_id for r in ok for p in r.passages]
    # A period explanation backs the whole answer, so its evidence is always cited.
    period_ids = [e.evidence_id for r in ok if r.tool == "explain_period" for e in r.evidence]
    model = plan.model
    try:
        reply = llm_fn(compose_messages(question, catalog.company_name, ok, failures), schema=compose_schema(ok))
        model = reply.model
        data = json.loads(reply.text)
        text = data.get("answer_text", "") if isinstance(data, dict) else ""
    except (LLMError, json.JSONDecodeError) as e:
        data, text = {}, ""
        warnings.append(f"composer reply unusable ({type(e).__name__}: {str(e)[:200]}); template answer used")
    if not isinstance(data, dict):
        data = {}

    def template(report=None):
        return Answer(question=question, ticker=env.ticker,
                      answer_text=_with_dcf_footer(template_answer(ok, failures), ok, cfg),
                      numbers_used=list(all_numbers.values()),
                      citations=_cite(ok, period_ids + [n.evidence_id for n in all_numbers.values()] + chunk_ids),
                      refused=False, route=plan, tool_results=results, limitations=limitations,
                      composed_by="template", model=model, warnings=warnings, verification=report,
                      rejected_text=text or None)

    banned = _banned(text, cfg["banned_phrases"])
    if banned:
        warnings.append(f"composer text contained advice/verdict language {banned}; template answer used")
    if not text.strip() or banned:
        if text.strip() == "" and not warnings:
            warnings.append("composer gave no answer text; template answer used")
        return template()

    # 4. verify the LLM's text against the tool results (verifier.py); any error -> template
    listed = [i for i in data.get("used_number_ids") or [] if isinstance(i, str)]
    cited = [i for i in data.get("cited_evidence_ids") or [] if isinstance(i, str)]
    report = verify_answer(text, ok, cfg=cfg, listed_number_ids=listed, cited_ids=cited)
    warnings += [f"verifier {i.severity} ({i.check}): {i.message}" for i in report.issues]
    if not report.ok and verify:
        warnings.append(f"verifier rejected the composed text ({len(report.errors)} error(s)); template answer used")
        return template(report)
    if not verify:
        warnings.append(f"verifier off (eval ablation): report recorded, not enforced "
                        f"({len(report.errors)} error(s))")

    numbers_used = report.numbers_in_text
    known_evidence = {e.evidence_id for r in ok for e in r.evidence}
    cited_chunks = [i for i in cited if i in chunk_ids]
    if chunk_ids and not cited_chunks:
        warnings.append("composer cited no passage; all passages it was given are attached")
        cited_chunks = chunk_ids
    citations = _cite(ok, period_ids + [n.evidence_id for n in numbers_used]
                      + [i for i in cited if i in known_evidence and i not in chunk_ids] + cited_chunks)
    return Answer(question=question, ticker=env.ticker, answer_text=_with_dcf_footer(text, ok, cfg),
                  numbers_used=numbers_used, citations=citations, refused=False, route=plan, tool_results=results,
                  limitations=limitations, composed_by="llm", model=model, warnings=warnings, verification=report)


# ---------- CLI ----------

def open_env(db_path, dcf_assumptions=None, cfg=None) -> ToolEnv:
    cfg = cfg or load_agent_config()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return ToolEnv(conn=conn, ticker=cfg["default_ticker"], display=cfg["display"],
                   search_top_k=cfg["tools"]["search_top_k"], passage_chars=cfg["tools"]["passage_chars"],
                   dcf_assumptions=REPO / (dcf_assumptions or cfg["tools"]["dcf_assumptions"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Answer one question (prints the structured Answer as JSON).")
    parser.add_argument("question")
    parser.add_argument("--db", default=str(REPO / "data" / "db" / "sample.sqlite"))
    parser.add_argument("--dcf-assumptions", default=None, help="path relative to the repo (default from config)")
    args = parser.parse_args(argv)
    env = open_env(args.db, args.dcf_assumptions)
    a = answer_question(args.question, env)
    print(a.model_dump_json(indent=2, exclude={"tool_results"}))


if __name__ == "__main__":
    sys.exit(main())
