"""Tool layer: the tools behind one common interface. No LLM inside.

    run_tool(call: ToolCall, env: ToolEnv) -> ToolResult

Each tool has a typed input model (FactArgs, RatioArgs, DCFArgs, SearchArgs, PeriodArgs). Every result,
success or failure, is a ToolResult with the same shape:
  - numbers:  every figure the answer may use, each pointing at an evidence_id, with a display
              string formatted by code (the LLM copies it; it never rounds or converts).
  - evidence: where each figure or passage comes from (source, page, period, basis).
  - passages: chunk text, for qualitative answers (never a source of numbers).
  - error:    why the tool refused (missing fact, unknown period, no assumptions file ...).

Evidence ids are stable strings that point back into the stores:
  fact:<fact_id>        a row in SQLite `fact`
  calc:<computed_id>    a row in SQLite `computed_metric` (inputs are fact:<id> entries)
  dcf:<run_id>          a row in SQLite `dcf_run`
  chunk:<chunk_id>      a chunk in ChromaDB
  period:<label>        a period's dates (label with '_' for spaces), from the company config (fiscal_year_end_month) and the
                        period resolver (periods.py)
"""
import sqlite3
from datetime import date
from pathlib import Path
from typing import Callable, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from erp.config import REPO
from erp.dcf.assumptions import AssumptionError
from erp.dcf.engine import DCFError
from erp.dcf.run import DCFResult, run_dcf
from erp.ingest.embed import EmbeddingError, embed_texts
from erp.periods import PeriodError, resolve_period
from erp.tools.facts import FactLookupError, FactResult, get_financial_fact
from erp.tools.ratios import RatioError, compute_ratio, load_ratios
from erp.tools.search import SearchError, search_documents

TOOL_NAMES = ("get_financial_fact", "compute_ratio", "run_dcf", "search_documents", "explain_period")
Basis = Literal["consolidated", "standalone"]


# ---------- typed inputs ----------

class FactArgs(BaseModel):
    metric_id: str
    period: str
    basis: Basis = "consolidated"


class RatioArgs(BaseModel):
    ratio_id: str
    period: str
    basis: Basis = "consolidated"


class DCFArgs(BaseModel):
    scenario: str
    include_sensitivity: bool = False


class SearchArgs(BaseModel):
    query: str = Field(min_length=1)
    doc_type: str | None = None
    fiscal_year: int | None = None


class PeriodArgs(BaseModel):
    period: str


ARGS_MODELS = {"get_financial_fact": FactArgs, "compute_ratio": RatioArgs,
               "run_dcf": DCFArgs, "search_documents": SearchArgs, "explain_period": PeriodArgs}


class ToolCall(BaseModel):
    tool: str
    args: dict


# ---------- typed outputs ----------

class Evidence(BaseModel):
    evidence_id: str                  # 'fact:12', 'calc:3', 'dcf:1', 'chunk:...', 'period:FY26'
    kind: Literal["fact", "calc", "dcf_run", "doc_chunk", "config"]
    source_id: int | None = None      # SQLite source_document id (None for calc / dcf_run)
    source_title: str
    page: int | None = None           # PDF page index, 1-based
    page_end: int | None = None
    page_label: str | None = None     # printed page number, if known
    period: str | None = None         # period label of the figure, or the document's period
    basis: str | None = None          # consolidated / standalone; None where it does not apply
    accounting_standard: str | None = None
    verified: bool | None = None      # facts: a human filled verified_by; calc: all inputs verified
    formula: str | None = None        # calc only
    input_evidence_ids: list[str] = []
    note: str | None = None


class ToolNumber(BaseModel):
    number_id: str                    # '<evidence_id>#<field>', e.g. 'fact:12#value'
    label: str                        # plain words, e.g. 'Revenue from operations, FY26'
    value: float
    unit: str
    display: str                      # formatted by code; the only form the LLM may write
    period: str | None
    basis: str | None
    evidence_id: str
    # For the verifier (M6): what the figure measures, so prose like "net margin fell" can be
    # checked against the right numbers. quantity = metric_id, ratio_id or DCF field.
    quantity: str | None = None
    measures_change: bool = False     # a growth rate: its sign is the direction of change
    variant: bool = False             # a sensitivity-grid value, not the scenario's own figure
    conditions: dict[str, float] = {}  # grid cells: the WACC and terminal growth (percent) it assumes


