"""M8: Streamlit UI. No live model and no Ollama: answers come from the real pipeline driven by the
scripted fake LLM (tests/fakes.py), or are hand-built Answer objects.

Acceptance (plan Section 9): a reviewer can trace one number back to its source page in 3 clicks or
fewer. Checked here structurally: the source document and PDF page of every figure are on the page
with no click at all (not inside an expander); the chunk text is one click (an expander). The
manual walkthrough of 5 questions is the author's.
"""
import json
import re
from pathlib import Path

import pytest
import yaml
from streamlit.testing.v1 import AppTest

from erp.agent.answer_schema import Answer
from erp.agent.llm import load_agent_config
from erp.agent.loop import REFUSAL_TEXT, answer_question
from erp.agent.tools import Evidence, Passage, ToolEnv, ToolNumber, ToolResult
from erp.agent.verifier import VerifierIssue, VerifierReport
from erp.ingest.index_chroma import add_chunks, open_collection
from erp.ui import view_model as vm
from erp.ui.demo import DemoError, load_saved_answers, newest_run, resolve_run
from fakes import ScriptedLLM, fake_embed
from test_agent_tools import CHUNKS, DISPLAY
from test_dcf_run import TOY_YAML

REPO = Path(__file__).resolve().parent.parent
UI_SRC = REPO / "src" / "erp" / "ui"
AGENT_CFG = load_agent_config()
UI_CFG = vm.load_ui_config()
FOOTER = " ".join(AGENT_CFG["dcf_footer"].split())


# ---------- answers from the real pipeline, scripted LLM ----------

@pytest.fixture
def env(loaded, tmp_path):
    col = open_collection(tmp_path / "chroma", "test_docs")
    add_chunks(col, CHUNKS, embed_fn=fake_embed)
    toy = yaml.safe_load(TOY_YAML.read_text())
    toy["ticker"] = "TCS"          # toy numbers under the TCS ticker, only inside this test
    toy_path = tmp_path / "toy_as_tcs.yaml"
    toy_path.write_text("# STATUS: test fixture status line, toy numbers.\n" + yaml.safe_dump(toy))
    return ToolEnv(conn=loaded, ticker="TCS", display=DISPLAY, collection=col, embed_fn=fake_embed,
                   dcf_assumptions=toy_path)


def scripted(calls, question_type="numeric", refuse=False, reason="none", text=None):
    """Router returns `calls`; the composer writes every offered figure as displayed (or `text`)."""
    route = {"question_type": question_type, "refusal_reason": reason, "calls": calls}

    def reply(messages, schema):
        if "question_type" in schema["properties"]:
            return json.dumps({**route, "refuse": refuse} if refuse else route)
        props = schema["properties"]
        offered = lambda f: props[f].get("items", {}).get("enum", [])  # noqa: E731
        figures = re.findall(r"^- \[([^\]#]+)#[^\]]+\] ([^:\n]+): (.+)$", messages[-1]["content"], re.M)
        body = text or (" ".join(f"{label}: {shown} [{eid}]." for eid, label, shown in figures)
                        or "The filings describe this.")
        return json.dumps({"answer_text": body, "used_number_ids": offered("used_number_ids"),
                           "cited_evidence_ids": offered("cited_evidence_ids")})
    return ScriptedLLM(reply)


def view_of(a: Answer, assumptions_file=None):
    return vm.build_view(a, display=DISPLAY, ui_cfg=UI_CFG, assumptions_file=assumptions_file or TOY_YAML,
                         dcf_footer=FOOTER)


@pytest.fixture
def fact_answer(env):
    q = "What was TCS's consolidated revenue from operations in FY26?"
    return answer_question(q, env, scripted([{"tool": "get_financial_fact", "metric_id": "revenue_from_operations",
                                              "period": "FY26", "basis": "consolidated"}]))


@pytest.fixture
def ratio_answer(env):
    return answer_question("What was TCS's net margin in FY26?", env,
                           scripted([{"tool": "compute_ratio", "ratio_id": "net_margin", "period": "FY26",
                                      "basis": "consolidated"}]))


@pytest.fixture
def dcf_answer(env):
    return answer_question("What is the base-case DCF value per share?", env,
                           scripted([{"tool": "run_dcf", "scenario": "base", "include_sensitivity": True}],
                                    question_type="valuation"))


@pytest.fixture
def search_answer(env):
    return answer_question("What do the filings say about customer concentration?", env,
                           scripted([{"tool": "search_documents", "query": "single customer revenue"}],
                                    question_type="qualitative"))


