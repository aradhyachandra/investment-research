"""Streamlit page (M8): ask a question, see the answer, every figure's source page, and how it was computed.

Run (from the repo root):
    .venv/bin/streamlit run app/streamlit_app.py                 # live: calls the agent (needs Ollama)
    .venv/bin/streamlit run app/streamlit_app.py -- --demo       # saved answers, no model

Plain Streamlit, no custom JavaScript. All display records come from view_model.py; this file only
lays them out. PDFs are never copied into the app: a citation shows the PDF page number and the chunk
text the agent retrieved.
"""
import argparse
import re
from typing import Callable

import streamlit as st

from erp.agent.answer_schema import Answer
from erp.agent.llm import load_agent_config
from erp.config import REPO
from erp.ui.demo import DemoError, load_saved_answers, resolve_run
from erp.ui.view_model import (
    AUTHORS_NOTE,
    FILING,
    AnswerView,
    CitationView,
    DCFPath,
    RatioPath,
    build_view,
    load_ui_config,
)

BADGE_COLOURS = {FILING: "blue", AUTHORS_NOTE: "violet"}   # everything else grey


# ---------- small helpers ----------

def md_escape(text: str) -> str:
    """Show text literally in st.markdown (PDF text has '$', '*', '#', '|' ...)."""
    return re.sub(r"([\\`*_\[\]$#<>|~])", r"\\\1", text)


