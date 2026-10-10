"""E2: the v1.1 evaluation. Written before the code.

Covers: a second question file (eval/questions_v1_1.jsonl) loads, category H (history/trend
questions with several numbers) is scored, run_eval --questions keeps each question file's
results (and its one-time test-split gate) apart, and the results table shows v1 and v1.1 side
by side without mixing them.

The CLI tests use small synthetic question files. No test-split question text is read here:
the v1.1 file is only counted.
"""
import hashlib
import json

import pytest

from erp.agent.loop import answer_question
from erp.eval import cli
from erp.eval.metrics import summarize
from erp.eval.questions import QUESTIONS_PATH, QuestionFileError, load_questions, question_set
from erp.eval.results_table import QuestionSet, results_markdown
from erp.eval.score import load_eval_config, routing_check, score_question
from erp.config import REPO
from test_eval_harness import CFG, REVENUE_26, llm, q
from test_m5_acceptance import env  # noqa: F401  (fixture: sample DB, fake Chroma, TOY DCF)

ECFG = load_eval_config()
V11_PATH = REPO / "eval" / "questions_v1_1.jsonl"


# ---------- the v1.1 question file ----------

def test_v1_1_file_loads_with_category_h_and_is_not_changed():
    before = hashlib.sha256(V11_PATH.read_bytes()).hexdigest()
    dev, test = load_questions(V11_PATH, split="dev"), load_questions(V11_PATH, split="test")
    assert len(dev) == 22 and len(test) == 23
    assert len({x.id for x in dev + test}) == 45
    assert "H" in {x.category for x in dev} and "H" in {x.category for x in test}
    assert hashlib.sha256(V11_PATH.read_bytes()).hexdigest() == before          # read only


def test_unknown_category_is_still_refused(tmp_path):
    p = tmp_path / "q.jsonl"
    p.write_text(json.dumps({**q().model_dump(), "category": "Z"}) + "\n")
    with pytest.raises(QuestionFileError, match="category"):
        load_questions(p)


# ---------- category H: scoring ----------

def h(**kw):
    base = dict(id="SYN-H1", category="H", question="How did revenue growth change from FY25 to FY26?",
                gold_value=None, gold_unit="PERCENT", gold_period=None, tolerance=None,
                gold_sources=[{"source_id": 1, "page": 167}])
    return q(**{**base, **kw})


GROWTH = {"tool": "compute_ratio", "ratio_id": "revenue_growth_yoy"}


@pytest.mark.parametrize("calls,expected", [
    ([{**GROWTH, "period": "FY25"}, {**GROWTH, "period": "FY26"}], (True, True)),   # one lookup per year
    ([{**REVENUE_26}, {**REVENUE_26, "period": "FY25"}], (True, True)),            # facts are fine too
    ([{**GROWTH, "period": "FY26"}], (True, False)),                              # several numbers needed
    ([{"tool": "run_dcf", "scenario": "base"}], (False, False)),
    ([{"tool": "search_documents", "query": "revenue growth"}], (False, False)),   # no figures fetched
])
def test_h_routing_needs_data_tools_and_two_periods(env, calls, expected):
    # The question names no period, so the router's "add the missing year" rule does not hide a gap.
    a = answer_question("How has TCS's revenue growth changed over the years?", env,
                        llm(calls, "Revenue growth slowed."), cfg=CFG)
    assert routing_check(h(), a, ECFG) == expected


def test_h_without_gold_value_is_out_of_numeric_accuracy_but_in_citations_and_behaviour(env):
    a = answer_question("How did revenue change from FY25 to FY26?", env,
                        llm([REVENUE_26, {**REVENUE_26, "period": "FY25"}],
                            "Revenue rose from INR 255,324 crore in FY25 to INR 267,021 crore in FY26."), cfg=CFG)
    s = score_question(h(), a, ECFG, CFG)
    assert not s.has_gold_value and not s.numeric_correct
    assert s.behavior_ok and s.numeric_claims == 2 and s.numeric_claims_in_scope == 2
    m = summarize([s, score_question(q(id="SYN-A1"), a, ECFG, CFG)])
    assert m["by_category"]["H"]["numeric_accuracy"] is None                  # shown as n/a, not 0 of 0
    assert m["headline"]["numeric_accuracy"]["n"] == 1                         # only the A question counts
    assert m["by_category"]["H"]["routing_tools"]["text"] == "1 of 1"