class Passage(BaseModel):
    evidence_id: str
    section: str
    text: str


class ToolResult(BaseModel):
    tool: str
    args: dict
    ok: bool
    error: str | None = None
    numbers: list[ToolNumber] = []
    evidence: list[Evidence] = []
    passages: list[Passage] = []
    notes: list[str] = []             # facts about the data the answer must carry (e.g. unverified)
    detail: dict | None = None        # full original tool output, for the calculation path in the UI


class ToolEnv(BaseModel):
    """What the tools need besides their arguments. The LLM never sets any of this."""
    model_config = {"arbitrary_types_allowed": True}
    conn: sqlite3.Connection
    ticker: str
    display: dict                     # config/agent.yaml `display`
    search_top_k: int = 5
    passage_chars: int = 900
    dcf_assumptions: Path = REPO / "data" / "manual" / "dcf_inputs.yaml"
    collection: object | None = None  # ChromaDB collection override (tests)
    embed_fn: Callable = embed_texts


# ---------- formatting (code, not the LLM) ----------

def format_number(value: float, unit: str, display: dict) -> str:
    decimals = display["decimals"].get(unit, 2)
    template = display["templates"].get(unit, "{v} " + unit)
    return template.format(v=f"{value:,.{decimals}f}")


def _number(evidence_id, field, label, value, unit, period, basis, display, *, quantity=None,
            measures_change=False, variant=False) -> ToolNumber:
    return ToolNumber(number_id=f"{evidence_id}#{field}", label=label, value=value, unit=unit,
                      display=format_number(value, unit, display), period=period, basis=basis,
                      evidence_id=evidence_id, quantity=quantity, measures_change=measures_change,
                      variant=variant)


def _metric_names(conn) -> dict:
    return dict(conn.execute("SELECT metric_id, display_name FROM metric").fetchall())


def _fact_evidence(f: FactResult) -> Evidence:
    cross = ", ".join(f"fact:{c.fact_id} (source {c.source_id}, PDF p.{c.source_page})" for c in f.cross_checked_by)
    return Evidence(
        evidence_id=f"fact:{f.fact_id}", kind="fact", source_id=f.source_id, source_title=f.source_title,
        page=f.source_page, page_label=f.source_page_label, period=f.period_label, basis=f.basis,
        accounting_standard=f.accounting_standard, verified=f.verified,
        note=("restated figure; " if f.restated else "") + (f"also printed in: {cross}" if cross else "") or None)


def _unverified_note(facts: list[FactResult]) -> list[str]:
    ids = [f"fact:{f.fact_id}" for f in facts if not f.verified]
    if not ids:
        return []
    return [f"Not yet checked by a human: {', '.join(ids)} (entry method: "
            f"{', '.join(sorted({f.entry_method for f in facts if not f.verified}))})."]


# ---------- the tools ----------

def _fact_tool(a: FactArgs, env: ToolEnv) -> ToolResult:
    f = get_financial_fact(env.conn, env.ticker, a.metric_id, a.period, a.basis)
    name = _metric_names(env.conn).get(f.metric_id, f.metric_id)
    ev = _fact_evidence(f)
    num = _number(ev.evidence_id, "value", f"{name}, {f.period_label} ({f.basis})", f.value, f.unit,
                  f.period_label, f.basis, env.display, quantity=f.metric_id)
    notes = _unverified_note([f]) + [
        f"{f.period_label} runs from {f.period_start.isoformat()} to {f.period_end.isoformat()} "
        f"(fiscal year, not calendar year)."]
    return ToolResult(tool="get_financial_fact", args=a.model_dump(), ok=True, numbers=[num], evidence=[ev],
                      notes=notes, detail=f.model_dump(mode="json"))


