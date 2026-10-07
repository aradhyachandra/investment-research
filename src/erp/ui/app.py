"""Streamlit page (M8, polished in M8.1): ask a question, see the answer, every figure's source page, and
how it was computed; plus a company snapshot, the DCF, how the system works, and the eval results.

Run (from the repo root):
    .venv/bin/streamlit run app/streamlit_app.py                 # live: calls the agent (needs Ollama)
    .venv/bin/streamlit run app/streamlit_app.py -- --demo       # saved answers, no model

Plain Streamlit plus Altair charts. No custom JavaScript, no raw HTML. All display records come from
view_model.py, snapshot.py, dcf_view.py and eval_view.py; this file only lays them out. The snapshot and
DCF tabs call the deterministic tools (no LLM) on an in-memory copy of the database. PDFs are never copied
into the app: the source page preview renders a page from data/raw/ in memory, if the file is there.
"""
import argparse
import re
from pathlib import Path
from typing import Callable

import pandas as pd
import streamlit as st

from erp.agent.answer_schema import Answer
from erp.agent.llm import load_agent_config
from erp.config import REPO
from erp.ui import charts, page_preview
from erp.ui.dcf_view import DCFTabView, build_dcf_tab
from erp.ui.demo import DemoError, load_saved_answers, resolve_run
from erp.ui.eval_view import latest_results, readme_caveats
from erp.ui.snapshot import SnapshotError, build_snapshot, env_for, readonly_copy, snapshot_targets
from erp.ui.view_model import (
    AnswerView,
    CitationView,
    DCFPath,
    PreviewTarget,
    RatioPath,
    Step,
    answer_badge,
    build_view,
    chip_colour,
    example_questions,
    load_ui_config,
    preview_targets,
    ratio_steps,
)

QUESTIONS_FILE = REPO / "eval" / "questions.jsonl"
COMPANY_CONFIG_DIR = REPO / "config" / "companies"
BUILD_DB_HINT = ("PYTHONPATH=src .venv/bin/python -m erp.db.load_facts --csv data/sample/facts_sample.csv "
                 "--entry-method llm_extracted --replace")


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
    return f":{chip_colour(label)}-badge[{md_escape(label)}]"


def citation_line(c: CitationView) -> str:
    """Badge, a coloured chip with document and page, then period, basis, checked or not, evidence id."""
    where = " · ".join(md_escape(x) for x in (c.source_title, c.page_text) if x)
    parts = [badge(c.badge), f":{chip_colour(c.badge)}-badge[:material/description: {where}]"]
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
    elif c.verified:
        parts.append(":green[:material/check_circle: checked by a human]")
    parts.append(f"`{c.evidence_id}`")
    line = " · ".join(parts[:2]) + "  \n" + " · ".join(parts[2:])
    if c.badge_note:
        line += f"  \n:gray[{md_escape(c.badge_note)}]"
    return line


def step_cards(steps: list[Step]) -> None:
    """Calculation path as numbered cards side by side."""
    for n, (col, s) in enumerate(zip(st.columns(len(steps)), steps), 1):
        with col.container(border=True):
            st.markdown(f"**{n} · {md_escape(s.title)}**")
            st.markdown("\n".join(f"- {md_escape(x)}" for x in s.lines))


def dcf_footer(text: str) -> None:
    """The fixed DCF footer, shown next to every DCF figure."""
    st.caption(f":material/info: {md_escape(text)}")


# ---------- header ----------

def show_header(ui_cfg: dict) -> None:
    h = ui_cfg["header"]
    st.title(h["title"])
    st.markdown(f"**{md_escape(h['scope'])}**  \n:gray[*{md_escape(h['tagline'])}*]")
    show_disclaimer(ui_cfg)


def show_disclaimer(ui_cfg: dict) -> None:
    st.info(ui_cfg["disclaimer"], icon=":material/gavel:")


# ---------- source page preview ----------

