"""Turns an Answer (agent/answer_schema.py) into plain display records for the Streamlit page.

No Streamlit here and no arithmetic on figures: every figure shown is either a display string the
tool layer already formatted, or a stored tool value formatted by tools.format_number (the same
code the agent uses). Rates stored as decimals are shown as percent (x 100), as tools.py does.
Nothing is looked up again in SQLite or ChromaDB, so a saved Answer (--demo) shows exactly what the
agent had when it answered.

Where the Answer lacks something, this module says so instead of filling it in:
  - Evidence has no doc_type. It is read from the tool output stored in the Answer
    (tool_results[].detail: facts carry source_doc_type, search hits carry doc_type).
    A source whose type is not found there gets the badge "Source type not recorded".
  - Chunk text is the full search hit (tool_results[].detail.results[].text) when present,
    otherwise the passage as cut for the composer.
"""
import json
from pathlib import Path

import yaml
from pydantic import BaseModel

from erp.agent.answer_schema import Answer
from erp.agent.tools import Evidence, ToolResult, format_number
from erp.config import REPO

UI_CONFIG = REPO / "config" / "ui.yaml"

FILING = "Filing"
AUTHORS_NOTE = "Author's note"
OTHER_DOCUMENT = "Other document"
TYPE_NOT_RECORDED = "Source type not recorded"
# Evidence that is not a document page.
KIND_BADGES = {"calc": "Calculation", "dcf_run": "DCF model", "config": "Company config"}

# How the DCF engine computes (src/erp/dcf/engine.py), written out for the reader.
DCF_FORMULAS = [
    "Cost of equity = risk-free rate + beta x equity risk premium",
    "WACC = equity weight x cost of equity + debt weight x cost of debt x (1 - debt tax rate)",
    "FCFF = EBIT x (1 - tax rate) + D&A - capex - increase in net working capital "
    "(other income is not included)",
    "Discount factor for year t = 1 / (1 + WACC)^t (year-end discounting)",
    "Terminal value = FCFF of the last forecast year x (1 + terminal growth) / (WACC - terminal growth)",
    "Enterprise value = sum of present values of FCFF + present value of terminal value",
    "Equity value = enterprise value + cash and investments - debt - lease liabilities - minority interest",
    "Value per share = equity value / diluted shares",
]


def load_ui_config(path=UI_CONFIG) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


# ---------- records the page shows ----------

class CitationView(BaseModel):
    evidence_id: str
    kind: str
    badge: str
    badge_note: str | None = None     # e.g. "AI-generated sample note ..."
    source_title: str
    page_text: str | None = None      # "PDF p.167 (printed p.197)"
    page: int | None = None           # PDF page index, 1-based (first page of a passage)
    period: str | None = None
    basis: str | None = None
    accounting_standard: str | None = None
    verified: bool | None = None
    note: str | None = None
    section: str | None = None        # chunks only
    chunk_text: str | None = None     # chunks only
    formula: str | None = None        # calc only
    input_evidence_ids: list[str] = []
    reported_value: float | None = None   # facts only: the figure as printed (to find it on the PDF page)


class NumberClaim(BaseModel):
    label: str
    display: str
    period: str | None
    basis: str | None
    citation: CitationView | None     # None only if the Answer is inconsistent (flagged on the page)
    inputs: list[CitationView] = []   # calc: the facts the ratio was computed from


class CalcInput(BaseModel):
    role: str
    label: str
    display: str
    citation: CitationView


class RatioPath(BaseModel):
    evidence_id: str
    title: str
    formula: str
    formula_version: str
    definition: str | None
    inputs: list[CalcInput]
    result_display: str
    verified: bool


class Assumption(BaseModel):
    name: str
    value: str                        # as written in the assumptions file (rates are decimals)
    rationale: str
    source: str
    defined_in: str


class DCFPath(BaseModel):
    evidence_id: str
    title: str
    status_line: str                  # from the assumptions file header, or a "not found" message
    scenario_label: str
    valuation_date: str
    formulas: list[str]
    wacc_rows: list[tuple[str, str]]
    fcff_rows: list[dict]
    valuation_rows: list[tuple[str, str]]
    bridge_rows: list[tuple[str, str]]
    sensitivity: dict | None          # {"columns": [...], "rows": [[wacc, cell, ...], ...]}
    assumptions: list[Assumption]
    checks: list[tuple[str, str, str]]   # (check_id, status, detail)
    disclaimer: str
    footer: str


