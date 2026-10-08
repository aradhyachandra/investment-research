"""M8.1: UI polish. View-model logic for the new tabs, the answer badges and the source page preview.

No live model and no Ollama. Tool outputs come from the real tools on the test fixture database
(tests/fixtures/facts_unverified_fixture.csv) and the toy DCF file (tests/fixtures/dcf_toy_assumptions.yaml,
made-up numbers). PDFs are built on the fly with tests/pdf_fixtures.py; the private PDFs in data/raw/
are never needed.
"""
import json
import re
import sqlite3
from pathlib import Path

import pymupdf
import pytest
import yaml

from erp.agent.answer_schema import Answer
from erp.agent.verifier import VerifierIssue, VerifierReport
from erp.ui import dcf_view, eval_view, page_preview, snapshot
from erp.ui import view_model as vm
from pdf_fixtures import build_pdf
from test_agent_tools import DISPLAY
from test_dcf_run import TOY_YAML
from erp.agent.loop import answer_question
from erp.agent.tools import ToolEnv
from test_ui import FOOTER, UI_CFG, fact_answer, ratio_answer, dcf_answer, scripted, view_of  # noqa: F401
from test_ui import env as chroma_env  # noqa: F401  (only the passage answer needs a Chroma index)

REPO = Path(__file__).resolve().parent.parent


# ---------- fixtures ----------
# Most tests here need no document index. Each Chroma client a test opens stays open for the whole
# pytest process, and with the full suite that many clients made a later Chroma start-up hang
# (seen 2026-10-07; TO VERIFY why). So `env` here has no collection; only `search_answer` uses one.

@pytest.fixture
def env(loaded, tmp_path):
    toy = yaml.safe_load(TOY_YAML.read_text())
    toy["ticker"] = "TCS"          # toy numbers under the TCS ticker, only inside this test
    toy_path = tmp_path / "toy_as_tcs.yaml"
    toy_path.write_text("# STATUS: test fixture status line, toy numbers.\n" + yaml.safe_dump(toy))
    return ToolEnv(conn=loaded, ticker="TCS", display=DISPLAY, dcf_assumptions=toy_path)


@pytest.fixture
def search_answer(chroma_env):
    return answer_question("What do the filings say about customer concentration?", chroma_env,
                           scripted([{"tool": "search_documents", "query": "single customer revenue"}],
                                    question_type="qualitative"))


# ---------- answer badge: checked by the verifier vs code-built fallback ----------

def _answer(**kw) -> Answer:
    base = dict(question="q", ticker="TCS", refused=False, refusal_reason=None, answer_text="t", numbers_used=[], citations=[],
                limitations=[], composed_by="llm", model="m", warnings=[], tool_results=[],
                verification=VerifierReport(ok=True, issues=[]))
    base.update(kw)
    return Answer(**base)


@pytest.mark.parametrize("kw,text,colour", [
    ({}, "Checked by verifier", "green"),
    ({"verification": VerifierReport(ok=True, issues=[VerifierIssue(severity="warning", check="c", span="s",
                                                                    message="m")])},
     "Checked by verifier (with warnings)", "green"),
    ({"composed_by": "template", "verification": VerifierReport(ok=False, issues=[
        VerifierIssue(severity="error", check="c", span="s", message="m")])}, "Code-built fallback answer", "orange"),
    ({"composed_by": "refusal", "refused": True, "refusal_reason": "price_prediction", "verification": None},
     "Refused by code", "gray"),
    ({"verification": None}, "No verifier ran", "red"),
    ({"verification": VerifierReport(ok=False, issues=[VerifierIssue(severity="error", check="c", span="s",
                                                                     message="m")])},
     "Verifier found errors (verifier switched off)", "red"),
])
def test_answer_badge(kw, text, colour):
    view = vm.build_view(_answer(**kw), display=DISPLAY, ui_cfg=UI_CFG, assumptions_file=TOY_YAML, dcf_footer=FOOTER)
    assert vm.answer_badge(view) == (text, colour)


# ---------- citation chips ----------