# ---------- which results folder a question file uses ----------

def test_question_set_labels_and_folders(tmp_path):
    assert question_set(QUESTIONS_PATH) == ("v1", None)                       # v1 keeps results/dev, results/test
    assert question_set(V11_PATH) == ("v1_1", "v1_1")
    assert question_set(tmp_path / "questions_v9.jsonl", default=tmp_path / "questions.jsonl") == ("v9", "v9")
    assert question_set(tmp_path / "questions.jsonl", default=tmp_path / "questions.jsonl") == ("v1", None)
    for bad in ("questions_dev.jsonl", "questions_test.jsonl", "questions_a b.jsonl"):
        with pytest.raises(ValueError):
            question_set(tmp_path / bad)


def test_config_question_sets_match_the_folder_rule():
    sets = ECFG["question_sets"]
    assert sets["v1"] == "eval/questions.jsonl" and sets["v1_1"] == "eval/questions_v1_1.jsonl"
    for label, path in sets.items():
        assert question_set(REPO / path)[0] == label


# ---------- run_eval --questions ----------

SYN = [q(id="SYN-D1", split="dev"), q(id="SYN-T1", split="test")]
SYN_V9 = [q(id="V9-D1", split="dev"), h(id="V9-H1", split="dev"), q(id="V9-T1", split="test")]


@pytest.fixture
def harness(env, tmp_path):
    v1 = tmp_path / "questions.jsonl"
    v1.write_text("".join(json.dumps(x.model_dump()) + "\n" for x in SYN))
    v9 = tmp_path / "questions_v9.jsonl"
    v9.write_text("".join(json.dumps(x.model_dump()) + "\n" for x in SYN_V9))
    root = tmp_path / "results"

    def run(argv, typed="no"):
        return cli.main(argv, input_fn=lambda prompt: typed, make_env=lambda: env,
                        llm_fn=llm([REVENUE_26], "Revenue in FY26 was INR 267,021 crore."),
                        results_root=root, questions_path=v1)
    return run, root, v1, v9


def test_default_question_file_keeps_the_v1_layout(harness):
    run, root, v1, _ = harness
    out = run(["--systems", "full"])
    assert out.parent == root / "dev"
    meta = json.loads((out / "run.json").read_text())
    assert meta["question_set"] == "v1"
    assert meta["questions_sha256"] == hashlib.sha256(v1.read_bytes()).hexdigest()


def test_other_question_file_gets_its_own_folder_and_is_recorded(harness):
    run, root, _, v9 = harness
    out = run(["--questions", str(v9), "--systems", "full"])
    assert out.parent == root / "v9" / "dev"
    meta = json.loads((out / "run.json").read_text())
    assert meta["question_set"] == "v9"
    assert meta["questions_path"] == str(v9)
    assert meta["questions_sha256"] == hashlib.sha256(v9.read_bytes()).hexdigest()
    assert meta["question_ids"] == ["V9-D1", "V9-H1"]
    report = (out / "report.md").read_text()
    assert "questions_v9.jsonl" in report and "| H |" in report


def test_ids_are_checked_against_the_chosen_file(harness):
    run, _, _, v9 = harness
    with pytest.raises(SystemExit):
        run(["--questions", str(v9), "--ids", "SYN-D1"])                      # a v1 id, not in v9