class VerificationView(BaseModel):
    status: str                       # one sentence
    fallback_used: bool
    report_ok: bool | None = None     # the verifier's verdict on the model's text; None = no report
    issues: list[tuple[str, str, str, str]] = []   # (severity, check, span, message)
    warnings: list[str] = []


class AnswerView(BaseModel):
    question: str
    refused: bool
    refusal_reason: str | None
    answer_text: str
    composed_by: str
    model: str | None
    number_claims: list[NumberClaim]
    passage_claims: list[CitationView]
    passages_note: str | None         # when the list is "everything retrieved", not "what the model cited"
    citations: list[CitationView]
    ratio_paths: list[RatioPath]
    dcf_paths: list[DCFPath]
    limitations: list[str]
    verification: VerificationView


# ---------- badges ----------

def source_badge(doc_type: str | None, ui_cfg: dict) -> tuple[str, str | None]:
    """(badge, note) for a document type."""
    if doc_type is None:
        return TYPE_NOT_RECORDED, None
    badges = ui_cfg["badges"]
    note = badges.get("notes", {}).get(doc_type)
    if doc_type in badges["filing"]:
        return FILING, note
    if doc_type in badges["authors_note"]:
        return AUTHORS_NOTE, note
    return OTHER_DOCUMENT, note or f"document type: {doc_type}"


def doc_types(results: list[ToolResult]) -> dict[int, str]:
    """source_id -> doc_type, from the tool output stored in the Answer."""
    found = {}

    def add_fact(f: dict):
        if f.get("source_id") is not None and f.get("source_doc_type"):
            found[f["source_id"]] = f["source_doc_type"]
    for r in results:
        d = r.detail or {}
        if r.tool == "get_financial_fact":
            add_fact(d)
        elif r.tool == "compute_ratio":
            for i in d.get("inputs", []):
                add_fact(i.get("fact", {}))
        elif r.tool == "search_documents":
            for h in d.get("results", []):
                if h.get("source_id") is not None and h.get("doc_type"):
                    found[h["source_id"]] = h["doc_type"]
    return found


def page_text(e: Evidence) -> str | None:
    """PDF page index with the printed page in brackets (plan 4.1 rule 6)."""
    if e.page is None:
        return None
    text = f"PDF p.{e.page}"
    if e.page_end and e.page_end != e.page:
        text += f"-{e.page_end}"
    if e.page_label and e.page_label != str(e.page):
        text += f" (printed p.{e.page_label})"
    return text


def _chunk_texts(results: list[ToolResult]) -> dict[str, tuple[str, str]]:
    """evidence_id -> (section, text): the full hit text if stored, else the composer's passage."""
    out = {}
    for r in results:
        for p in r.passages:
            out[p.evidence_id] = (p.section, p.text)
        for h in (r.detail or {}).get("results", []) if r.tool == "search_documents" else []:
            if h.get("chunk_id") and h.get("text"):
                out[f"chunk:{h['chunk_id']}"] = (h.get("section", ""), h["text"])
    return out


def reported_values(results: list[ToolResult]) -> dict[str, float]:
    """fact evidence id -> value as printed in the filing, from the tool output stored in the Answer."""
    found = {}

    def add(f: dict):
        if f.get("fact_id") is not None and f.get("reported_value") is not None:
            found[f"fact:{f['fact_id']}"] = f["reported_value"]
    for r in results:
        d = r.detail or {}
        if r.tool == "get_financial_fact":
            add(d)
        elif r.tool == "compute_ratio":
            for i in d.get("inputs", []):
                add(i.get("fact", {}))
    return found


def citation_view(e: Evidence, types: dict[int, str], chunks: dict, ui_cfg: dict,
                  reported: dict[str, float] | None = None) -> CitationView:
    if e.kind in KIND_BADGES:
        badge, badge_note = KIND_BADGES[e.kind], None
    else:
        badge, badge_note = source_badge(types.get(e.source_id), ui_cfg)
    section, text = chunks.get(e.evidence_id, (None, None))
    return CitationView(
        evidence_id=e.evidence_id, kind=e.kind, badge=badge, badge_note=badge_note, source_title=e.source_title,
        page_text=page_text(e), page=e.page, period=e.period, basis=e.basis, accounting_standard=e.accounting_standard,
        verified=e.verified, note=e.note, section=section, chunk_text=text, formula=e.formula,
        input_evidence_ids=e.input_evidence_ids, reported_value=(reported or {}).get(e.evidence_id))


