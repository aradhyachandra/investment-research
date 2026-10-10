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

Search year (R1, R2), decided by code from the question text, never by the model: a question naming
exactly one fiscal year with data (FY24, FY 2024, 2023-24, fiscal 2024) filters search_documents to
that year; a question naming no period lets search prefer the latest report; anything else (two or
more periods, a quarter, a year with no data) gets neither.

Named metric (E2), decided by code: when the question uses exactly one metric's own name (its
display name, or the opening phrase of its definition) and the model's plan is plain fact lookups
that use none of it, the lookups are replaced by that metric. Seen live (PDEV-07): "profit for the
year, including non-controlling interests" -> profit_attributable_to_owners + non_controlling_interests.

E3, decided by code (dev failures of the v1.1 eval, docs/E3_dev_fixes.md):
- Named ratio: the same rule for a ratio's own name (V11-C05: "effective tax rate" -> two input facts).
- A ratio that spans years (CAGR, year-on-year growth) is called once, for the period the question
  names, not once per year of a range (V11-C11: a 3-year CAGR asked for FY23, FY24, FY25 and FY26).
- A group of metrics named by its family name ("exceptional items", from display names "Exceptional
  items - <line>") gets the stored facts of the group for the named year (V11-E01: a search only).
"""
import json
import re
import sqlite3
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from erp.agent.tools import ARGS_MODELS, TOOL_NAMES, ToolCall
from erp.agent.verifier import period_spans, periods_in
from erp.ingest.pdf_to_chunks import load_ingest_config
from erp.periods import resolve_period
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
    metric_definitions: dict[str, str] = {}   # metric_id -> definition (for names; not in the prompt)
    ratios: dict[str, str]           # ratio_id -> display name
    ratio_definitions: dict[str, str] = {}    # ratio_id -> definition (for names; not in the prompt)
    ratio_spans: dict[str, int] = {}          # ratio_id -> fiscal years it spans (growth 1, CAGR n); others absent
    fact_periods: dict[str, dict[str, bool]] = {}   # metric_id -> {period label: value is not zero}, consolidated
    periods: list[str]               # labels with data in the database
    scenarios: list[str]             # DCF scenario names in the assumptions file ([] if none)
    doc_types: list[str]             # indexed document types
    fiscal_year_end_month: int       # from the company table; for the period resolver


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
    company = conn.execute("SELECT company_id, name, fiscal_year_end_month FROM company WHERE ticker_nse = ?",
                           (ticker,)).fetchone()
    if company is None:
        raise RoutingError(f"unknown company ticker {ticker!r}")
    rows = conn.execute("SELECT metric_id, display_name, definition FROM metric ORDER BY metric_id").fetchall()
    metrics = {m: name for m, name, _ in rows}
    periods = [r[0] for r in conn.execute(
        "SELECT DISTINCT p.label FROM period p JOIN fact f USING (period_id) WHERE p.company_id = ?"
        " ORDER BY p.end_date, p.label", (company[0],))]
    scenarios = []
    if Path(dcf_assumptions).exists():
        with open(dcf_assumptions) as f:
            scenarios = list((yaml.safe_load(f) or {}).get("scenarios") or {})
    fact_periods = {}
    for m, label, value in conn.execute(
            "SELECT f.metric_id, p.label, f.value FROM fact_current f JOIN period p USING (period_id)"
            " WHERE f.company_id = ? AND f.basis = 'consolidated'", (company[0],)):
        fact_periods.setdefault(m, {})[label] = fact_periods.get(m, {}).get(label, False) or value != 0
    ratios = load_ratios()
    spans = {k: 1 if r["kind"] == "yoy_growth" else int(r["years"])
             for k, r in ratios.items() if r["kind"] in ("yoy_growth", "cagr")}
    return Catalog(company_name=company[1], ticker=ticker, metrics=metrics,
                   metric_definitions={m: d for m, _, d in rows},
                   ratios={k: r["display_name"] for k, r in ratios.items()},
                   ratio_definitions={k: r.get("definition", "") for k, r in ratios.items()},
                   ratio_spans=spans, fact_periods=fact_periods, periods=periods,
                   scenarios=scenarios, doc_types=load_ingest_config()["indexable_doc_types"],
                   fiscal_year_end_month=company[2])


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


def search_year(question: str, catalog: Catalog) -> int | None:
    """R2: the fiscal_year to filter search to, or None. Set only when the question names exactly one
    period, and it is a fiscal year (not a quarter) with data in the database; the number comes from
    the period resolver (FY24 -> 2024, the year the fiscal year ends in)."""
    named = list(dict.fromkeys(periods_in(question)))
    if len(named) != 1 or named[0] not in catalog.periods:
        return None
    p = resolve_period(named[0], catalog.fiscal_year_end_month)
    return p.fiscal_year if p.period_type == "FY" else None


def set_search_year(calls: list[ToolCall], question: str, catalog: Catalog) -> None:
    """Decided by code. R1: search prefers the latest report (SearchArgs default) unless the question
    or the search phrase names a period; then the search ranks all reports without the weight.
    R2: if the question names exactly one fiscal year with data, the search is also filtered to it."""
    year = search_year(question, catalog)
    for c in calls:
        if c.tool != "search_documents":
            continue
        if year is not None:
            c.args["fiscal_year"] = year
        if periods_in(question) or periods_in(c.args.get("query") or ""):
            c.args["prefer_latest"] = False


def _words(text: str) -> str:
    """Lower case, letters and digits only, single spaces (so "non-controlling" == "non controlling")."""
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _definition_opening(definition: str) -> str:
    """A definition's first phrase: the quoted line name it starts with ('"Total equity" as reported
    ...'), or the text before the first colon, semicolon, bracket, quote or full stop."""
    d = definition.strip()
    if d.startswith('"'):
        return d[1:].split('"', 1)[0]
    return re.split(r'[:;("]|\.\s', d, maxsplit=1)[0]


def metric_names(catalog: Catalog) -> dict[str, set[str]]:
    """Each metric's own names, in _words form: its display name without any bracketed qualifier
    ("Investments (current)" -> "investments"), and the opening phrase of its definition. A name of
    one word ("investments", "equity") is too loose and is dropped."""
    out = {}
    for m, display in catalog.metrics.items():
        candidates = [re.sub(r"\([^)]*\)", " ", display), _definition_opening(catalog.metric_definitions.get(m, ""))]
        out[m] = {w for w in map(_words, candidates) if len(w.split()) >= 2}
    return out


def ratio_names(catalog: Catalog) -> dict[str, set[str]]:
    """Each ratio's own names, as for metrics: its display name without a bracketed qualifier
    ("Operating margin (EBIT margin)" -> "operating margin"), and the opening phrase of its definition,
    unless that phrase contains a metric's own name: ratio definitions open with the formula's input
    ("Total tax expense ..." for the effective tax rate), and an input line does not name the ratio."""
    metric_words = {n for names in metric_names(catalog).values() for n in names}
    out = {}
    for r, display in catalog.ratios.items():
        names = {_words(re.sub(r"\([^)]*\)", " ", display))}
        opening = _words(_definition_opening(catalog.ratio_definitions.get(r, "")))
        if not any(f" {n} " in f" {opening} " for n in metric_words):
            names.add(opening)
        out[r] = {w for w in names if len(w.split()) >= 2}
    return out


def _question_words(question: str) -> str:
    """The question in _words form, padded with spaces, with period mentions (and an "in", "for" or
    "during" before them) blanked, so "profit for the year in FY26, including ..." reads as one name."""
    text = question
    for start, end in reversed(period_spans(question)):
        head = re.sub(r"\b(?:in|for|during)\s*$", "", text[:start], flags=re.I)
        text = head + " " + text[end:]
    return f" {_words(text)} "


def _name_hits(text: str, catalog: Catalog) -> list[tuple[int, int, str, str]]:
    """(start, end, "metric"|"ratio", id) for each own name found in a _question_words text. A name
    inside a longer found name does not count ("tax expense" inside "total tax expense" would not)."""
    found = []
    for kind, names_by_id in (("metric", metric_names(catalog)), ("ratio", ratio_names(catalog))):
        for i, names in names_by_id.items():
            for name in names:
                for hit in re.finditer(re.escape(f" {name} "), text):
                    found.append((hit.start(), hit.end(), kind, i))
    return [(s, e, k, i) for s, e, k, i in found
            if not any(s2 <= s and e <= e2 and (e2 - s2) > (e - s) for s2, e2, _, _ in found)]


def names_in(question: str, catalog: Catalog) -> set[tuple[str, str]]:
    """("metric", id) and ("ratio", id) for every metric or ratio the question names by its own name."""
    return {(k, i) for _, _, k, i in _name_hits(_question_words(question), catalog)}


def metrics_named_in(question: str, catalog: Catalog) -> set[str]:
    """Metrics whose own name appears in the question as whole words (see names_in). A name inside a
    longer matched name does not count ("non-controlling interests" inside "profit for the year,
    including non-controlling interests", or a metric name inside a ratio's name)."""
    return {i for k, i in names_in(question, catalog) if k == "metric"}


def _use_named_metric(calls: list[ToolCall], qtype: str, question: str, catalog: Catalog,
                      problems: list[str]) -> list[ToolCall]:
    """E2, decided by code: when the question names exactly one metric (and no ratio) and the plan is
    a plain lookup (question_type numeric, only fact calls), none of them for that metric, replace
    them with that metric (one call per period, in order, keeping each period's basis). Anything else
    is left to the model: two names, a plan with a ratio or a search, a "mixed" or other question
    type (a "why" question may fetch related lines on purpose), or the named metric already fetched."""
    if qtype != "numeric" or not calls or any(c.tool != "get_financial_fact" for c in calls):
        return calls
    named = names_in(question, catalog)
    if len(named) != 1 or next(iter(named))[0] != "metric":
        return calls
    ((_, metric),) = named
    if any(c.args.get("metric_id") == metric for c in calls):
        return calls
    out, seen = [], set()
    for c in calls:
        if c.args.get("period") in seen:
            continue
        seen.add(c.args.get("period"))
        out.append(ToolCall(tool=c.tool, args={**c.args, "metric_id": metric}))
    problems.append(f"router chose {', '.join(dict.fromkeys(c.args.get('metric_id') for c in calls))}; "
                    f"the question names {metric} ({catalog.metrics[metric]}), so code fetched that instead")
    return out


def _use_named_ratio(calls: list[ToolCall], qtype: str, question: str, catalog: Catalog,
                     problems: list[str]) -> list[ToolCall]:
    """E3, decided by code, with the named-metric rule's safeguards: the question names exactly one
    ratio (and no metric); the model's question type is numeric or ratio; every call is a fact or
    ratio lookup; none computes the named ratio. Then the plan becomes compute_ratio for it, one call
    per period of the plan, in order, keeping each period's basis."""
    if qtype not in ("numeric", "ratio") or not calls or any(c.tool not in _DATA_TOOLS for c in calls):
        return calls
    named = names_in(question, catalog)
    if len(named) != 1 or next(iter(named))[0] != "ratio":
        return calls
    ((_, ratio),) = named
    if any(c.tool == "compute_ratio" and c.args.get("ratio_id") == ratio for c in calls):
        return calls
    out, seen = [], set()
    for c in calls:
        if c.args.get("period") in seen:
            continue
        seen.add(c.args.get("period"))
        args = {"ratio_id": ratio, **{k: c.args[k] for k in ("period", "basis") if k in c.args}}
        out.append(ToolCall(tool="compute_ratio", args=args))
    chosen = dict.fromkeys(c.args.get("metric_id") or c.args.get("ratio_id") for c in calls)
    problems.append(f"router chose {', '.join(map(str, chosen))}; the question names {ratio} "
                    f"({catalog.ratios[ratio]}), so code computes that ratio instead")
    return out


def _one_period_for_span_ratios(calls: list[ToolCall], qtype: str, question: str, catalog: Catalog,
                                problems: list[str]) -> list[ToolCall]:
    """E3, decided by code: a ratio that spans years (growth: 1, a CAGR: its years) already covers the
    range, so it is called once, for the period the question names: the only period named, or, when
    exactly two fiscal years are named and they are the ratio's own span apart, the later one ("CAGR
    from FY23 to FY26" -> FY26). Only for numeric/ratio questions. Not for two adjacent years and a
    one-year ratio ("growth in FY25 and FY26" may compare two growth rates), nor for a range longer
    than the span (a trend: one value per year is the point)."""
    if qtype not in ("numeric", "ratio"):
        return calls
    named = [p for p in dict.fromkeys(periods_in(question)) if p in catalog.periods]
    out = list(calls)
    for key in dict.fromkeys((c.args.get("ratio_id"), c.args.get("basis")) for c in calls
                             if c.tool == "compute_ratio" and c.args.get("ratio_id") in catalog.ratio_spans):
        span = catalog.ratio_spans[key[0]]
        target = None
        if len(named) == 1:
            target = named[0]
        elif len(named) == 2 and span >= 2:
            a, b = (resolve_period(p, catalog.fiscal_year_end_month) for p in named)
            if a.period_type == b.period_type == "FY" and abs(a.fiscal_year - b.fiscal_year) == span:
                target = max((a, b), key=lambda p: p.fiscal_year).label
        group = [c for c in out if c.tool == "compute_ratio" and (c.args.get("ratio_id"), c.args.get("basis")) == key]
        if target is None or [c.args.get("period") for c in group] == [target]:
            continue
        first = out.index(group[0])
        out = [c for c in out if c not in group]
        out.insert(first, ToolCall(tool="compute_ratio", args={**group[0].args, "period": target}))
        problems.append(f"{key[0]} spans {span} year(s), so code called it once, for {target} (the period the "
                        f"question names); the plan had {', '.join(str(c.args.get('period')) for c in group)}")
    return out


# A group mention after one of these words qualifies another line ("profit before exceptional
# items"); it is not a question about the group.
_GROUP_QUALIFIERS = ("before", "after", "excluding", "including", "ex", "net of")


def _singular(words: str) -> str:
    return re.sub(r"s$", "", words)


def metric_groups(catalog: Catalog) -> dict[str, set[str]]:
    """Groups of metrics, from display names of the form "<group> - <line>" (config/metrics.yaml):
    group name in _words form, singular ("Exceptional items - ..." -> "exceptional item") -> its
    metric_ids. A group needs two or more metrics."""
    groups = {}
    for m, display in catalog.metrics.items():
        if " - " in display:
            groups.setdefault(_singular(_words(display.split(" - ", 1)[0])), set()).add(m)
    return {g: ms for g, ms in groups.items() if len(ms) >= 2}


def _groups_asked_about(question: str, catalog: Catalog) -> list[str]:
    """Groups the question asks about: the group name (singular or plural) as whole words, not inside
    a metric's or ratio's own name, not after a qualifier word, and no member of the group named."""
    text = _question_words(question)
    hits = _name_hits(text, catalog)
    named = {i for _, _, _, i in hits}
    out = []
    for group, members in metric_groups(catalog).items():
        if named & members:
            continue
        for m in re.finditer(re.escape(f" {group}") + r"s? ", text):
            inside = any(s <= m.start() + 1 and m.end() - 1 <= e for s, e, _, _ in hits)
            qualified = any(text[:m.start() + 1].endswith(f" {q} ") for q in _GROUP_QUALIFIERS)
            if not inside and not qualified:
                out.append(group)
                break
    return out


def _add_group_facts(calls: list[ToolCall], question: str, catalog: Catalog, max_calls: int,
                     problems: list[str]) -> list[ToolCall]:
    """E3, decided by code: a question about a group ("what was the exceptional item in FY24?") gets a
    fact lookup for each member with a stored fact in each period the question names (with data):
    the lines that are not zero, or, if all are zero, the zero lines, so the answer can say so from the
    facts. The model's calls are kept (a search explains the item); if the plan is then too long, the
    model's other lookups go first, then its searches. No period named -> nothing added (code does not
    pick a year)."""
    periods = [p for p in dict.fromkeys(periods_in(question)) if p in catalog.periods]
    added = []
    for group in _groups_asked_about(question, catalog):
        for p in periods:
            have = [m for m in sorted(metric_groups(catalog)[group]) if p in catalog.fact_periods.get(m, {})]
            nonzero = [m for m in have if catalog.fact_periods[m][p]]
            for m in nonzero or have:
                if not any(c.tool == "get_financial_fact" and c.args.get("metric_id") == m
                           and c.args.get("period") == p for c in calls + added):
                    added.append(ToolCall(tool="get_financial_fact",
                                          args={"metric_id": m, "period": p, "basis": "consolidated"}))
        if added:
            problems.append(f"the question asks about the group '{group}' for {', '.join(periods)}; code added "
                            f"the stored lines: {', '.join(c.args['metric_id'] + ' ' + c.args['period'] for c in added)}")
    if not added:
        return calls
    members = set().union(*metric_groups(catalog).values())
    out = [*added, *calls]
    for searches in (False, True):                     # the model's other lookups go first, then searches
        for c in reversed(calls):
            if len(out) > max_calls and (c.tool == "search_documents") == searches \
                    and not (c.tool == "get_financial_fact" and c.args.get("metric_id") in members):
                out.remove(c)
    return out[:max_calls]


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
    calls = _use_named_metric([_to_call(c) for c in items], qtype, question, catalog, problems)
    calls = _use_named_ratio(calls, qtype, question, catalog, problems)
    set_search_year(calls, question, catalog)
    if not calls:
        return RoutePlan(**failed, problems=["router chose no tools and gave no refusal reason"])
    with_data = [p for p in dict.fromkeys(periods_in(question)) if p in catalog.periods]
    calls += _missing_years(calls, with_data, max_calls, problems)
    calls = _one_period_for_span_ratios(calls, qtype, question, catalog, problems)
    calls = _add_group_facts(calls, question, catalog, max_calls, problems)
    no_data = [c for c in calls if c.tool in _DATA_TOOLS and c.args.get("period") not in catalog.periods]
    if len(no_data) == len(calls):
        # Decided by code, not the model: every lookup is for a period with no data.
        return RoutePlan(question_type="out_of_scope", refusal_reason="outside_data", refuse=True, raw=reply.text,
                         model=reply.model, problems=[f"{c.tool} for {c.args.get('period')}, which has no data"
                                                      for c in no_data])
    return RoutePlan(question_type=qtype, calls=calls, problems=problems, raw=reply.text, model=reply.model)
