"""Router v1, step 1: the LLM picks tools and arguments from a fixed list. Nothing runs here.

The fixed lists (metrics, ratios, periods, DCF scenarios) come from config and the database,
and are put into the JSON schema as enums, so a small model can only choose, not invent.
The plan's Router v0 (free-form tool calling) is not built; P0.6 compared it (NOTES.md).

Output: a RoutePlan. A question is refused (no tools run) when the model says it is out of
scope or gives a refusal reason, or (decided by code) when every call it chose is a fact/ratio
lookup for a period with no data. A reply that cannot be read is a routing failure, never a guess.

Periods named in the question (read by code) are added to the allowed period values, so a
question about a period with no data (e.g. "what dates does Q3 FY24 cover?") can still reach
explain_period instead of being forced into a refusal.
"""
import json
import sqlite3
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from erp.agent.tools import ARGS_MODELS, TOOL_NAMES, ToolCall
from erp.agent.verifier import periods_in
from erp.ingest.pdf_to_chunks import load_ingest_config
from erp.tools.ratios import load_ratios

QUESTION_TYPES = ["numeric", "ratio", "valuation", "qualitative", "period", "mixed", "out_of_scope"]
REFUSAL_REASONS = ["none", "investment_advice", "price_prediction", "other_company", "outside_data"]
# The flat call shape the model fills in. Each tool keeps only its own fields (ARGS_MODELS).
CALL_FIELDS = ["metric_id", "ratio_id", "period", "basis", "scenario", "include_sensitivity", "query"]
# metric_id choice for "the figure asked about is not in the list". Without it, a model that has
# already chosen get_financial_fact must pick some listed metric (seen live: lease interest ->
# cash_and_equivalents) and then refuses. Code turns it into a search of the filings.
NOT_LISTED = "not_listed"


class RoutingError(ValueError):
    pass


class Catalog(BaseModel):
    company_name: str
    ticker: str
    metrics: dict[str, str]          # metric_id -> display name
    ratios: dict[str, str]           # ratio_id -> display name
    periods: list[str]               # labels with data in the database
    scenarios: list[str]             # DCF scenario names in the assumptions file ([] if none)
    doc_types: list[str]             # indexed document types


class RoutePlan(BaseModel):
    question_type: Literal["numeric", "ratio", "valuation", "qualitative", "period", "mixed", "out_of_scope",
                           "routing_failed"]
    refusal_reason: str = "none"
    calls: list[ToolCall] = []
    refuse: bool = False
    problems: list[str] = []         # what was wrong with the model's reply, if anything
    raw: str = ""                    # the model's reply as received
    model: str | None = None


def build_catalog(conn: sqlite3.Connection, ticker: str, dcf_assumptions: Path) -> Catalog:
    company = conn.execute("SELECT company_id, name FROM company WHERE ticker_nse = ?", (ticker,)).fetchone()
    if company is None:
        raise RoutingError(f"unknown company ticker {ticker!r}")
    metrics = dict(conn.execute("SELECT metric_id, display_name FROM metric ORDER BY metric_id").fetchall())
    periods = [r[0] for r in conn.execute(
        "SELECT DISTINCT p.label FROM period p JOIN fact f USING (period_id) WHERE p.company_id = ?"
        " ORDER BY p.end_date, p.label", (company[0],))]
    scenarios = []
    if Path(dcf_assumptions).exists():
        with open(dcf_assumptions) as f:
            scenarios = list((yaml.safe_load(f) or {}).get("scenarios") or {})
    return Catalog(company_name=company[1], ticker=ticker, metrics=metrics,
                   ratios={k: r["display_name"] for k, r in load_ratios().items()}, periods=periods,
                   scenarios=scenarios, doc_types=load_ingest_config()["indexable_doc_types"])