def md_table(headers: list[str], rows: list[list]) -> str:
    def cell(x):
        return md_escape(str(x)).replace("\n", " ")
    lines = ["| " + " | ".join(cell(h) for h in headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(cell(x) for x in row) + " |" for row in rows]
    return "\n".join(lines)


def badge(label: str) -> str:
    return f":{BADGE_COLOURS.get(label, 'gray')}-badge[{md_escape(label)}]"


def citation_line(c: CitationView) -> str:
    """One line: badge, document, page, period, basis, checked or not, evidence id."""
    parts = [badge(c.badge), f"**{md_escape(c.source_title)}**"]
    if c.page_text:
        parts.append(f"**{c.page_text}**")
    if c.period:
        # A DCF run carries its valuation date in the period field, a chunk its document's period (tools.py).
        word = {"dcf_run": "valuation date", "doc_chunk": "document period"}.get(c.kind, "period")
        parts.append(f"{word} {md_escape(c.period)}")
    if c.basis:
        parts.append(md_escape(c.basis))
    if c.accounting_standard:
        parts.append(md_escape(c.accounting_standard))
    if c.verified is False:
        parts.append(":orange[not yet checked by a human]")
    parts.append(f"`{c.evidence_id}`")
    line = " · ".join(parts)
    if c.badge_note:
        line += f"  \n:gray[{md_escape(c.badge_note)}]"
    return line


# ---------- sections ----------

def show_disclaimer(ui_cfg: dict) -> None:
    st.info(ui_cfg["disclaimer"])


def show_number_claims(view: AnswerView) -> None:
    st.subheader("Figures in the answer")
    if not view.number_claims:
        st.caption("No figures from the database or the DCF model in this answer.")
    for n in view.number_claims:
        # Tool labels usually name the period and basis already; add them only when they are missing.
        where = ", ".join(x for x in (n.period, n.basis) if x and x not in n.label)
        st.markdown(f"**{md_escape(n.display)}**: {md_escape(n.label)}" + (f" ({md_escape(where)})" if where else ""))
        if n.citation is None:
            st.error("This figure points at evidence the answer does not list. Treat it as unsourced.")
            continue
        st.markdown(citation_line(n.citation))
        if n.citation.formula:
            st.markdown(f"Formula: `{n.citation.formula}`")
        for i in n.inputs:
            st.markdown("Input: " + citation_line(i))


def show_passage_claims(view: AnswerView) -> None:
    if not view.passage_claims:
        return
    st.subheader("Passages cited")
    if view.passages_note:
        st.caption(view.passages_note)
    for c in view.passage_claims:
        st.markdown(citation_line(c))
        with st.expander(f"Text of {c.page_text or 'this passage'}" + (f", {c.section}" if c.section else "")):
            st.markdown(md_escape(c.chunk_text).replace("\n", "  \n") if c.chunk_text
                        else "_Chunk text not stored in this answer._")


def show_ratio_path(p: RatioPath) -> None:
    with st.expander(f"Calculation path: {p.title}"):
        st.markdown("**Inputs**")
        st.markdown(md_table(["Role", "Figure", "Value", "Evidence", "Source", "Page", "Checked by a human"],
                             [[i.role, i.label, i.display, i.citation.evidence_id, i.citation.source_title,
                               i.citation.page_text or "", "yes" if i.citation.verified else "no"] for i in p.inputs]))
        st.markdown(f"**Formula** (`{p.formula_version}`): `{p.formula}`")
        if p.definition:
            st.caption(f"Definition: {p.definition}")
        st.markdown(f"**Result**: {md_escape(p.result_display)} (`{p.evidence_id}`)")
        if not p.verified:
            st.caption("At least one input has not been checked by a human, so this result is not verified.")


def show_dcf_path(p: DCFPath) -> None:
    with st.expander(f"Calculation path: {p.title}"):
        st.warning(f"Assumptions status: {p.status_line}")
        st.markdown(f"**Scenario**: {md_escape(p.scenario_label)} · **valuation date** {p.valuation_date} · `{p.evidence_id}`")
        st.markdown("**Formulas**\n" + "\n".join(f"- {md_escape(f)}" for f in p.formulas))
        st.markdown("**Discount rate**")
        st.markdown(md_table(["Item", "Value"], p.wacc_rows))
        st.markdown("**Forecast free cash flow**")
        st.markdown(md_table(list(p.fcff_rows[0]), [list(r.values()) for r in p.fcff_rows]))
        st.markdown("**Terminal value and enterprise value**")
        st.markdown(md_table(["Item", "Value"], p.valuation_rows))
        st.markdown("**Enterprise value to equity value**")
        st.markdown(md_table(["Item", "Value"], p.bridge_rows))
        if p.sensitivity:
            st.markdown("**Sensitivity: value per share by WACC and terminal growth**")
            st.markdown(md_table(p.sensitivity["columns"], p.sensitivity["rows"]))
        st.markdown("**Key assumptions** (values as written in the assumptions file; rates are decimals)")
        st.markdown(md_table(["Assumption", "Value", "Rationale", "Source", "Defined in"],
                             [[a.name, a.value, a.rationale, a.source, a.defined_in] for a in p.assumptions]))
        st.markdown("**Sanity checks**")
        st.markdown(md_table(["Check", "Status", "Detail"], p.checks))
        st.caption(md_escape(p.disclaimer))
        st.markdown(f"_{md_escape(p.footer)}_")


def show_verification(view: AnswerView) -> None:
    v = view.verification
    label = "Verifier: code-built fallback used" if v.fallback_used else "Verifier checks and warnings"
    with st.expander(label, expanded=False):
        st.markdown(md_escape(v.status))
        if v.issues:
            st.markdown(md_table(["Severity", "Check", "Words in the model's text", "Message"], v.issues))
        if v.warnings:
            st.markdown("**Warnings recorded by the agent**\n" + "\n".join(f"- {md_escape(w)}" for w in v.warnings))
        if not v.issues and not v.warnings:
            st.caption("Nothing recorded.")


def show_all_citations(view: AnswerView) -> None:
    if not view.citations:
        return
    with st.expander(f"All citations ({len(view.citations)})"):
        for c in view.citations:
            st.markdown(citation_line(c))


def written_by(view: AnswerView) -> str:
    if view.composed_by == "llm" and view.verification.status.startswith("No verifier report"):
        return f"Written by the model ({view.model or 'unknown model'}). No verifier ran on this answer."
    if view.composed_by == "llm" and not view.verification.status.startswith("The verifier passed"):
        return f"Written by the model ({view.model or 'unknown model'}). {view.verification.status}"
    if view.composed_by == "llm":
        n = len(view.verification.issues)
        return (f"Written by the model ({view.model or 'unknown model'}) from tool results. The verifier checked "
                "that its figures match the tool results; it does not check the wording or figures quoted from "
                "passages." + (f" It raised {n} warning(s): see the verifier box." if n else ""))
    if view.composed_by == "template":
        return ("Written by code from the tool results (code-built fallback): "
                + ("the verifier rejected the model's text." if view.verification.issues
                   else "the model's reply could not be used."))
    return "Refused by code with a fixed text."


def render_answer(answer: Answer, *, ui_cfg: dict, agent_cfg: dict) -> None:
    view = build_view(answer, display=agent_cfg["display"], ui_cfg=ui_cfg,
                      assumptions_file=REPO / agent_cfg["tools"]["dcf_assumptions"],
                      dcf_footer=" ".join(agent_cfg["dcf_footer"].split()))
    st.markdown(f"**Question:** {md_escape(view.question)}")
    if view.refused:
        st.warning(md_escape(f"Refused ({view.refusal_reason}). {view.answer_text}").replace("\n", "  \n"))
        st.caption(written_by(view))
        if view.limitations:
            st.markdown("\n".join(f"- {md_escape(x)}" for x in view.limitations))
        show_verification(view)
        return

    st.subheader("Answer")
    st.markdown(md_escape(view.answer_text).replace("\n", "  \n"))
    st.caption(written_by(view))
    if view.limitations:
        st.markdown("**Notes and limitations**\n" + "\n".join(f"- {md_escape(x)}" for x in view.limitations))
    show_verification(view)
    show_number_claims(view)
    show_passage_claims(view)
    if view.ratio_paths or view.dcf_paths:
        st.subheader("How the figures were computed")
        for p in view.ratio_paths:
            show_ratio_path(p)
        for p in view.dcf_paths:
            show_dcf_path(p)
    show_all_citations(view)


# ---------- modes ----------

def live_answer_fn(db_path) -> Callable[[str], Answer]:
    """Calls the real agent (and so Ollama). Opens a fresh connection per question: Streamlit may
    run each rerun on a different thread, and a sqlite3 connection is tied to its thread."""
    def answer(question: str) -> Answer:
        from erp.agent.loop import answer_question, open_env
        env = open_env(db_path)
        try:
            return answer_question(question, env)
        finally:
            env.conn.close()
    return answer


def demo_picker(run_dir, system: str) -> Answer | None:
    try:
        run = resolve_run(run_dir)
        saved = load_saved_answers(run, system)
    except DemoError as e:
        st.error(f"Demo mode: {e}")
        return None
    st.sidebar.markdown(f"**Demo mode**: saved answers, no model is called.  \nRun: `{run.name}` · system: `{system}`")
    if system != "full":
        st.sidebar.warning(f"System '{system}' is an eval comparison arm, not the full system.")
    # A radio list, not a dropdown: one click picks a question.
    choice = st.sidebar.radio("Saved question", range(len(saved)),
                                  format_func=lambda i: f"{saved[i].question_id}: {saved[i].answer.question}")
    return saved[choice].answer if saved else None


def live_box(answer_fn: Callable[[str], Answer]) -> Answer | None:
    with st.form("ask"):
        question = st.text_input("Question about TCS", placeholder="What was TCS's net margin in FY26?")
        asked = st.form_submit_button("Ask")
    if asked and question.strip():
        with st.spinner("Answering (routing, tools, verifier)..."):
            st.session_state["answer"] = answer_fn(question.strip())
    return st.session_state.get("answer")


def parse_args(argv):
    p = argparse.ArgumentParser(description="TCS research UI")
    p.add_argument("--demo", nargs="?", const="", default=None, metavar="RUN_OR_RESULTS_DIR",
                   help="show saved answers (default: newest run in config/ui.yaml demo.results_dir)")
    p.add_argument("--system", default=None, help="saved system to show in demo mode (default from config)")
    p.add_argument("--db", default=None, help="SQLite database for live mode (default from config)")
    return p.parse_args(argv)


def main(argv=None, *, answer_fn: Callable[[str], Answer] | None = None) -> None:
    args = parse_args(argv or [])
    ui_cfg, agent_cfg = load_ui_config(), load_agent_config()
    st.set_page_config(page_title="TCS research assistant", layout="wide")
    st.title("TCS research assistant")
    show_disclaimer(ui_cfg)
    if args.demo is not None:
        answer = demo_picker(REPO / (args.demo or ui_cfg["demo"]["results_dir"]),
                             args.system or ui_cfg["demo"]["system"])
    else:
        answer = live_box(answer_fn or live_answer_fn(REPO / (args.db or ui_cfg["db_path"])))
    if answer is not None:
        render_answer(answer, ui_cfg=ui_cfg, agent_cfg=agent_cfg)
    st.divider()
    st.caption(ui_cfg["disclaimer"])
