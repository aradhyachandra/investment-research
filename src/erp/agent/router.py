"""Router v1, step 1: the LLM picks tools and arguments from a fixed list. Nothing runs here.

The fixed lists (metrics, ratios, periods, DCF scenarios) come from config and the database,
and are put into the JSON schema as enums, so a small model can only choose, not invent.
The plan's Router v0 (free-form tool calling) is not built; P0.6 compared it (NOTES.md).

Output: a RoutePlan. A question is refused (no tools run) when the model says it is out of
scope or gives a refusal reason. A reply that cannot be read is a routing failure, never a guess.
"""
import json
import sqlite3
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from erp.agent.tools import ARGS_MODELS, TOOL_NAMES, ToolCall
from erp.ingest.pdf_to_chunks import load_ingest_config
from erp.tools.ratios import load_ratios

QUESTION_TYPES = ["numeric", "ratio", "valuation", "qualitative", "mixed", "out_of_scope"]
REFUSAL_REASONS = ["none", "investment_advice", "price_prediction", "other_company", "outside_data"]
# The flat call shape the model fills in. Each tool keeps only its own fields (ARGS_MODELS).
CALL_FIELDS = ["metric_id", "ratio_id", "period", "basis", "scenario", "include_sensitivity", "query"]


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
    question_type: Literal["numeric", "ratio", "valuation", "qualitative", "mixed", "out_of_scope",
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


def route_schema(catalog: Catalog, max_calls: int) -> dict:
    def optional(values):
        return {"enum": [*values, None]}
    call = {
        "type": "object",
        "properties": {
            "tool": {"enum": list(TOOL_NAMES)},
            "metric_id": optional(catalog.metrics),
            "ratio_id": optional(catalog.ratios),
            "period": optional(catalog.periods),
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
  qualitative questions: strategy, risks, clients, people, policies, management commentary.
  Write the query as a short search phrase.

ALLOWED VALUES
metric_id:
{_bullets(catalog.metrics)}
ratio_id:
{_bullets(catalog.ratios)}
period: {", ".join(catalog.periods)}   (Indian fiscal years: FY26 = 1 April 2025 to 31 March 2026)
basis: consolidated (default) or standalone
scenario: {scenarios}

RULES
- Use compute_ratio for margins and growth rates; never ask for the inputs separately to work them out.
- A question about a change between two years of a ratio needs one compute_ratio call per year.
- A question that asks for figures and an explanation is "mixed": add a search_documents call.
- Set question_type to out_of_scope, make no calls, and set refusal_reason when the question:
  asks for personal investment advice or what to do with the shares (investment_advice);
  asks for a forecast of the share price or market moves (price_prediction);
  is about, or compares with, any other company (other_company);
  needs a period or figure that is not in the allowed values above (outside_data).
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


def route(question: str, catalog: Catalog, llm_fn, *, max_calls: int) -> RoutePlan:
    reply = llm_fn(router_messages(question, catalog), schema=route_schema(catalog, max_calls))
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
    if qtype == "out_of_scope" or reason != "none":
        return RoutePlan(question_type=qtype, refusal_reason=reason if reason != "none" else "outside_scope",
                         refuse=True, raw=reply.text, model=reply.model)

    problems = []
    items = [c for c in data.get("calls", []) if isinstance(c, dict)]
    if len(items) > max_calls:
        problems.append(f"router asked for {len(items)} calls; cut to {max_calls}")
        items = items[:max_calls]
    calls = [_to_call(c) for c in items]
    if not calls:
        return RoutePlan(**failed, problems=["router chose no tools and gave no refusal reason"])
    return RoutePlan(question_type=qtype, calls=calls, problems=problems, raw=reply.text, model=reply.model)