def _ratio_tool(a: RatioArgs, env: ToolEnv) -> ToolResult:
    r = compute_ratio(env.conn, env.ticker, a.ratio_id, a.period, a.basis)
    names = _metric_names(env.conn)
    facts = [i.fact for i in r.inputs]
    calc_id = f"calc:{r.computed_id}"
    fact_evs = [_fact_evidence(f) for f in facts]
    calc_ev = Evidence(
        evidence_id=calc_id, kind="calc", source_title=f"computed_metric row {r.computed_id} ({r.formula_version})",
        period=r.period_label, basis=r.basis, verified=r.verified, formula=r.formula,
        input_evidence_ids=[e.evidence_id for e in fact_evs])
    numbers = [_number(calc_id, "value", f"{r.display_name}, {r.period_label} ({r.basis})", r.value, r.unit,
                       r.period_label, r.basis, env.display, quantity=r.ratio_id,
                       measures_change=load_ratios()[r.ratio_id]["kind"] == "yoy_growth")]
    # A sum or average operand (e.g. EBIT, average equity) is a figure code computed, so it is a
    # tool number too: an answer may quote it, and the verifier can check it.
    spec = load_ratios()[r.ratio_id]
    for side in ("numerator", "denominator"):
        if spec["kind"] == "quotient" and not isinstance(spec[side], str):
            name = getattr(r, f"{side}_label") or side
            numbers.append(_number(calc_id, side, f"{name}, {r.period_label} ({r.basis}; {side} of {r.display_name})",
                                   getattr(r, f"{side}_value"), facts[0].unit, r.period_label, r.basis, env.display,
                                   quantity=f"{r.ratio_id}.{side}"))
    for i, ev in zip(r.inputs, fact_evs):
        f = i.fact
        numbers.append(_number(ev.evidence_id, "value", f"{names.get(f.metric_id, f.metric_id)}, {f.period_label} "
                               f"({f.basis}; input '{i.role}')", f.value, f.unit, f.period_label, f.basis, env.display,
                               quantity=f.metric_id))
    return ToolResult(tool="compute_ratio", args=a.model_dump(), ok=True, numbers=numbers,
                      evidence=[calc_ev, *fact_evs],
                      notes=[f"Definition: {load_ratios()[r.ratio_id]['definition']}", *_unverified_note(facts)],
                      detail=r.model_dump(mode="json"))