def route_schema(catalog: Catalog, max_calls: int, extra_periods: list[str] = ()) -> dict:
    """extra_periods: valid period labels named in the question but without data (for explain_period)."""
    def optional(values):
        return {"enum": [*values, None]}
    call = {
        "type": "object",
        "properties": {
            "tool": {"enum": list(TOOL_NAMES)},
            "metric_id": optional([*catalog.metrics, NOT_LISTED]),
            "ratio_id": optional(catalog.ratios),
            "period": optional([*catalog.periods, *[p for p in extra_periods if p not in catalog.periods]]),
            "basis": optional(["consolidated", "standalone"]),
            "scenario": optional(catalog.scenarios) if catalog.scenarios else {"type": ["string", "null"]},
            "include_sensitivity": {"type": ["boolean", "null"]},
            "query": {"type": ["string", "null"]},
        },
        "required": ["tool"],
    }
    # `calls` comes first: Ollama generates fields in schema order, and deciding the type first
    # made small models label plain lookups out_of_scope (P0.6 run, 2026-10-04: 5 of 20 vs 19 of 20).
    return {
        "type": "object",
        "properties": {
            "calls": {"type": "array", "maxItems": max_calls, "items": call},
            "question_type": {"enum": QUESTION_TYPES},
            "refusal_reason": {"enum": REFUSAL_REASONS},
        },
        "required": ["calls", "question_type", "refusal_reason"],
    }


def _bullets(d: dict) -> str:
    return "\n".join(f"  - {k}: {v}" for k, v in d.items())


# Worked examples. Written to differ from the provisional dev questions (tests/), and never
# copied from the eval set. A DCF example appears only if a scenario exists.
_EXAMPLES = [
    ("What was the company's total equity at the end of {last}?",
     {"calls": [{"tool": "get_financial_fact", "metric_id": "total_equity", "period": "{last}",
                 "basis": "consolidated"}], "question_type": "numeric", "refusal_reason": "none"}),
    ("How fast did net profit grow in {last}?",
     {"calls": [{"tool": "compute_ratio", "ratio_id": "net_profit_growth_yoy", "period": "{last}",
                 "basis": "consolidated"}], "question_type": "ratio", "refusal_reason": "none"}),
    ("What does the annual report say about employee attrition?",
     {"calls": [{"tool": "search_documents", "query": "employee attrition"}], "question_type": "qualitative",
      "refusal_reason": "none"}),
    ("Which dates does {last} run between?",
     {"calls": [{"tool": "explain_period", "period": "{last}"}], "question_type": "period",
      "refusal_reason": "none"}),
    ("What was revenue in FY19?",
     {"calls": [], "question_type": "out_of_scope", "refusal_reason": "outside_data"}),
    ("Is this a good stock to own?",
     {"calls": [], "question_type": "out_of_scope", "refusal_reason": "investment_advice"}),
]


def _examples(catalog: Catalog) -> str:
    last = catalog.periods[-1] if catalog.periods else "FY26"
    examples = list(_EXAMPLES)
    if catalog.scenarios:
        examples.insert(3, ("What does the {scenario} DCF scenario give per share?",
                            {"calls": [{"tool": "run_dcf", "scenario": "{scenario}", "include_sensitivity": False}],
                             "question_type": "valuation", "refusal_reason": "none"}))
    # Drop an example whose metric/ratio this company does not have, or whose "missing" period it does.
    def fits(q, a):
        calls = a["calls"]
        return all(c.get("metric_id", next(iter(catalog.metrics), None)) in catalog.metrics
                   and c.get("ratio_id", next(iter(catalog.ratios), None)) in catalog.ratios for c in calls) \
            and not (a["refusal_reason"] == "outside_data" and any(p in q for p in catalog.periods))
    examples = [(q, a) for q, a in examples if fits(q, a)]
    fill = {"last": last, "scenario": catalog.scenarios[-1] if catalog.scenarios else ""}
    return "\n".join(f"Q: {q.format(**fill)}\n{json.dumps(a).replace('{last}', last).replace('{scenario}', fill['scenario'])}"
                     for q, a in examples)