def test_chip_text_names_badge_document_and_page(fact_answer):
    c = view_of(fact_answer).number_claims[0].citation
    chip = vm.chip_text(c)
    assert chip.startswith("Filing · ") and c.source_title in chip and "PDF p.167 (printed p.197)" in chip
    assert vm.chip_colour(c.badge) == "blue"
    assert vm.chip_colour(vm.AUTHORS_NOTE) == "violet" and vm.chip_colour(vm.OTHER_DOCUMENT) == "gray"


# ---------- calculation path as step cards ----------

def test_ratio_steps_are_inputs_formula_result(ratio_answer):
    [p] = view_of(ratio_answer).ratio_paths
    steps = vm.ratio_steps(p)
    assert [s.title for s in steps] == ["Inputs", "Formula", "Result"]
    inputs = steps[0].lines
    assert any("INR 267,021 crore" in x and "PDF p.167" in x for x in inputs)
    assert p.formula in steps[1].lines[0]
    assert steps[2].lines[0] == p.result_display


# ---------- source page preview targets ----------

def test_preview_targets_carry_page_and_search_strings(fact_answer, search_answer):
    [t] = vm.preview_targets(view_of(fact_answer))
    assert (t.source_title, t.page, t.kind) == ("TCS Integrated Annual Report 2025-26", 167, "fact")
    # The figure as the filing prints it (Indian grouping), plus the other spellings.
    assert t.needles[:2] == ["2,67,021", "267,021"]
    passages = vm.preview_targets(view_of(search_answer))
    assert passages and all(p.kind == "doc_chunk" and p.needles for p in passages)


def test_preview_targets_include_ratio_inputs_once(ratio_answer):
    targets = vm.preview_targets(view_of(ratio_answer))
    ids = [t.evidence_id for t in targets]
    assert len(ids) == len(set(ids)) and all(i.startswith("fact:") for i in ids)
    assert len(ids) == 2       # numerator and denominator facts, no calc row (it has no page)


@pytest.mark.parametrize("value,expected", [
    (267021, ["2,67,021", "267,021", "267021"]),
    (1234567.0, ["12,34,567", "1,234,567", "1234567"]),
    (136.01, ["136.01"]),
    (6417, ["6,417", "6417"]),
    (49, ["49"]),
])
def test_number_needles(value, expected):
    assert page_preview.number_needles(value) == expected


def test_passage_needles_are_whole_sentences():
    text = "Risk management.\nNo single customer accounts for 10%\nor more of revenue. Short. " + "x" * 10
    assert page_preview.passage_needles(text) == ["No single customer accounts for 10% or more of revenue."]


# ---------- source page preview rendering (generated PDFs only) ----------

@pytest.fixture
def pdf(tmp_path):
    return build_pdf(tmp_path / "doc.pdf", [
        {"blocks": [("p", "Cover page.")], "footer": "1"},
        {"blocks": [("h", "Statement of Profit and Loss"),
                    ("p", "Revenue from operations 2,67,021 and 2,55,324. No single customer accounts for "
                          "10% or more of revenue.")], "footer": "2"},
    ])


def test_render_page_highlights_the_cited_number(pdf):
    out = page_preview.render_page(pdf, 2, ["2,67,021", "267,021"])
    assert out.found == ["2,67,021"] and out.png.startswith(b"\x89PNG")
    # The file on disk is not changed (the highlight is drawn on an in-memory copy).
    with pymupdf.open(pdf) as doc:
        assert not list(doc[1].annots())


def test_render_page_finds_a_figure_split_by_spaces(tmp_path):
    # The real annual report extracts some figures with spaces inside ("49, 454", "1, 08, 47 8").
    path = build_pdf(tmp_path / "spaced.pdf", [{"blocks": [("p", "Profit for the year 49, 454 and 1, 08, 47 8.")],
                                                "footer": "1"}])
    assert page_preview.render_page(path, 1, ["49,454"]).found == ["49,454"]
    assert page_preview.render_page(path, 1, ["1,08,478"]).found == ["1,08,478"]
    assert page_preview.render_page(path, 1, ["8,47"]).found == []      # only whole words, not parts of them


def test_render_page_without_a_match_still_shows_the_page(pdf):
    out = page_preview.render_page(pdf, 2, ["9,99,999"])
    assert out.found == [] and out.png.startswith(b"\x89PNG")
    assert "not found" in out.note