def _dcf_tool(a: DCFArgs, env: ToolEnv) -> ToolResult:
    if not Path(env.dcf_assumptions).exists():
        shown = Path(env.dcf_assumptions)
        shown = shown.relative_to(REPO) if shown.is_relative_to(REPO) else shown.name
        raise AssumptionError(f"DCF assumptions file {shown} does not exist yet "
                              "(author-owned, plan P0.3); no DCF value can be given")
    d: DCFResult = run_dcf(env.conn, env.ticker, a.scenario, assumptions_path=env.dcf_assumptions)
    v = d.valuation
    dcf_id = f"dcf:{d.run_id}"
    money = d.units["money"]
    period = d.valuation_date
    # Base-year revenue and bridge items read from the facts database (D2): each fact is cited
    # with its page, and the DCF run lists them as its inputs (so citing the run cites them too).
    fact_evs = list({e.evidence_id: e for e in (_fact_evidence(f) for i in d.db_inputs for f in i.facts)}.values())
    ev = Evidence(
        evidence_id=dcf_id, kind="dcf_run",
        source_title=f"DCF run {d.run_id}, scenario '{d.scenario}' ({d.label}); assumptions file "
                     f"{Path(env.dcf_assumptions).name}",
        period=period, input_evidence_ids=[e.evidence_id for e in fact_evs],
        note="Valuation date shown as period. Basis as stated in the assumptions file."
             + (f" Inputs read from the facts database: {', '.join(i.assumption for i in d.db_inputs)}."
                if d.db_inputs else ""))

    def n(field, label, value, unit, quantity=None, variant=False, conditions=None):
        num = _number(dcf_id, field, label, value, unit, period, None, env.display,
                      quantity=quantity or field, variant=variant)
        num.conditions = conditions or {}
        return num

    # Rates are stored as decimals; code converts them to percent for display.
    numbers = [
        n("value_per_share", "DCF value per share", v.value_per_share, d.per_share_unit),
        n("enterprise_value", "Enterprise value", v.enterprise_value, money),
        n("equity_value", "Equity value", v.equity_value, money),
        n("wacc", "WACC", v.wacc * 100, "PERCENT"),
        n("terminal_growth", "Terminal growth rate", v.terminal_growth * 100, "PERCENT"),
    ]
    names = _metric_names(env.conn)
    for i in d.db_inputs:
        unit = d.units["shares"] if i.assumption == "diluted_shares" else money
        words = i.assumption.replace("_", " ")
        how = " (0: leases treated as an operating cost)" if i.factor == 0 else ""
        numbers.append(n(f"input_{i.assumption}", f"{words.capitalize()} used in the DCF{how}; from the facts "
                         f"database{' plus assumptions-file adjustments' if i.adjustments else ''}", i.value, unit,
                         quantity=i.assumption))
        for k, adj in enumerate(i.adjustments, 1):
            numbers.append(n(f"input_{i.assumption}_adjustment_{k}", f"Adjustment to {words} from the assumptions "
                             f"file: {adj.rationale}", adj.value, unit, quantity=f"{i.assumption}.adjustment"))
        for f in i.facts:
            numbers.append(_number(f"fact:{f.fact_id}", "value", f"{names.get(f.metric_id, f.metric_id)}, "
                                   f"{f.period_label} ({f.basis}; DCF input '{i.assumption}')", f.value, f.unit,
                                   f.period_label, f.basis, env.display, quantity=f.metric_id))
    if v.tv_share_of_ev is not None:
        numbers.append(n("tv_share_of_ev", "Terminal value as share of enterprise value", v.tv_share_of_ev * 100,
                         "PERCENT"))
    if a.include_sensitivity:
        g = d.sensitivity
        # The grid's WACC and growth values are numbers too, so prose may quote them.
        numbers += [n(f"sensitivity_wacc_{i}", "WACC used in the sensitivity grid", w * 100, "PERCENT",
                      "wacc", True) for i, w in enumerate(g.wacc_values)]
        numbers += [n(f"sensitivity_growth_{j}", "Terminal growth used in the sensitivity grid", gr * 100,
                      "PERCENT", "terminal_growth", True) for j, gr in enumerate(g.growth_values)]
        for i, w in enumerate(g.wacc_values):
            for j, gr in enumerate(g.growth_values):
                if g.value_per_share[i][j] is not None:
                    numbers.append(n(f"sensitivity_{i}_{j}", f"Value per share at WACC {w * 100:.2f}% and "
                                     f"terminal growth {gr * 100:.2f}%", g.value_per_share[i][j], d.per_share_unit,
                                     "value_per_share", True, {"wacc": w * 100, "terminal_growth": gr * 100}))
    notes = [d.disclaimer, f"Scenario label: {d.label}.", *d.notes]
    notes += [f"Check {c.check_id}: {c.status} ({c.detail})" for c in d.checks if c.status != "pass"]
    return ToolResult(tool="run_dcf", args=a.model_dump(), ok=True, numbers=numbers, evidence=[ev, *fact_evs],
                      notes=notes,
                      detail=d.model_dump(mode="json"))


def _search_tool(a: SearchArgs, env: ToolEnv) -> ToolResult:
    hits = search_documents(a.query, top_k=env.search_top_k, doc_type=a.doc_type, fiscal_year=a.fiscal_year,
                            collection=env.collection, embed_fn=env.embed_fn)
    periods = dict(env.conn.execute("SELECT source_id, period_covered FROM source_document").fetchall())
    evidence, passages = [], []
    for h in hits:
        eid = f"chunk:{h.chunk_id}"
        evidence.append(Evidence(
            evidence_id=eid, kind="doc_chunk", source_id=h.source_id, source_title=h.doc_title, page=h.page,
            page_end=h.page_end, page_label=h.page_label or None, period=periods.get(h.source_id),
            note=f"section: {h.section}; score {h.score:.3f}" + ("; table-heavy" if h.is_table_heavy else "")))
        passages.append(Passage(evidence_id=eid, section=h.section, text=h.text[:env.passage_chars]))
    return ToolResult(tool="search_documents", args=a.model_dump(), ok=bool(hits),
                      error=None if hits else "no passages found", evidence=evidence, passages=passages,
                      detail={"results": [h.model_dump() for h in hits]})