# ---------- badges ----------

@pytest.mark.parametrize("doc_type,badge", [
    ("annual_report", vm.FILING), ("fact_sheet", vm.FILING), ("quarterly_results", vm.FILING),
    ("analyst_note", vm.AUTHORS_NOTE), ("generated_sample", vm.AUTHORS_NOTE),
    ("press_release", vm.OTHER_DOCUMENT), (None, vm.TYPE_NOT_RECORDED),
])
def test_source_badges(doc_type, badge):
    assert vm.source_badge(doc_type, UI_CFG)[0] == badge


def test_generated_sample_is_never_presented_as_written_by_the_author():
    badge, note = vm.source_badge("generated_sample", UI_CFG)
    assert badge == vm.AUTHORS_NOTE and "AI-generated" in note and "not written by the author" in note


def test_page_text_shows_pdf_index_and_printed_page():
    e = Evidence(evidence_id="fact:1", kind="fact", source_title="AR", page=167, page_label="197")
    assert vm.page_text(e) == "PDF p.167 (printed p.197)"
    assert vm.page_text(e.model_copy(update={"page_label": "167"})) == "PDF p.167"
    assert vm.page_text(e.model_copy(update={"page_end": 168, "page_label": None})) == "PDF p.167-168"
    assert vm.page_text(e.model_copy(update={"page": None})) is None


# ---------- claims and citations ----------

def test_fact_figure_carries_document_page_period_basis_and_filing_badge(fact_answer):
    v = view_of(fact_answer)
    assert not v.refused and len(v.number_claims) == 1
    n = v.number_claims[0]
    assert n.display == "INR 267,021 crore"
    c = n.citation
    assert c.badge == vm.FILING
    assert c.source_title == "TCS Integrated Annual Report 2025-26"
    assert c.page_text == "PDF p.167 (printed p.197)"
    assert (c.period, c.basis) == ("FY26", "consolidated")
    assert c.verified is False                      # sample facts are llm_extracted, unchecked


def test_ratio_figure_lists_its_input_facts_with_pages(ratio_answer):
    v = view_of(ratio_answer)
    ratio = next(n for n in v.number_claims if n.citation.kind == "calc")
    assert ratio.citation.badge == "Calculation" and ratio.citation.formula
    assert {i.evidence_id for i in ratio.inputs} == set(ratio.citation.input_evidence_ids)
    assert all(i.page_text and i.page_text.startswith("PDF p.") and i.badge == vm.FILING for i in ratio.inputs)


def test_ratio_calculation_path_has_inputs_formula_and_result(ratio_answer):
    v = view_of(ratio_answer)
    [p] = v.ratio_paths
    tool = next(r for r in ratio_answer.tool_results if r.tool == "compute_ratio")
    assert p.formula == tool.detail["formula"]
    assert p.result_display == tool.numbers[0].display        # the tool's own display string
    assert [i.role for i in p.inputs] == ["numerator", "denominator"]
    for i in p.inputs:
        assert i.citation.evidence_id.startswith("fact:") and i.citation.page_text
    assert p.definition and p.verified is False


def test_dcf_path_shows_assumptions_status_line_and_fixed_footer(dcf_answer, env):
    v = view_of(dcf_answer, assumptions_file=env.dcf_assumptions)
    [p] = v.dcf_paths
    assert p.status_line == "STATUS: test fixture status line, toy numbers."
    assert p.footer == FOOTER and FOOTER in dcf_answer.answer_text
    tool = next(r for r in dcf_answer.tool_results if r.tool == "run_dcf")
    names = {a.name for a in p.assumptions}
    assert names == set(tool.detail["assumptions"])
    assert all(a.rationale and a.source for a in p.assumptions)
    per_share = next(n.display for n in tool.numbers if n.number_id.endswith("#value_per_share"))
    assert ("Value per share", per_share) in p.bridge_rows       # same string as the tool's
    assert len(p.fcff_rows) == len(tool.detail["fcff_build"])
    assert p.sensitivity and len(p.sensitivity["rows"]) == len(tool.detail["sensitivity"]["wacc_values"])
    assert p.checks and p.formulas == vm.DCF_FORMULAS


def test_status_line_missing_or_file_missing_is_said_not_invented(tmp_path):
    f = tmp_path / "a.yaml"
    f.write_text("# just a comment\nticker: X\n# STATUS: below the header, ignored\n")
    assert vm.assumptions_status(f) == "No STATUS line in the header of a.yaml."
    assert "not found" in vm.assumptions_status(tmp_path / "missing.yaml")