def test_render_page_out_of_range_says_so(pdf):
    with pytest.raises(page_preview.PreviewError, match="page 9"):
        page_preview.render_page(pdf, 9, [])


def test_pdf_for_title_uses_company_config(tmp_path):
    files = page_preview.source_files(REPO / "config" / "companies" / "tcs.yaml")
    assert files["TCS Integrated Annual Report 2025-26"] == "tcs_annual_report_FY26.pdf"
    # Missing private data (fresh clone): no path, and a reason the page can show.
    path, why = page_preview.pdf_for_title("TCS Integrated Annual Report 2025-26", files, tmp_path / "raw")
    assert path is None and "data/raw" in why
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "tcs_annual_report_FY26.pdf").write_bytes(b"%PDF")
    path, why = page_preview.pdf_for_title("TCS Integrated Annual Report 2025-26", files, tmp_path / "raw")
    assert path == tmp_path / "raw" / "tcs_annual_report_FY26.pdf" and why is None
    assert page_preview.pdf_for_title("Unknown doc", files, tmp_path / "raw")[0] is None


# ---------- company snapshot ----------

SNAPSHOT_CFG = {
    "period": "FY26", "compare_period": "FY25", "basis": "consolidated",
    "cards": [
        {"label": "Revenue", "tool": "get_financial_fact", "metric_id": "revenue_from_operations",
         "change_ratio": "revenue_growth_yoy"},
        {"label": "Net margin", "tool": "compute_ratio", "ratio_id": "net_margin"},
        {"label": "EPS (basic)", "tool": "get_financial_fact", "metric_id": "eps_basic"},
        {"label": "Cash", "tool": "get_financial_fact", "metric_id": "cash_and_equivalents"},
    ],
}


def _db_file(conn, path) -> Path:
    disk = sqlite3.connect(path)
    conn.backup(disk)
    disk.close()
    return path


def test_readonly_copy_never_writes_to_the_file(env, tmp_path):
    path = _db_file(env.conn, tmp_path / "db.sqlite")
    before = path.read_bytes()
    copy = snapshot.readonly_copy(path)
    snapshot.build_snapshot(snapshot.tool_env(copy, env), SNAPSHOT_CFG, UI_CFG)
    assert copy.execute("SELECT COUNT(*) FROM computed_metric").fetchone()[0] > 0   # ratio rows go to the copy
    assert path.read_bytes() == before
    with pytest.raises(snapshot.SnapshotError, match="not found"):
        snapshot.readonly_copy(tmp_path / "missing.sqlite")


def test_snapshot_cards_come_from_the_tools(env):
    cards = snapshot.build_snapshot(env, SNAPSHOT_CFG, UI_CFG)
    assert [c.label for c in cards] == ["Revenue", "Net margin", "EPS (basic)", "Cash"]
    rev, margin, eps, cash = cards
    assert (rev.current, rev.compare) == ("INR 267,021 crore", "INR 255,324 crore")
    assert rev.change and rev.change.startswith("Revenue growth") and "4.58%" in rev.change
    assert (eps.current, eps.compare) == ("INR 136.01 per share", "INR 134.19 per share")
    assert (cash.current, cash.compare) == ("INR 6,417 crore", "INR 8,342 crore")
    assert margin.current.endswith("%") and margin.compare.endswith("%")
    for c in cards:
        assert c.error is None and c.citations
        assert all(x.badge == vm.FILING and x.page_text.startswith("PDF p.") for x in c.citations)
        # The test fixture is unverified: the card must say so, not claim a sign-off.
        assert c.verified_by is None and "Not yet checked by a human" in c.verified_line


def test_snapshot_shows_who_verified_from_the_database(env):
    env.conn.execute("UPDATE fact SET verified_by = 'Test Reviewer', verified_on = '2026-10-07'")
    cards = snapshot.build_snapshot(env, SNAPSHOT_CFG, UI_CFG)
    for c in cards:
        assert c.verified_by == "Test Reviewer"
        assert c.verified_line == "Verified by Test Reviewer (2026-10-07)"


def test_snapshot_missing_fact_is_reported_not_invented(env):
    cfg = {**SNAPSHOT_CFG, "cards": [{"label": "Headcount", "tool": "get_financial_fact", "metric_id": "headcount"}]}
    [card] = snapshot.build_snapshot(env, cfg, UI_CFG)
    assert card.current is None and card.error