def _day(d: date) -> str:
    return f"{d.day} {d.strftime('%B %Y')}"


def _period_tool(a: PeriodArgs, env: ToolEnv) -> ToolResult:
    """What a period label means: its real dates, from the company's fiscal year end month (company
    config) and the period resolver. No database facts are needed, so it works for any valid label."""
    config = REPO / "config" / "companies" / f"{env.ticker.lower()}.yaml"
    with open(config) as f:
        company = (yaml.safe_load(f) or {})["company"]
    fy_end = company["fiscal_year_end_month"]
    p = resolve_period(a.period, fy_end)
    name = company.get("name", env.ticker)
    end_month = date(2000, fy_end, 1).strftime("%B")
    dates = f"{_day(p.start_date)} to {_day(p.end_date)} ({p.start_date.isoformat()} to {p.end_date.isoformat()})"
    if p.period_type == "FY":
        notes = [f"{p.label} is {name}'s fiscal year from {dates}; its fiscal year ends in {end_month}."]
        if p.start_date.month == 1:
            notes.append(f"{p.label} is the same as calendar year {p.end_date.year}.")
        else:
            notes.append(f"{p.label} is not calendar year {p.end_date.year} (1 January to 31 December "
                         f"{p.end_date.year}); it covers part of {p.start_date.year} and part of {p.end_date.year}.")
    else:
        fy = resolve_period(f"FY{p.fiscal_year % 100:02d}", fy_end)
        notes = [f"{p.label} is quarter {p.period_type[1]} of {fy.label}, from {dates}. {fy.label} runs from "
                 f"{_day(fy.start_date)} to {_day(fy.end_date)}; the fiscal year ends in {end_month}."]
    # Evidence ids carry no spaces ('Q3 FY27' -> 'period:Q3_FY27'), so "[period:Q3_FY27]" reads as one id.
    ev = Evidence(evidence_id=f"period:{p.label.replace(' ', '_')}", kind="config", period=p.label,
                  source_title=f"Company config ({config.relative_to(REPO)}: fiscal_year_end_month = {fy_end}) "
                               f"and the period resolver (src/erp/periods.py)")
    return ToolResult(tool="explain_period", args=a.model_dump(), ok=True, evidence=[ev], notes=notes,
                      detail=p.model_dump(mode="json"))


RUNNERS = {"get_financial_fact": (FactArgs, _fact_tool), "compute_ratio": (RatioArgs, _ratio_tool),
           "run_dcf": (DCFArgs, _dcf_tool), "search_documents": (SearchArgs, _search_tool),
           "explain_period": (PeriodArgs, _period_tool)}

# Expected refusals from the tools. Anything else is a bug and is raised, not hidden.
TOOL_ERRORS = (FactLookupError, PeriodError, RatioError, AssumptionError, DCFError, SearchError, EmbeddingError)


def run_tool(call: ToolCall, env: ToolEnv) -> ToolResult:
    if call.tool not in RUNNERS:
        return ToolResult(tool=call.tool, args=call.args, ok=False, error=f"unknown tool {call.tool!r}")
    args_model, runner = RUNNERS[call.tool]
    try:
        args = args_model(**call.args)
    except ValidationError as e:
        return ToolResult(tool=call.tool, args=call.args, ok=False, error=f"bad arguments: {e.errors()}")
    try:
        return runner(args, env)
    except TOOL_ERRORS as e:
        return ToolResult(tool=call.tool, args=args.model_dump(), ok=False, error=str(e))