@st.cache_data(show_spinner=False, max_entries=32)
def _render(path: str, mtime: float, page: int, needles: tuple[str, ...]) -> tuple[bytes, list[str], str]:
    out = page_preview.render_page(path, page, list(needles))
    return out.png, out.found, out.note


def show_page_preview(targets: list[PreviewTarget], ui_cfg: dict, key: str) -> None:
    st.subheader("Source page")
    if not targets:
        st.caption("No cited figure or passage with a PDF page in this answer.")
        return
    choice = st.selectbox("Cited page", range(len(targets)), format_func=lambda i: targets[i].label, key=key)
    t = targets[choice]
    files = page_preview.source_files(COMPANY_CONFIG_DIR / f"{ui_cfg.get('ticker', 'tcs').lower()}.yaml")
    path, why = page_preview.pdf_for_title(t.source_title, files, REPO / ui_cfg.get("raw_dir", "data/raw"))
    if path is None:
        st.info(why, icon=":material/folder_off:")
        return
    try:
        png, found, note = _render(str(path), path.stat().st_mtime, t.page, tuple(t.needles))
    except page_preview.PreviewError as e:
        st.warning(str(e))
        return
    st.caption(md_escape(note) + " Rendered from the local PDF; no copy is kept.")
    st.image(png, caption=f"{t.source_title}, PDF p.{t.page}", width=820)


# ---------- answer sections ----------

def show_number_claims(view: AnswerView) -> None:
    dcf = view.dcf_paths[0] if view.dcf_paths else None
    st.subheader("Figures in the answer")
    if not view.number_claims:
        st.caption("No figures from the database or the DCF model in this answer.")
    for n in view.number_claims:
        # Tool labels usually name the period and basis already; add them only when they are missing.
        where = ", ".join(x for x in (n.period, n.basis) if x and x not in n.label)
        with st.container(border=True):
            st.markdown(f"#### {md_escape(n.display)}\n{md_escape(n.label)}" + (f" ({md_escape(where)})" if where else ""))
            if n.citation is None:
                st.error("This figure points at evidence the answer does not list. Treat it as unsourced.")
                continue
            st.markdown(citation_line(n.citation))
            if n.citation.kind == "dcf_run" and dcf is not None:
                st.caption(f":material/warning: {md_escape(dcf.status_line)}")
                dcf_footer(dcf.footer)
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
        step_cards(ratio_steps(p))
        st.markdown("**Inputs in full**")
        st.markdown(md_table(["Role", "Figure", "Value", "Evidence", "Source", "Page", "Checked by a human"],
                             [[i.role, i.label, i.display, i.citation.evidence_id, i.citation.source_title,
                               i.citation.page_text or "", "yes" if i.citation.verified else "no"] for i in p.inputs]))
        st.markdown(f"**Formula** (`{p.formula_version}`): `{p.formula}`")
        if p.definition:
            st.caption(f"Definition: {p.definition}")
        st.markdown(f"**Result**: {md_escape(p.result_display)} (`{p.evidence_id}`)")
        if not p.verified:
            st.caption("At least one input has not been checked by a human, so this result is not verified.")


def dcf_steps(p: DCFPath) -> list[Step]:
    wacc = dict(p.wacc_rows)
    valuation, bridge = dict(p.valuation_rows), dict(p.bridge_rows)
    return [
        Step(title="Discount rate", lines=[f"Cost of equity {wacc['Cost of equity']}", f"WACC {wacc['WACC']}"]),
        Step(title="Cash flows", lines=[f"Sum of PV of FCFF {valuation['Sum of PV of FCFF']}",
                                        f"PV of terminal value {valuation['PV of terminal value']}",
                                        f"Enterprise value {valuation['Enterprise value']}"]),
        Step(title="Bridge to equity", lines=[f"Equity value {bridge['= Equity value']}",
                                              f"Diluted shares {bridge['Diluted shares']}",
                                              f"Value per share {bridge['Value per share']}"]),
    ]