# ---------- DCF tab ----------

@pytest.fixture
def toy_env(env):
    return env      # env already points at the toy DCF file (renamed to TCS inside the test)


def test_scenario_order_comes_from_config_and_file(toy_env):
    assert dcf_view.scenario_names(toy_env.dcf_assumptions, ["bear", "base", "bull"]) == ["bear", "base"]


def test_dcf_tab_view(toy_env):
    v = dcf_view.build_dcf_tab(toy_env, ["bear", "base", "bull"], base="base",
                               assumptions_file=toy_env.dcf_assumptions, footer=FOOTER)
    assert [b.scenario for b in v.scenarios] == ["bear", "base"]
    base_bar = v.scenarios[1]
    assert base_bar.display == "INR 229.32 per share"            # toy base case, hand-worked in tests/test_dcf_run.py
    assert v.base.footer == FOOTER and v.base.status_line.startswith("STATUS:")
    # Heatmap: one cell per (WACC, growth) pair from the engine's grid; undefined cells kept as None.
    detail = v.base_detail["sensitivity"]
    n = len(detail["wacc_values"]) * len(detail["growth_values"])
    assert len(v.heatmap) == n
    centre = [c for c in v.heatmap if c.is_scenario]
    assert len(centre) == 1 and centre[0].display == "INR 229.32 per share"
    # Waterfall: EV -> + cash - debt - leases - minorities -> equity, ending at the engine's equity value.
    labels = [s.label for s in v.waterfall]
    assert labels[0] == "Enterprise value" and labels[-1] == "Equity value"
    assert v.waterfall[-1].end == pytest.approx(v.base_detail["valuation"]["bridge"]["equity_value"])
    assert all(s.display for s in v.waterfall)
    assert v.errors == []


def test_dcf_tab_uses_display_labels_and_leads_with_firm_level_figures(toy_env):
    labels = {"bear": "Low growth", "base": "Central", "bull": "High growth"}
    v = dcf_view.build_dcf_tab(toy_env, ["bear", "base", "bull"], base="base",
                               assumptions_file=toy_env.dcf_assumptions, footer=FOOTER, labels=labels)
    assert [(b.scenario, b.name) for b in v.scenarios] == [("bear", "Low growth"), ("base", "Central")]
    assert v.base_name == "Central"
    assert [h.label for h in v.headline] == ["Enterprise value", "Equity value", "Terminal value share of EV", "WACC"]
    val = v.base_detail["valuation"]
    assert v.headline[3].display == "12.00%"                     # toy WACC = 7% + 1.0 x 5%
    assert v.headline[2].display == f"{val['tv_share_of_ev'] * 100:.2f}%"


def test_dcf_tab_without_labels_falls_back_to_scenario_keys(toy_env):
    v = dcf_view.build_dcf_tab(toy_env, ["base"], base="base", assumptions_file=toy_env.dcf_assumptions, footer=FOOTER)
    assert v.scenarios[0].name == "base" and v.base_name == "base"


def test_ui_config_labels_cover_every_shown_scenario():
    cfg = UI_CFG["dcf"]
    assert set(cfg["scenarios"]) <= set(cfg["labels"])
    assert not any(w in " ".join(cfg["labels"].values()).lower() for w in ("bear", "bull", "target"))


def test_dcf_tab_reports_a_failing_scenario(toy_env):
    v = dcf_view.build_dcf_tab(toy_env, ["base", "nonexistent"], base="base",
                               assumptions_file=toy_env.dcf_assumptions, footer=FOOTER)
    assert [b.scenario for b in v.scenarios] == ["base"]


def test_dcf_tab_without_assumptions_file(env, tmp_path):
    env = env.model_copy(update={"dcf_assumptions": tmp_path / "missing.yaml"})
    v = dcf_view.build_dcf_tab(env, ["base"], base="base", assumptions_file=env.dcf_assumptions, footer=FOOTER)
    assert v.scenarios == [] and v.base is None and v.errors


# ---------- evaluation tab ----------