def router_messages(question: str, catalog: Catalog) -> list[dict]:
    scenarios = ", ".join(catalog.scenarios) if catalog.scenarios else "(none defined yet)"
    system = f"""You are the router of a research tool about {catalog.company_name} ({catalog.ticker}).
You do not answer the question. You choose which tools to run, and with which arguments.

TOOLS
- get_financial_fact(metric_id, period, basis): one reported figure from the financial statements.
- compute_ratio(ratio_id, period, basis): a ratio or growth rate computed in code from reported figures.
- run_dcf(scenario, include_sensitivity): the discounted cash flow model for a named scenario of the
  author's assumptions. include_sensitivity=true when the question asks how the value changes with
  WACC or terminal growth.
- search_documents(query): search the text of the company's filings (annual report, fact sheet) for
  qualitative questions: strategy, risks, clients, people, policies, management commentary, and for
  figures that are printed in the filings but are not in the metric_id list (e.g. a line item in the
  notes to the accounts). Write the query as a short search phrase naming the item.
- explain_period(period): what a period label means: its start and end dates. Use it for questions
  about which dates or months a period covers, or how a fiscal period relates to a calendar year.

ALLOWED VALUES
metric_id:
{_bullets(catalog.metrics)}
  - {NOT_LISTED}: the figure asked about is not in this list (the filings are searched for it instead)
ratio_id:
{_bullets(catalog.ratios)}
period: {", ".join(catalog.periods)}   (Indian fiscal years: FY26 = 1 April 2025 to 31 March 2026)
basis: consolidated (default) or standalone
scenario: {scenarios}

RULES
- Use compute_ratio for margins and growth rates; never ask for the inputs separately to work them out.
- A question about a change between two years of a ratio needs one compute_ratio call per year.
- A question that asks for figures and an explanation is "mixed": add a search_documents call.
- A figure that is not in the metric_id or ratio_id list may still be in the filings: use
  search_documents for it. Never substitute a different metric_id for the one asked about.
- Set question_type to out_of_scope, make no calls, and set refusal_reason when the question:
  asks for personal investment advice or what to do with the shares (investment_advice);
  asks for a forecast of the share price or market moves (price_prediction);
  is about, or compares with, any other company (other_company);
  asks for a figure for a period that has no data (outside_data). A figure missing from the
  metric_id list is not a reason to refuse; a question about what a period means is not either.
- Otherwise refusal_reason is "none". Most questions need at least one call.

OUTPUT FORMAT
{{"calls": [{{"tool": ..., <its arguments>}}, ...], "question_type": ..., "refusal_reason": ...}}

EXAMPLES (question, then the JSON to reply with)
{_examples(catalog)}
Reply with JSON only."""
    return [{"role": "system", "content": system}, {"role": "user", "content": question}]


def _to_call(item: dict) -> ToolCall:
    tool = item.get("tool")
    fields = ARGS_MODELS[tool].model_fields if tool in ARGS_MODELS else {}
    return ToolCall(tool=str(tool), args={k: v for k, v in item.items()
                                          if k in fields and k in CALL_FIELDS and v is not None})


# Tools whose period must have data in the database (explain_period needs none).
_DATA_TOOLS = ("get_financial_fact", "compute_ratio")
# Refusals that contradict a not_listed call: that call asks for a reported figure, which is never
# advice or a forecast, and a figure missing from the metric list is not outside the data (the
# filings may print it). Seen live: lease interest -> not_listed + "investment_advice". A refusal
# for another company still stands. The pattern pre-check (guardrails.py) runs before the router.
_NOT_LISTED_OVERRIDES = ("outside_data", "investment_advice", "price_prediction")