def show_dcf_path(p: DCFPath) -> None:
    with st.expander(f"Calculation path: {p.title}"):
        st.warning(f"Assumptions status: {p.status_line}")
        st.markdown(f"**Scenario**: {md_escape(p.scenario_label)} · **valuation date** {p.valuation_date} · `{p.evidence_id}`")
        step_cards(dcf_steps(p))
        dcf_footer(p.footer)
        show_dcf_tables(p)


def show_dcf_tables(p: DCFPath) -> None:
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
    text, colour = answer_badge(view)
    st.markdown(f"**Question:** {md_escape(view.question)}")
    st.markdown(f":{colour}-badge[{text}]" + (f" :gray-badge[model {md_escape(view.model)}]" if view.model else ""))
    if view.refused:
        st.warning(md_escape(f"Refused ({view.refusal_reason}). {view.answer_text}").replace("\n", "  \n"))
        st.caption(written_by(view))
        if view.limitations:
            st.markdown("\n".join(f"- {md_escape(x)}" for x in view.limitations))
        show_verification(view)
        return

    st.subheader("Answer")
    with st.container(border=True):
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
    show_page_preview(preview_targets(view), ui_cfg, key="answer_page")
    show_all_citations(view)


# ---------- Ask tab ----------

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


def demo_ask(run_dir, system: str, ui_cfg: dict) -> Answer | None:
    try:
        run = resolve_run(run_dir)
        saved = load_saved_answers(run, system)
    except DemoError as e:
        st.error(f"Demo mode: {e}")
        return None
    if not saved:
        return None
    st.sidebar.markdown(f"**Demo mode**: saved answers, no model is called.  \nRun: `{run.name}` · system: `{system}`")
    if system != "full":
        st.sidebar.warning(f"System '{system}' is an eval comparison arm, not the full system.")
    st.caption("Demo mode: saved answers from an eval run; no model is called. Pick an example below or any "
               "saved question in the sidebar.")
    index = {s.question_id: i for i, s in enumerate(saved)}
    examples = [e for e in ui_cfg.get("examples", []) if e["question_id"] in index]

    def pick(i):
        st.session_state["demo_choice"] = i
    for col, e in zip(st.columns(max(len(examples), 1)), examples):
        col.button(e["kind"], key=f"ex_{e['question_id']}", on_click=pick, args=(index[e["question_id"]],),
                   help=saved[index[e["question_id"]]].answer.question, width="stretch")
    # A radio list, not a dropdown: one click picks a question.
    choice = st.sidebar.radio("Saved question", range(len(saved)), key="demo_choice",
                              format_func=lambda i: f"{saved[i].question_id}: {saved[i].answer.question}")
    return saved[choice].answer


def live_ask(answer_fn: Callable[[str], Answer], ui_cfg: dict) -> Answer | None:
    with st.form("ask"):
        question = st.text_input("Question about TCS", placeholder="What was TCS's net margin in FY26?")
        asked = st.form_submit_button("Ask", type="primary")
    try:
        examples = example_questions(ui_cfg, QUESTIONS_FILE)
    except OSError:
        examples = []
    clicked = None
    if examples:
        st.caption("Or try an example:")
        for col, e in zip(st.columns(len(examples)), examples):
            if col.button(e.kind, key=f"ex_{e.question_id}", help=e.question, width="stretch"):
                clicked = e.question
    to_ask = clicked or (question.strip() if asked else None)
    if to_ask:
        with st.spinner("Answering (routing, tools, verifier)..."):
            st.session_state["answer"] = answer_fn(to_ask)
    return st.session_state.get("answer")


# ---------- Company snapshot tab ----------

@st.cache_data(show_spinner=False)
def _snapshot(db_path: str, mtime: float, ui_cfg: dict, agent_cfg: dict):
    conn = readonly_copy(db_path)
    try:
        env = env_for(conn, agent_cfg)
        return build_snapshot(env, ui_cfg["snapshot"], ui_cfg)
    finally:
        conn.close()