# ---------- calculation paths ----------

def _money(value: float, unit: str, display: dict) -> str:
    return format_number(value, unit, display)


def _pct(rate: float, display: dict) -> str:
    return format_number(rate * 100, "PERCENT", display)


def ratio_path(r: ToolResult, by_id: dict[str, CitationView], display: dict) -> RatioPath:
    d = r.detail
    calc_id = f"calc:{d['computed_id']}"
    inputs = []
    for i in d["inputs"]:
        f = i["fact"]
        eid = f"fact:{f['fact_id']}"
        inputs.append(CalcInput(role=i["role"], label=f"{f['metric_id']} [{f['period_label']}]",
                                display=format_number(f["value"], f["unit"], display), citation=by_id[eid]))
    result = next(n.display for n in r.numbers if n.evidence_id == calc_id)
    definition = next((x.removeprefix("Definition: ") for x in r.notes if x.startswith("Definition: ")), None)
    return RatioPath(evidence_id=calc_id, title=f"{d['display_name']}, {d['period_label']} ({d['basis']})",
                     formula=d["formula"], formula_version=d["formula_version"], definition=definition,
                     inputs=inputs, result_display=result, verified=d["verified"])


def assumptions_status(path) -> str:
    """The '# STATUS:' line(s) from the top comment block of the assumptions file."""
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return f"Assumptions file {Path(path).name} not found, so its status line cannot be shown."
    status = []
    for line in lines:
        if not line.startswith("#"):
            break
        if line.lstrip("# ").upper().startswith("STATUS:"):
            status.append(line.lstrip("# ").strip())
    return " ".join(status) or f"No STATUS line in the header of {Path(path).name}."


def _show_value(v) -> str:
    return ", ".join(str(x) for x in v) if isinstance(v, list) else str(v)


def dcf_path(r: ToolResult, display: dict, assumptions_file, footer: str) -> DCFPath:
    d = r.detail
    money, shares, per_share = d["units"]["money"], d["units"].get("shares"), d["per_share_unit"]
    w, v = d["wacc_build"], d["valuation"]
    b = v["bridge"]
    fcff_rows = [{"Year": y["year"], "Revenue": _money(y["revenue"], money, display),
                  "Growth": _pct(y["revenue_growth"], display), "EBIT": _money(y["ebit"], money, display),
                  "EBIT margin": _pct(y["ebit_margin"], display), "Tax on EBIT": _money(y["taxes_on_ebit"], money, display),
                  "D&A": _money(y["da"], money, display), "Capex": _money(y["capex"], money, display),
                  "NWC increase": _money(y["nwc_increase"], money, display), "FCFF": _money(y["fcff"], money, display),
                  "Discount factor": f"{df:.4f}", "PV of FCFF": _money(pv, money, display)}
                 for y, df, pv in zip(d["fcff_build"], v["discount_factors"], v["pv_fcff"])]
    sensitivity = None
    if r.args.get("include_sensitivity"):
        g = d["sensitivity"]
        sensitivity = {"columns": ["WACC \\ terminal growth"] + [_pct(x, display) for x in g["growth_values"]],
                       "rows": [[_pct(wv, display)] + [format_number(c, per_share, display) if c is not None
                                                       else "undefined" for c in row]
                                for wv, row in zip(g["wacc_values"], g["value_per_share"])]}
    return DCFPath(
        evidence_id=f"dcf:{d['run_id']}", title=f"DCF run {d['run_id']}, scenario '{d['scenario']}'",
        status_line=assumptions_status(assumptions_file), scenario_label=d["label"],
        valuation_date=d["valuation_date"], formulas=DCF_FORMULAS,
        wacc_rows=[("Risk-free rate", _pct(w["risk_free_rate"], display)), ("Beta", f"{w['beta']:.2f}"),
                   ("Equity risk premium", _pct(w["equity_risk_premium"], display)),
                   ("Cost of equity", _pct(w["cost_of_equity"], display)),
                   ("Debt weight", _pct(w["debt_weight"], display)),
                   ("Cost of debt after tax", _pct(w["cost_of_debt_after_tax"], display)),
                   ("WACC", _pct(w["wacc"], display))],
        fcff_rows=fcff_rows,
        valuation_rows=[("Sum of PV of FCFF", _money(v["sum_pv_fcff"], money, display)),
                        ("Terminal growth", _pct(v["terminal_growth"], display)),
                        ("Terminal value (end of last forecast year)", _money(v["terminal_value"], money, display)),
                        ("PV of terminal value", _money(v["pv_terminal_value"], money, display)),
                        ("Enterprise value", _money(v["enterprise_value"], money, display)),
                        ("PV of terminal value as share of EV", _pct(v["tv_share_of_ev"], display)
                         if v["tv_share_of_ev"] is not None else "not defined (EV not positive)")],
        bridge_rows=[("Enterprise value", _money(b["enterprise_value"], money, display)),
                     ("+ Cash and investments", _money(b["cash_and_investments"], money, display)),
                     ("- Debt", _money(b["debt"], money, display)),
                     ("- Lease liabilities", _money(b["lease_liabilities"], money, display)),
                     ("- Minority interest", _money(b["minority_interest"], money, display)),
                     ("= Equity value", _money(b["equity_value"], money, display)),
                     ("Diluted shares", format_number(b["diluted_shares"], shares, display) if shares
                      else str(b["diluted_shares"])),
                     ("Value per share", format_number(b["value_per_share"], per_share, display))],
        sensitivity=sensitivity,
        assumptions=[Assumption(name=k, value=_show_value(a["value"]), rationale=a["rationale"], source=a["source"],
                                defined_in=a["defined_in"]) for k, a in d["assumptions"].items()],
        checks=[(c["check_id"], c["status"], c["detail"]) for c in d["checks"]],
        disclaimer=d["disclaimer"], footer=footer)