def test_real_assumptions_header_states_ai_drafted_and_no_review():
    status = vm.assumptions_status(REPO / AGENT_CFG["tools"]["dcf_assumptions"])
    assert "NOT reviewed by a finance partner" in status


def test_passage_claims_show_chunk_text_and_page(search_answer):
    v = view_of(search_answer)
    assert v.passage_claims
    for c in v.passage_claims:
        assert c.badge == vm.FILING and c.page_text.startswith("PDF p.") and c.chunk_text and c.section
    assert v.passages_note is None                   # the scripted composer cites the passages
    texts = " ".join(c.chunk_text for c in v.passage_claims)
    assert "No single customer accounts for 10% or more of revenue." in texts


def _note_answer(doc_type: str) -> Answer:
    """A hand-built answer citing one chunk of a note (no author notes are indexed yet)."""
    ev = Evidence(evidence_id="chunk:n1", kind="doc_chunk", source_id=9, source_title="Notes on TCS", page=3)
    hit = {"chunk_id": "n1", "source_id": 9, "doc_type": doc_type, "text": "Full text of the note.",
           "section": "Risks"}
    r = ToolResult(tool="search_documents", args={"query": "risks"}, ok=True, evidence=[ev],
                   passages=[Passage(evidence_id="chunk:n1", section="Risks", text="Full text")],
                   detail={"results": [hit]})
    return Answer(question="What risks does the note list?", ticker="TCS", answer_text="The note lists risks.",
                  numbers_used=[], citations=[ev], refused=False, tool_results=[r], composed_by="llm",
                  verification=VerifierReport(ok=True))


@pytest.mark.parametrize("doc_type", ["analyst_note", "generated_sample"])
def test_author_note_badge_code_path(doc_type):
    [c] = view_of(_note_answer(doc_type)).passage_claims
    assert c.badge == vm.AUTHORS_NOTE and c.badge_note
    assert c.chunk_text == "Full text of the note."   # full hit text preferred over the cut passage


def test_unknown_source_type_is_not_called_a_filing():
    a = _note_answer("annual_report")
    a.tool_results[0].detail = None
    [c] = view_of(a).passage_claims
    assert c.badge == vm.TYPE_NOT_RECORDED
    assert c.chunk_text == "Full text"                # falls back to the composer's passage


# ---------- refusals and verifier ----------

def test_refusal_shows_the_fixed_text(env):
    a = answer_question("Should I buy TCS shares?", env, scripted([]))
    v = view_of(a)
    assert v.refused and v.answer_text == REFUSAL_TEXT["investment_advice"]
    assert not v.number_claims and not v.citations
    assert "did not run" in v.verification.status


def test_verifier_rejection_and_fallback_are_reported(env):
    # The composer writes a figure no tool returned: the verifier rejects it, code writes the answer.
    a = answer_question("What was TCS's revenue in FY26?", env,
                        scripted([{"tool": "get_financial_fact", "metric_id": "revenue_from_operations",
                                   "period": "FY26", "basis": "consolidated"}],
                                 text="Revenue was INR 999,999 crore in FY26."))
    assert a.composed_by == "template"
    v = view_of(a)
    assert v.verification.fallback_used and "rejected" in v.verification.status
    assert any(sev == "error" for sev, *_ in v.verification.issues)
    assert "999,999" not in v.answer_text
    assert v.passages_note is None or v.passages_note.startswith("Listed by code")


def test_uncited_passages_are_labelled_as_all_retrieved():
    a = _note_answer("annual_report")
    a.warnings = ["composer cited no passage; all passages it was given are attached"]
    assert "may not support the answer" in view_of(a).passages_note


def test_verifier_off_answer_with_errors_is_flagged():
    a = _note_answer("annual_report")
    a.verification = VerifierReport(ok=False, issues=[VerifierIssue(check="number_unsupported", severity="error",
                                                                    span="79", message="not a tool number")])
    assert "Do not rely on this answer" in view_of(a).verification.status


def test_caption_never_claims_a_check_that_did_not_happen(tmp_path):
    from erp.ui.app import written_by
    a = _note_answer("annual_report")
    a.verification = None                                  # e.g. the naive-RAG baseline
    assert "No verifier ran" in written_by(view_of(a))
    a.verification = VerifierReport(ok=False, issues=[VerifierIssue(check="x", severity="error", span="1",
                                                                    message="m")])
    assert "Do not rely on this answer" in written_by(view_of(a))
    a.verification = VerifierReport(ok=True)
    assert "does not check the wording" in written_by(view_of(a))