def snapshot_tab(db_path: Path, ui_cfg: dict, agent_cfg: dict) -> None:
    cfg = ui_cfg["snapshot"]
    st.subheader(f"{cfg['period']} at a glance")
    st.caption(f"Statutory figures, {cfg.get('basis', 'consolidated')}, from the database through the same tools the "
               f"agent uses. {cfg['compare_period']} shown for comparison. Nothing on this tab is typed in.")
    if not db_path.is_file():
        st.info(f"No database at `{db_path.relative_to(REPO) if db_path.is_relative_to(REPO) else db_path}`. "
                f"Build the sample database first:\n\n`{BUILD_DB_HINT}`", icon=":material/database:")
        return
    try:
        cards = _snapshot(str(db_path), db_path.stat().st_mtime, ui_cfg, agent_cfg)
    except SnapshotError as e:
        st.error(str(e))
        return
    cols = [c for _ in range(0, len(cards), 2) for c in st.columns(2)]   # two cards per row: values never truncate
    for col, card in zip(cols, cards):
        with col.container(border=True):
            if card.current is None:
                st.markdown(f"**{md_escape(card.label)}**")
                st.warning(f"Not available: {card.error}")
                continue
            st.metric(f"{card.label} · {card.period}", card.current,
                      delta=f"{card.compare_period}: {card.compare}" if card.compare else None,
                      delta_color="off", delta_arrow="off")
            if card.change:
                st.caption(f"{md_escape(card.change)} (code-computed)")
            chips = dict.fromkeys((c.badge, c.page_text or "no page") for c in card.citations)  # each page once
            st.markdown(" ".join(f":{chip_colour(b)}-badge[{md_escape(b)}] :{chip_colour(b)}-badge[{md_escape(page)}]"
                                 for b, page in chips))
            if card.verified_by:
                st.markdown(f":green-badge[:material/verified: verified by {md_escape(card.verified_by)}]")
                st.caption(md_escape(card.verified_line.removeprefix(f"Verified by {card.verified_by} ")))
            else:
                st.markdown(f":orange-badge[{md_escape(card.verified_line)}]")
            if card.error:
                st.caption(md_escape(card.error))
    titles = sorted({c.source_title for card in cards for c in card.citations})
    if titles:
        st.caption("Source: " + "; ".join(md_escape(t) for t in titles) + ". Verification is read from the "
                   "database's verified_by field.")
    show_page_preview(snapshot_targets(cards), ui_cfg, key="snapshot_page")


# ---------- DCF tab ----------

@st.cache_data(show_spinner=False)
def _dcf(db_path: str, db_mtime: float, assumptions: str, a_mtime: float, ui_cfg: dict, agent_cfg: dict) -> DCFTabView:
    conn = readonly_copy(db_path)       # run_dcf logs a dcf_run row: keep it off the file
    try:
        env = env_for(conn, agent_cfg).model_copy(update={"dcf_assumptions": Path(assumptions)})
        return build_dcf_tab(env, ui_cfg["dcf"]["scenarios"], base=ui_cfg["dcf"]["base"], assumptions_file=assumptions,
                             footer=" ".join(agent_cfg["dcf_footer"].split()))
    finally:
        conn.close()