# ---------- verification ----------

def verification_view(a: Answer) -> VerificationView:
    rep = a.verification
    issues = [(i.severity, i.check, i.span, i.message) for i in rep.issues] if rep else []
    fallback = a.composed_by == "template"
    if a.composed_by == "refusal":
        status = "Refused before an answer was written; the verifier did not run."
    elif fallback and rep is not None and not rep.ok:
        status = ("The verifier rejected the model's text. The answer shown was written by code from the "
                  "tool results instead (code-built fallback).")
    elif fallback:
        status = "The model's reply could not be used. The answer shown was written by code from the tool results."
    elif rep is None:
        status = "No verifier report recorded for this answer."
    elif not rep.ok:
        status = ("The verifier found errors but the text was shipped anyway (verifier switched off for the "
                  "eval ablation). Do not rely on this answer.")
    elif issues:
        status = "The verifier passed the model's text, with warnings."
    else:
        status = "The verifier passed the model's text with no issues."
    return VerificationView(status=status, fallback_used=fallback, report_ok=rep.ok if rep else None,
                            issues=issues, warnings=a.warnings)


# ---------- the whole answer ----------

def build_view(a: Answer, *, display: dict, ui_cfg: dict, assumptions_file, dcf_footer: str) -> AnswerView:
    types = doc_types(a.tool_results)
    chunks = _chunk_texts(a.tool_results)
    reported = reported_values(a.tool_results)
    all_evidence = {e.evidence_id: e for r in a.tool_results for e in r.evidence}
    all_evidence.update({e.evidence_id: e for e in a.citations})
    by_id = {eid: citation_view(e, types, chunks, ui_cfg, reported) for eid, e in all_evidence.items()}

    number_claims = []
    for n in a.numbers_used:
        c = by_id.get(n.evidence_id)
        inputs = [by_id[i] for i in (c.input_evidence_ids if c else []) if i in by_id]
        number_claims.append(NumberClaim(label=n.label, display=n.display, period=n.period, basis=n.basis,
                                         citation=c, inputs=inputs))
    ok = [r for r in a.tool_results if r.ok and r.detail]
    passages_note = None
    if a.composed_by == "template":
        passages_note = "Listed by code: the passages retrieved for this question (the answer quotes from them)."
    elif any(w.startswith("composer cited no passage") for w in a.warnings):
        passages_note = ("The model cited no passage, so every retrieved passage is listed. "
                         "They may not support the answer.")
    return AnswerView(
        question=a.question, refused=a.refused, refusal_reason=a.refusal_reason, answer_text=a.answer_text,
        composed_by=a.composed_by, model=a.model, number_claims=number_claims,
        passage_claims=[by_id[e.evidence_id] for e in a.citations if e.kind == "doc_chunk"],
        passages_note=passages_note,
        citations=[by_id[e.evidence_id] for e in a.citations],
        ratio_paths=[ratio_path(r, by_id, display) for r in ok if r.tool == "compute_ratio"],
        dcf_paths=[dcf_path(r, display, assumptions_file, dcf_footer) for r in ok if r.tool == "run_dcf"],
        limitations=a.limitations, verification=verification_view(a))