def test_number_pointing_at_missing_evidence_has_no_citation():
    a = _note_answer("annual_report")
    a.numbers_used = [ToolNumber(number_id="fact:404#value", label="x", value=1, unit="INR_CRORE",
                                 display="INR 1 crore", period="FY26", basis="consolidated", evidence_id="fact:404")]
    assert view_of(a).number_claims[0].citation is None


# ---------- demo loader ----------

def _write_run(folder: Path, answers: list[Answer], system="full"):
    folder.mkdir(parents=True)
    with open(folder / f"{system}.jsonl", "w") as f:
        for i, a in enumerate(answers):
            f.write(json.dumps({"question_id": f"EV-X{i:02d}", "question": a.question,
                                "answer": a.model_dump(mode="json")}) + "\n")


def test_demo_loads_saved_answers_from_the_newest_run(tmp_path, fact_answer, dcf_answer):
    _write_run(tmp_path / "20260101-000000_aaaa", [fact_answer])
    _write_run(tmp_path / "20260102-000000_bbbb", [fact_answer, dcf_answer])
    run = resolve_run(tmp_path)
    assert run.name == "20260102-000000_bbbb" and newest_run(tmp_path) == run
    saved = load_saved_answers(run)
    assert [s.question_id for s in saved] == ["EV-X00", "EV-X01"]
    assert saved[1].answer == dcf_answer
    assert resolve_run(tmp_path / "20260101-000000_aaaa").name == "20260101-000000_aaaa"


def test_demo_errors_are_clear(tmp_path):
    with pytest.raises(DemoError, match="no saved eval runs"):
        newest_run(tmp_path / "nothing")
    (tmp_path / "r").mkdir()
    (tmp_path / "r" / "full.jsonl").write_text('{"question_id": "Q1", "answer": {"oops": 1}}\n')
    with pytest.raises(DemoError, match="not a saved Answer"):
        load_saved_answers(tmp_path / "r")
    with pytest.raises(DemoError, match="naive_rag.jsonl not found"):
        load_saved_answers(tmp_path / "r", "naive_rag")


# ---------- the Streamlit page itself (headless AppTest, no browser, no model) ----------

def _page_with_answer(answer_json_path: str):
    """Script run by AppTest: live mode with a fake answer function that returns a saved Answer."""
    from pathlib import Path as _P

    from erp.agent.answer_schema import Answer as _A
    from erp.ui.app import main as _main
    saved = _A.model_validate_json(_P(answer_json_path).read_text())
    _main([], answer_fn=lambda q: saved.model_copy(update={"question": q}))


def run_page(tmp_path, answer: Answer, question="test question") -> AppTest:
    path = tmp_path / "answer.json"
    path.write_text(answer.model_dump_json())
    at = AppTest.from_function(_page_with_answer, args=(str(path),), default_timeout=30)
    at.run()
    assert not at.exception
    at.text_input[0].input(question)
    at.button[0].click()
    at.run()
    assert not at.exception, at.exception
    return at


def _top_level_markdown(at) -> str:
    """Markdown visible with no click: everything in the main area that is not inside an expander."""
    out = []

    def walk(node):
        if type(node).__name__ == "Expander":
            return
        if type(node).__name__ == "Markdown":
            out.append(node.value)
        for child in getattr(node, "children", {}).values():
            walk(child)
    walk(at.main)
    return "\n".join(out)


def test_page_traces_a_figure_to_its_page_without_clicks(tmp_path, ratio_answer):
    at = run_page(tmp_path, ratio_answer)
    shown = _top_level_markdown(at)
    ratio = next(n for n in ratio_answer.numbers_used if n.evidence_id.startswith("calc:"))
    assert ratio.display in shown
    # Every input fact's document and PDF page are visible outside any expander (0 clicks).
    for e in ratio_answer.citations:
        if e.kind == "fact":
            assert f"PDF p.{e.page} (printed p.{e.page_label})" in shown
            assert e.source_title in shown and f"`{e.evidence_id}`" in shown
    assert ":blue-badge[Filing]" in shown
    # The calculation path is one expander (1 click) and starts collapsed.
    calc = [x for x in at.expander if x.label.startswith("Calculation path:")]
    assert calc and all(not x.proto.expanded for x in calc)