def _missing_years(calls: list[ToolCall], periods: list[str], max_calls: int, problems: list[str]) -> list[ToolCall]:
    """The rule "a change between two years needs one call per year", enforced in code: when the
    question names two or more periods with data and a fact/ratio was fetched for only some of them,
    add the same lookup for the others (within max_calls). The small model drops the earlier year
    (seen live, PDEV-17 in M5 and again after the 2026-10-04 prompt change)."""
    if len(periods) < 2:
        return []
    added = []
    for c in [c for c in calls if c.tool in _DATA_TOOLS]:
        key = {k: v for k, v in c.args.items() if k != "period"}
        have = {d.args.get("period") for d in calls + added if d.tool == c.tool
                and {k: v for k, v in d.args.items() if k != "period"} == key}
        for p in periods:
            if p not in have and len(calls) + len(added) < max_calls:
                added.append(ToolCall(tool=c.tool, args={**c.args, "period": p}))
                have.add(p)
                problems.append(f"added {c.tool} for {p}: the question names it and the router left it out")
    return added


def route(question: str, catalog: Catalog, llm_fn, *, max_calls: int) -> RoutePlan:
    named = [p for p in dict.fromkeys(periods_in(question)) if p not in catalog.periods]
    reply = llm_fn(router_messages(question, catalog), schema=route_schema(catalog, max_calls, named))
    failed = dict(question_type="routing_failed", raw=reply.text, model=reply.model)
    try:
        data = json.loads(reply.text)
    except json.JSONDecodeError:
        return RoutePlan(**failed, problems=["router reply is not JSON"])
    if not isinstance(data, dict) or data.get("question_type") not in QUESTION_TYPES \
            or not isinstance(data.get("calls", []), list):
        return RoutePlan(**failed, problems=[f"router reply does not match the schema: {reply.text[:200]}"])

    qtype = data["question_type"]
    reason = data.get("refusal_reason") if data.get("refusal_reason") in REFUSAL_REASONS else "none"
    items = [c for c in data.get("calls", []) if isinstance(c, dict)]
    problems = []
    not_listed = any(c.get("tool") == "get_financial_fact" and c.get("metric_id") == NOT_LISTED for c in items)
    if (qtype == "out_of_scope" or reason != "none") and not_listed and reason in (*_NOT_LISTED_OVERRIDES, "none"):
        problems.append(f"router refused ({qtype}, {reason}) while asking for a figure not in the metric list; "
                        "not a refusal reason, so the filings are searched")
        qtype, reason = "qualitative", "none"
    if qtype == "out_of_scope" or reason != "none":
        return RoutePlan(question_type=qtype, refusal_reason=reason if reason != "none" else "outside_scope",
                         refuse=True, raw=reply.text, model=reply.model)

    if len(items) > max_calls:
        problems.append(f"router asked for {len(items)} calls; cut to {max_calls}")
        items = items[:max_calls]
    for i, c in enumerate(items):
        if c.get("tool") == "get_financial_fact" and c.get("metric_id") == NOT_LISTED:
            items[i] = {"tool": "search_documents", "query": c.get("query") or question}
            problems.append(f"router chose metric_id {NOT_LISTED}; the filings are searched instead")
    calls = [_to_call(c) for c in items]
    if not calls:
        return RoutePlan(**failed, problems=["router chose no tools and gave no refusal reason"])
    with_data = [p for p in dict.fromkeys(periods_in(question)) if p in catalog.periods]
    calls += _missing_years(calls, with_data, max_calls, problems)
    no_data = [c for c in calls if c.tool in _DATA_TOOLS and c.args.get("period") not in catalog.periods]
    if len(no_data) == len(calls):
        # Decided by code, not the model: every lookup is for a period with no data.
        return RoutePlan(question_type="out_of_scope", refusal_reason="outside_data", refuse=True, raw=reply.text,
                         model=reply.model, problems=[f"{c.tool} for {c.args.get('period')}, which has no data"
                                                      for c in no_data])
    return RoutePlan(question_type=qtype, calls=calls, problems=problems, raw=reply.text, model=reply.model)