def _write_eval_run(root: Path, split: str, name: str, metrics: dict, sha="abc1234"):
    d = root / split / name
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps({"status": "finished", "git_sha": sha, "model": "m",
                                            "question_ids": ["Q1", "Q2"]}))
    (d / "metrics.json").write_text(json.dumps(metrics))


def _m(k, n):
    return {"k": k, "n": n, "text": f"{k} of {n}"}


METRICS = {
    "full": {"headline": {"numeric_accuracy": _m(10, 14), "citation_numeric_gold_claims": _m(8, 8)},
             "secondary": {"behavior_all": _m(18, 20), "unsupported_claims": _m(0, 56)}},
    "naive_rag": {"headline": {"numeric_accuracy": _m(1, 14), "citation_numeric_gold_claims": _m(0, 0)},
                  "secondary": {"behavior_all": _m(15, 20), "unsupported_claims": _m(5, 20)}},
}


def test_eval_view_reads_latest_runs(tmp_path):
    _write_eval_run(tmp_path, "dev", "20260101-000000_a", {"full": {}, "naive_rag": {}})
    _write_eval_run(tmp_path, "dev", "20260102-000000_b", METRICS, sha="def5678-dirty")
    [dev] = eval_view.latest_results(tmp_path)          # no test split yet
    assert dev.split == "dev" and dev.run_name == "20260102-000000_b" and dev.dirty
    table = {(r.metric, r.system): r for r in dev.rows}
    assert table[("Numeric accuracy", "Full system")].text == "10 of 14"
    assert table[("Numeric accuracy", "Naive RAG")].share == pytest.approx(1 / 14)
    # 0 of 0 has no share: the chart leaves it out instead of drawing a zero bar.
    assert table[("Gold-matching citations", "Naive RAG")].share is None
    assert table[("Unsupported numeric claims (lower is better)", "Naive RAG")].text == "5 of 20"
    assert len(dev.rows) == 8


def test_eval_view_no_results(tmp_path):
    assert eval_view.latest_results(tmp_path / "nothing") == []


def test_eval_caveats_come_from_the_readme(tmp_path):
    caveats = eval_view.readme_caveats(REPO / "README.md")
    assert caveats and any("Small sample" in c for c in caveats)
    assert eval_view.readme_caveats(tmp_path / "missing.md") == []


# ---------- config the new tabs read ----------

def test_ui_config_has_header_examples_and_snapshot():
    assert UI_CFG["header"]["tagline"] == "AI interprets, code calculates, sources prove"
    kinds = [e["kind"] for e in UI_CFG["examples"]]
    assert len(kinds) == 5
    qs = {json.loads(line)["id"]: json.loads(line) for line in (REPO / "eval" / "questions.jsonl").read_text().splitlines()
          if line.strip()}
    for e in UI_CFG["examples"]:
        assert qs[e["question_id"]]["split"] == "dev"     # never show frozen test questions as examples
    assert [c["label"] for c in UI_CFG["snapshot"]["cards"]]


def test_example_questions_read_text_from_the_question_file():
    ex = vm.example_questions(UI_CFG, REPO / "eval" / "questions.jsonl")
    assert len(ex) == 5 and all(e.question for e in ex)


def test_dcf_scenario_list_matches_assumptions_file():
    names = yaml.safe_load((REPO / "data" / "manual" / "dcf_inputs.yaml").read_text())["scenarios"]
    assert set(UI_CFG["dcf"]["scenarios"]) <= set(names)


def test_snapshot_targets_point_at_the_cited_pages(env):
    cards = snapshot.build_snapshot(env, SNAPSHOT_CFG, UI_CFG)
    targets = snapshot.snapshot_targets(cards)
    assert targets and all(t.page in (166, 167) and t.needles for t in targets)
    rev = next(t for t in targets if t.label.startswith("Revenue"))
    assert rev.needles[0] == "2,67,021"


# ---------- the page itself (headless AppTest: no browser, no model) ----------

from streamlit.testing.v1 import AppTest  # noqa: E402

from erp.agent.llm import load_agent_config  # noqa: E402
from test_ui import _write_run  # noqa: E402

AGENT_CFG = load_agent_config()


def _demo_page(results: str, db: str):
    from erp.ui.app import main as _main
    _main(["--demo", results, "--db", db])