def dcf_tab(db_path: Path, ui_cfg: dict, agent_cfg: dict) -> None:
    assumptions = REPO / agent_cfg["tools"]["dcf_assumptions"]
    footer = " ".join(agent_cfg["dcf_footer"].split())
    if not db_path.is_file():
        st.info(f"No database, so the DCF cannot run. Build it first:\n\n`{BUILD_DB_HINT}`", icon=":material/database:")
        return
    a_mtime = assumptions.stat().st_mtime if assumptions.is_file() else 0.0
    v = _dcf(str(db_path), db_path.stat().st_mtime, str(assumptions), a_mtime, ui_cfg, agent_cfg)
    for e in v.errors:
        st.error(e)
    if v.base is None:
        return
    p = v.base
    st.warning(p.status_line, icon=":material/warning:")
    st.caption(f"Scenario set: {md_escape(p.scenario_label)} · valuation date {p.valuation_date}. "
               "These are what the stated assumptions imply, computed by the DCF engine; not a forecast.")

    left, right = st.columns(2)
    with left:
        st.markdown("**Value per share implied by each scenario's assumptions**")
        st.altair_chart(charts.scenario_chart(v.scenarios), width="stretch")
        dcf_footer(footer)
    with right:
        st.markdown(f"**Sensitivity of the {ui_cfg['dcf']['base']} scenario's value per share** "
                    "(rows: WACC, columns: terminal growth; outlined: the scenario's own inputs)")
        st.altair_chart(charts.heatmap_chart(v.heatmap), width="stretch")
        dcf_footer(footer)

    st.markdown("**From enterprise value to equity value**")
    st.altair_chart(charts.waterfall_chart(v.waterfall, f"{v.base_detail['units']['money'].replace('_', ' ')}"),
                    width="stretch")
    bridge = dict(p.bridge_rows)
    st.caption(f"Equity value {bridge['= Equity value']} ÷ diluted shares {bridge['Diluted shares']} = "
               f"value per share {bridge['Value per share']} (engine output).")
    dcf_footer(footer)

    st.markdown("**Assumptions** (base scenario; values as written in the assumptions file, rates are decimals)")
    st.dataframe(pd.DataFrame([{"Assumption": a.name, "Value": a.value, "Rationale": a.rationale, "Source": a.source,
                                "Defined in": a.defined_in} for a in p.assumptions]),
                 hide_index=True, width="stretch",
                 column_config={"Rationale": st.column_config.TextColumn(width="large")})
    st.caption("Bear and bull override some of these; see `data/manual/dcf_inputs.yaml`.")
    with st.expander("Full calculation path (base scenario)"):
        show_dcf_tables(p)


# ---------- How it works tab ----------

FLOW_DOT = """
digraph {
  rankdir=LR; bgcolor="transparent"; nodesep=0.35; ranksep=0.35;
  node [shape=box, style="rounded,filled", fillcolor="#f0efec", color="#d9d8d3", fontname="sans-serif",
        fontsize=16, margin="0.20,0.12"];
  edge [color="#8a8984", arrowsize=0.8];
  q [label="Question"];
  pre [label="Pre-check\\n(code)", fillcolor="#cde2fb", color="#86b6ef"];
  router [label="Router\\n(LLM)"];
  tools [label="Tools\\n(code)", fillcolor="#cde2fb", color="#86b6ef"];
  composer [label="Composer\\n(LLM)"];
  verifier [label="Verifier\\n(code)", fillcolor="#cde2fb", color="#86b6ef"];
  answer [label="Answer\\nwith sources", fillcolor="#2a78d6", fontcolor="white", color="#2a78d6"];
  refusal [label="Fixed refusal", fillcolor="#fbe3d9", color="#eb6834"];
  fallback [label="Code-built\\nanswer", fillcolor="#fbe3d9", color="#eb6834"];
  q -> pre -> router -> tools -> composer -> verifier -> answer;
  pre -> refusal [style=dashed, label=" out of scope", fontsize=13, fontcolor="#52514e"];
  verifier -> fallback [style=dashed, label=" rejected", fontsize=13, fontcolor="#52514e"];
  fallback -> answer [style=dashed];
}
"""

HOW_IT_WORKS = [
    "A question first meets a pre-check written in code, which refuses requests for advice or price predictions "
    "before any model runs.",
    "A small local language model then acts only as a router: it picks which tools to call and with which "
    "arguments, as structured JSON.",
    "The tools are plain Python: they read hand-checked figures from SQLite, compute ratios and the DCF with "
    "fixed formulas, and search the annual report, so every number has a document and page or a formula behind it.",
    "The model writes the answer from those tool results, and a code verifier checks that every figure in the text "
    "matches a tool result; if it does not, the model's text is replaced by an answer built by code.",
    "The model never does arithmetic: AI interprets, code calculates, sources prove.",
]