# ---------- M8.1: chips, answer badge, step cards, page-preview targets, example questions ----------

CHIP_COLOURS = {FILING: "blue", AUTHORS_NOTE: "violet"}   # every other badge is grey


def chip_colour(badge: str) -> str:
    return CHIP_COLOURS.get(badge, "gray")


def chip_text(c: CitationView) -> str:
    """'Filing · <document> · PDF p.167 (printed p.197)': what a citation chip says."""
    return " · ".join(x for x in (c.badge, c.source_title, c.page_text) if x)


def answer_badge(view: AnswerView) -> tuple[str, str]:
    """(text, colour) of the badge above an answer: who wrote it and whether the verifier passed it."""
    v = view.verification
    if view.refused or view.composed_by == "refusal":
        return "Refused by code", "gray"
    if v.fallback_used:
        return "Code-built fallback answer", "orange"
    if v.report_ok is None:
        return "No verifier ran", "red"
    if not v.report_ok:
        return "Verifier found errors (verifier switched off)", "red"
    if v.issues:
        return "Checked by verifier (with warnings)", "green"
    return "Checked by verifier", "green"


class Step(BaseModel):
    title: str
    lines: list[str]


def ratio_steps(p: RatioPath) -> list[Step]:
    """A ratio's calculation path as three cards: inputs (with pages), formula, result."""
    inputs = [f"{i.role}: {i.label} = {i.display} ({i.citation.source_title}, {i.citation.page_text or 'no page'})"
              for i in p.inputs]
    formula = [f"{p.formula} ({p.formula_version})"] + ([p.definition] if p.definition else [])
    return [Step(title="Inputs", lines=inputs), Step(title="Formula", lines=formula),
            Step(title="Result", lines=[p.result_display])]


class PreviewTarget(BaseModel):
    """A cited page that the source page preview can show, with the text to look for on it."""
    evidence_id: str
    kind: str                         # fact / doc_chunk
    label: str                        # what the picker shows
    source_title: str
    page: int
    needles: list[str]                # strings to highlight, best first


def preview_targets(view: AnswerView) -> list[PreviewTarget]:
    """Every cited fact (including ratio inputs) and passage that has a PDF page, each once."""
    from erp.ui.page_preview import number_needles, passage_needles

    out, seen = [], set()

    def add(c: CitationView | None, label: str):
        if c is None or c.evidence_id in seen or c.page is None or c.kind not in ("fact", "doc_chunk"):
            return
        needles = (number_needles(c.reported_value) if c.kind == "fact" and c.reported_value is not None
                   else passage_needles(c.chunk_text or ""))
        seen.add(c.evidence_id)
        out.append(PreviewTarget(evidence_id=c.evidence_id, kind=c.kind, label=f"{label} · {chip_text(c)}",
                                 source_title=c.source_title, page=c.page, needles=needles))
    for n in view.number_claims:
        add(n.citation, n.label)
        for i in n.inputs:
            add(i, f"input to {n.label}")
    for c in view.passage_claims:
        add(c, f"passage{', ' + c.section if c.section else ''}")
    return out


class ExampleQuestion(BaseModel):
    kind: str                         # e.g. "A fact"
    question_id: str
    question: str


def example_questions(ui_cfg: dict, questions_path) -> list[ExampleQuestion]:
    """The one-click examples (config/ui.yaml `examples`), with their text read from the question file."""
    texts = {}
    for line in Path(questions_path).read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            texts[row["id"]] = row["question"]
    return [ExampleQuestion(kind=e["kind"], question_id=e["question_id"], question=texts[e["question_id"]])
            for e in ui_cfg.get("examples", []) if e["question_id"] in texts]