def test_page_shows_chunk_text_one_click_away(tmp_path, search_answer):
    at = run_page(tmp_path, search_answer)
    text_boxes = [x for x in at.expander if x.label.startswith("Text of PDF p.")]
    assert text_boxes and all(not x.proto.expanded for x in text_boxes)
    inside = "\n".join(m.value for x in text_boxes for m in x.markdown)
    assert "No single customer accounts for 10% or more of revenue." in inside
    assert "No single customer" not in _top_level_markdown(at)      # the walker really skips expanders


def test_page_shows_disclaimer_always(tmp_path, fact_answer):
    at = run_page(tmp_path, fact_answer)
    assert any(i.value == UI_CFG["disclaimer"] for i in at.info)
    assert any(c.value == UI_CFG["disclaimer"] for c in at.caption)
    assert UI_CFG["disclaimer"] == "Illustrative analysis, not investment advice."


def test_page_refusal_and_verifier_box_collapsed(tmp_path, env):
    a = answer_question("Will TCS shares go up next year?", env, scripted([]))
    at = run_page(tmp_path, a)
    [w] = at.warning
    assert REFUSAL_TEXT[a.refusal_reason].split(".")[0] in w.value
    [box] = [x for x in at.expander if x.label.startswith("Verifier")]
    assert not box.proto.expanded


def test_page_fallback_is_visible_without_clicks(tmp_path, env):
    a = answer_question("What was TCS's revenue in FY26?", env,
                        scripted([{"tool": "get_financial_fact", "metric_id": "revenue_from_operations",
                                   "period": "FY26", "basis": "consolidated"}],
                                 text="Revenue was INR 999,999 crore in FY26."))
    at = run_page(tmp_path, a)
    assert any("code-built fallback" in c.value and "rejected" in c.value for c in at.caption)
    [box] = [x for x in at.expander if x.label.startswith("Verifier")]
    assert box.label == "Verifier: code-built fallback used" and not box.proto.expanded
    assert "999,999" not in _top_level_markdown(at)


def test_page_dcf_path_has_status_footer_and_assumptions(tmp_path, dcf_answer):
    at = run_page(tmp_path, dcf_answer)
    [box] = [x for x in at.expander if x.label.startswith("Calculation path: DCF run")]
    assert not box.proto.expanded
    inside = "\n".join(m.value for m in box.markdown)
    assert "Key assumptions" in inside and "Rationale" in inside
    assert any("Assumptions status:" in w.value for w in box.warning)
    assert FOOTER in "\n".join(m.value for m in at.markdown).replace("\\", "")


def test_demo_mode_page(tmp_path, fact_answer, dcf_answer):
    _write_run(tmp_path / "20260102-000000_bbbb", [fact_answer, dcf_answer])

    def script(results):
        from erp.ui.app import main as _main
        _main(["--demo", results])
    at = AppTest.from_function(script, args=(str(tmp_path),), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    assert len(at.sidebar.radio) == 1 and not at.text_input     # no question box: nothing is called
    assert "INR 267,021 crore" in _top_level_markdown(at)
    at.sidebar.radio[0].set_value(1).run()
    assert any(x.label.startswith("Calculation path: DCF run") for x in at.expander)


# ---------- wording guards ----------

def _ui_strings() -> str:
    files = list(UI_SRC.glob("*.py")) + [REPO / "app" / "streamlit_app.py", REPO / "config" / "ui.yaml"]
    return "\n".join(f.read_text() for f in files)


def test_ui_code_has_no_advice_or_price_wording():
    text = _ui_strings()
    for phrase in AGENT_CFG["banned_phrases"]:
        assert not re.search(rf"\b{re.escape(phrase)}\b", text, re.I), phrase
    assert not re.search(r"market price|share price|current price", text, re.I)


def test_ui_has_no_custom_javascript():
    text = _ui_strings()
    assert "components.html" not in text and "<script" not in text.lower()
    assert "unsafe_allow_html" not in text


def test_rendered_page_has_no_advice_wording(tmp_path, dcf_answer):
    at = run_page(tmp_path, dcf_answer)
    rendered = "\n".join(m.value for m in at.markdown) + "\n".join(c.value for c in at.caption)
    for phrase in AGENT_CFG["banned_phrases"]:
        assert not re.search(rf"\b{re.escape(phrase)}\b", rendered, re.I), phrase