@pytest.fixture
def demo_page(tmp_path, env, fact_answer, ratio_answer, dcf_answer):
    _write_run(tmp_path / "20260102-000000_bbbb", [fact_answer, ratio_answer, dcf_answer])
    db = _db_file(env.conn, tmp_path / "db.sqlite")
    at = AppTest.from_function(_demo_page, args=(str(tmp_path), str(db)), default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def _all_text(at) -> str:
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption] + [w.value for w in at.warning]
    parts += [i.value for i in at.info] + [str(m.value) for m in at.metric] + [m.label for m in at.metric]
    return "\n".join(parts)


def test_page_has_header_tabs_and_disclaimer(demo_page):
    at = demo_page
    assert [t.label for t in at.tabs] == ["Ask", "Company snapshot", "DCF", "How it works", "Evaluation"]
    text = _all_text(at)
    assert UI_CFG["header"]["scope"] in text and UI_CFG["header"]["tagline"] in text
    assert any(i.value == UI_CFG["disclaimer"] for i in at.info)       # top of every page, outside the tabs
    assert any(c.value == UI_CFG["disclaimer"] for c in at.caption)    # and at the bottom


def test_page_snapshot_tab_shows_tool_values_and_sources(demo_page):
    snap = demo_page.tabs[1]
    values = [m.value for m in snap.metric]
    assert "INR 267,021 crore" in values and "INR 136.01 per share" in values
    text = "\n".join(m.value for m in snap.markdown)
    assert ":blue-badge[Filing]" in text and "PDF p.167 (printed p.197)" in text
    assert "not yet checked by a human" in text.lower()      # fixture facts are unverified


def test_page_dcf_tab_has_status_footer_and_charts(demo_page):
    dcf = demo_page.tabs[2]
    assert any("STATUS:" in w.value for w in dcf.warning)
    footer_captions = [c for c in dcf.caption if FOOTER in c.value.replace("\\", "")]
    assert len(footer_captions) >= 3                          # next to each chart of DCF figures
    assert "Assumptions" in "\n".join(m.value for m in dcf.markdown)


def test_page_has_no_advice_or_price_wording_on_any_tab(demo_page):
    text = _all_text(demo_page)
    for phrase in AGENT_CFG["banned_phrases"]:
        assert not re.search(rf"\b{re.escape(phrase)}\b", text, re.I), phrase
    assert not re.search(r"market price|share price|current price|target", text, re.I)


def test_page_demo_example_button_picks_the_saved_answer(tmp_path, env, fact_answer, dcf_answer):
    a1 = fact_answer.model_copy()
    a2 = dcf_answer.model_copy()
    run = tmp_path / "20260102-000000_bbbb"
    _write_run(run, [a1, a2])
    # _write_run numbers questions EV-X00, EV-X01; give the second one the DCF example id.
    rows = [json.loads(x) for x in (run / "full.jsonl").read_text().splitlines()]
    rows[1]["question_id"] = UI_CFG["examples"][2]["question_id"]          # the DCF example
    (run / "full.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    at = AppTest.from_function(_demo_page, args=(str(tmp_path), str(tmp_path / "none.sqlite")), default_timeout=60)
    at.run()
    [button] = [b for b in at.button if b.label == UI_CFG["examples"][2]["kind"]]
    button.click().run()
    assert not at.exception
    assert any(x.label.startswith("Calculation path: DCF run") for x in at.expander)


def test_page_without_database_says_how_to_build_it(tmp_path, fact_answer):
    _write_run(tmp_path / "20260102-000000_bbbb", [fact_answer])
    at = AppTest.from_function(_demo_page, args=(str(tmp_path), str(tmp_path / "none.sqlite")), default_timeout=60)
    at.run()
    assert not at.exception
    assert any("load_facts" in i.value for i in at.tabs[1].info)
    assert any("load_facts" in i.value for i in at.tabs[2].info)


def test_ask_tab_dcf_figure_carries_status_and_footer(demo_page):
    at = demo_page
    at.sidebar.radio[0].set_value(2).run()          # the saved DCF answer
    assert not at.exception
    ask = at.tabs[0]
    shown = "\n".join(c.value for c in ask.caption).replace("\\", "")
    assert "STATUS:" in shown and FOOTER in shown