def how_it_works_tab() -> None:
    st.graphviz_chart(FLOW_DOT, width="stretch")
    for s in HOW_IT_WORKS:
        st.markdown(f"- {s}")
    st.caption("Light blue boxes are code with no model inside; grey boxes use the local LLM; dashed paths are the safety exits.")


# ---------- Evaluation tab ----------

def evaluation_tab() -> None:
    results = latest_results(REPO / "eval" / "results")
    if not results:
        st.info("No saved eval results in `eval/results/` (the folder is gitignored, so a fresh clone has none). "
                "Run `eval/run_eval.py` to produce them.", icon=":material/science:")
        return
    st.caption("Full system vs the naive-RAG baseline (same model, same search, no database, no tools, no verifier). "
               "Counts are \"k of n\"; bars show k ÷ n. n differs per row because each metric counts only the "
               "questions or claims it applies to.")
    for r in sorted(results, key=lambda r: r.split != "test"):
        title = "Test split (frozen, run once)" if r.split == "test" else "Dev split (used while building)"
        st.subheader(title)
        st.caption(f"Run `{r.run_name}` · model `{r.model}` · {r.questions} questions · git `{r.git_sha}`"
                   + (" · **dirty tree**: made from uncommitted code" if r.dirty else " · committed code"))
        st.altair_chart(charts.eval_chart(r.rows), width="stretch")
        table = {}
        for row in r.rows:
            table.setdefault(row.metric, {"Metric": row.metric})[row.system] = row.text
        st.dataframe(pd.DataFrame(list(table.values())), hide_index=True, width="stretch")
        missing = [f"{x.system}: {x.metric} ({x.text})" for x in r.rows if x.share is None]
        if missing:
            st.caption("No bar where n is 0 or the row is missing: " + "; ".join(md_escape(m) for m in missing))
    caveats = readme_caveats(REPO / "README.md")
    st.markdown("**Read these with the README's caveats**")
    if caveats:
        st.markdown("\n".join(f"- {c}" for c in caveats))
    else:
        st.caption("Caveats not found in README.md; see README section 7.")


# ---------- page ----------

def parse_args(argv):
    p = argparse.ArgumentParser(description="TCS research UI")
    p.add_argument("--demo", nargs="?", const="", default=None, metavar="RUN_OR_RESULTS_DIR",
                   help="show saved answers (default: newest run in config/ui.yaml demo.results_dir)")
    p.add_argument("--system", default=None, help="saved system to show in demo mode (default from config)")
    p.add_argument("--db", default=None, help="SQLite database for live mode and the snapshot/DCF tabs")
    return p.parse_args(argv)


TABS = ["Ask", "Company snapshot", "DCF", "How it works", "Evaluation"]


def main(argv=None, *, answer_fn: Callable[[str], Answer] | None = None) -> None:
    args = parse_args(argv or [])
    ui_cfg, agent_cfg = load_ui_config(), load_agent_config()
    st.set_page_config(page_title=ui_cfg["header"]["title"], page_icon=":material/query_stats:", layout="wide")
    show_header(ui_cfg)
    db_path = REPO / (args.db or ui_cfg["db_path"])
    ask, snap, dcf, how, evals = st.tabs(TABS)
    with ask:
        if args.demo is not None:
            answer = demo_ask(REPO / (args.demo or ui_cfg["demo"]["results_dir"]),
                              args.system or ui_cfg["demo"]["system"], ui_cfg)
        else:
            answer = live_ask(answer_fn or live_answer_fn(db_path), ui_cfg)
        if answer is not None:
            render_answer(answer, ui_cfg=ui_cfg, agent_cfg=agent_cfg)
    with snap:
        snapshot_tab(db_path, ui_cfg, agent_cfg)
    with dcf:
        dcf_tab(db_path, ui_cfg, agent_cfg)
    with how:
        how_it_works_tab()
    with evals:
        evaluation_tab()
    st.divider()
    st.caption(ui_cfg["disclaimer"])