def test_test_split_gate_is_per_question_file(harness):
    run, root, _, v9 = harness
    phrase = ECFG["test_confirmation_phrase"]
    run(["--test"], typed=phrase)                                             # v1 test, once
    out = run(["--questions", str(v9), "--test"], typed=phrase)               # v9 has its own gate
    assert out.parent == root / "v9" / "test"
    assert [json.loads(x)["question_id"] for x in (out / "full.jsonl").read_text().splitlines()] == ["V9-T1"]
    with pytest.raises(SystemExit):
        run(["--questions", str(v9), "--test"], typed=phrase)                 # second v9 test run refused
    with pytest.raises(SystemExit):
        run(["--test"], typed=phrase)                                         # v1 still refused too
    assert len(list((root / "test").iterdir())) == 1 and len(list((root / "v9" / "test").iterdir())) == 1


def test_rescore_of_a_v9_run_uses_the_v9_file(harness):
    run, root, _, v9 = harness
    out = run(["--questions", str(v9), "--systems", "full"])
    (out / "metrics.json").unlink()
    cli.main(["--rescore", str(out)], input_fn=lambda p: "", make_env=lambda: pytest.fail("no env needed"),
             llm_fn=lambda *a, **k: pytest.fail("no LLM needed"), results_root=root)
    assert "H" in json.loads((out / "metrics.json").read_text())["full"]["by_category"]


# ---------- results table: v1 and v1.1 side by side, never mixed ----------

def _run(folder, name, qfile, acc, status="finished"):
    d = folder / name
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps({
        "git_sha": "a" * 40, "model": "m", "temperature": 0, "seed": 0, "question_ids": ["x"],
        "status": status, "questions_path": qfile, "questions_sha256": "x"}))
    k, n = acc
    (d / "metrics.json").write_text(json.dumps({
        "full": {"headline": {"numeric_accuracy": {"k": k, "n": n, "text": f"{k} of {n}"}}, "secondary": {}}}))


def test_two_question_sets_side_by_side_each_labelled(tmp_path):
    root = tmp_path / "results"
    _run(root / "dev", "20260101-000000_a", "eval/questions.jsonl", (10, 14))
    _run(root / "v1_1" / "dev", "20260102-000000_b", "eval/questions_v1_1.jsonl", (12, 16))
    sets = [QuestionSet("v1", tmp_path / "questions.jsonl", root),
            QuestionSet("v1_1", tmp_path / "questions_v1_1.jsonl", root / "v1_1")]
    md = results_markdown(root, sets=sets)
    dev, test = md.split("### Test split")
    assert "| Metric | v1: Full system | v1: Verifier off | v1: Naive RAG | v1_1: Full system |" in dev
    assert "| Numeric accuracy (questions with a gold value) | 10 of 14 | n/a | n/a | 12 of 16 | n/a | n/a |" in dev
    assert "**v1**" in dev and "**v1_1**" in dev
    assert "not comparable" in md
    assert "v1: Test split not yet run." in test and "v1_1: Test split not yet run." in test


def test_a_run_made_with_another_question_file_is_not_shown(tmp_path):
    root = tmp_path / "results"
    _run(root / "v1_1" / "dev", "20260101-000000_a", "eval/questions_v1_1.jsonl", (12, 16))
    _run(root / "v1_1" / "dev", "20260102-000000_b", "eval/questions.jsonl", (99, 99))   # wrong file
    sets = [QuestionSet("v1_1", tmp_path / "questions_v1_1.jsonl", root / "v1_1")]
    md = results_markdown(root, sets=sets)
    assert "12 of 16" in md and "99 of 99" not in md
    assert "made with another question file" in md


def test_single_set_output_is_unchanged(tmp_path):
    root = tmp_path / "results"
    _run(root / "dev", "20260101-000000_a", "eval/questions.jsonl", (10, 14))
    md = results_markdown(root)
    assert "| Metric | Full system | Verifier off | Naive RAG |" in md
    assert "| Numeric accuracy (questions with a gold value) | 10 of 14 | n/a | n/a |" in md
