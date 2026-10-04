"""M7 unit tests: the eval harness (src/erp/eval/). Written before the code.

Covers: reading the question file (read only), numeric claims found in answer text, matching a
claim with the gold value/unit/period, numeric citation correctness, behaviour classes
(answered / refused / not available), coarse routing checks, the verifier-off ablation, the
naive-RAG baseline, the qualitative labelling sample, and the test-split safety of run_eval.

All LLM calls are scripted fakes; the DB is the in-memory sample, Chroma a temp index with
fake embeddings, and DCF the TOY fixture under the TCS ticker. The CLI tests use a small
synthetic question file, so no test-split gold from eval/questions.jsonl is read here.
"""
import csv
import hashlib
import json
import re

import pytest

from erp.agent.llm import load_agent_config
from erp.agent.loop import answer_question
from erp.eval import cli
from erp.eval.baseline import naive_rag_answer
from erp.eval.claims import extract_claims, numeric_claims_in_text
from erp.eval.metrics import summarize
from erp.eval.qualitative import sample_claims, tally_labels, write_sample_csv
from erp.eval.questions import QUESTIONS_PATH, EvalQuestion, QuestionFileError, load_questions
from erp.eval.score import classify_behavior, load_eval_config, matches_gold, routing_check, score_question
from fakes import ScriptedLLM
from test_m5_acceptance import env  # noqa: F401  (fixture: sample DB, fake Chroma, TOY DCF)

CFG = load_agent_config()
ECFG = load_eval_config()

REVENUE_26 = {"tool": "get_financial_fact", "metric_id": "revenue_from_operations", "period": "FY26"}
NET_MARGIN_26 = {"tool": "compute_ratio", "ratio_id": "net_margin", "period": "FY26"}


def q(**kw) -> EvalQuestion:
    """A synthetic question (not from the eval file)."""
    base = dict(id="SYN-1", category="A", question="Revenue FY26?", gold_answer="", gold_value=267021,
                gold_unit="INR_CRORE", gold_period="FY26", tolerance=0, gold_sources=[{"source_id": 1, "page": 167}],
                must_refuse=False, split="dev", expected_behavior="answer", notes="")
    base.update(kw)
    return EvalQuestion(**base)


def llm(calls, text, refuse=None):
    """Router returns `calls` (or a refusal); composer returns `text` (str or f(prompt));
    the baseline prompt (no used_number_ids field) also gets `text`."""
    def reply(messages, schema):
        props = schema["properties"]
        if "question_type" in props:
            if refuse:
                return json.dumps({"calls": [], "question_type": "out_of_scope", "refusal_reason": refuse})
            return json.dumps({"calls": calls, "question_type": "numeric", "refusal_reason": "none"})
        t = text(messages[-1]["content"]) if callable(text) else text
        out = {"answer_text": t, "cited_evidence_ids": []}
        if "used_number_ids" in props:
            out["used_number_ids"] = []
        return json.dumps(out)
    return ScriptedLLM(reply)


def chunk_ids(prompt):
    return list(dict.fromkeys(re.findall(r"\[(chunk:[^\]]+)\]", prompt)))


# ---------- question file ----------

def test_real_question_file_loads_and_splits():
    before = hashlib.sha256(QUESTIONS_PATH.read_bytes()).hexdigest()
    dev, test = load_questions(split="dev"), load_questions(split="test")
    assert len(dev) == 20 and len(test) == 21
    assert len({x.id for x in dev + test}) == 41
    assert {x.expected_behavior for x in dev + test} == {"answer", "refuse", "not_available"}
    assert all((x.expected_behavior == "refuse") == x.must_refuse for x in dev + test)
    assert hashlib.sha256(QUESTIONS_PATH.read_bytes()).hexdigest() == before     # read only


def test_bad_question_file_is_refused(tmp_path):
    good = q().model_dump()
    p = tmp_path / "q.jsonl"
    p.write_text(json.dumps({k: v for k, v in good.items() if k != "expected_behavior"}) + "\n")
    with pytest.raises(QuestionFileError, match="expected_behavior"):
        load_questions(p)
    p.write_text(json.dumps({**good, "must_refuse": True}) + "\n")
    with pytest.raises(QuestionFileError, match="must_refuse"):
        load_questions(p)
    p.write_text(json.dumps(good) + "\n" + json.dumps(good) + "\n")
    with pytest.raises(QuestionFileError, match="duplicate"):
        load_questions(p)


# ---------- numeric claims in text ----------

def test_numeric_claims_read_value_unit_and_period():
    text = ("Revenue in FY26 was INR 267,021 crore [fact:1]. That is INR 2.67 lakh crore, or INR 2,670,210 "
            "million. Net margin was 18.43% in FY26. Basic EPS was INR 136.01 per share (PDF page 167).")
    claims = numeric_claims_in_text(text)
    assert [(c.text, c.unit) for c in claims] == [
        ("INR 267,021 crore", "INR_CRORE"), ("INR 2.67 lakh crore", "INR_LAKH_CRORE"),
        ("INR 2,670,210 million", "INR_MILLION"), ("18.43%", "PERCENT"), ("INR 136.01 per share", "INR_PER_SHARE")]
    assert claims[0].periods == ["FY26"] and claims[1].periods == []          # periods of the claim's sentence
    assert claims[0].value == "267021" and claims[3].value == "18.43"          # page 167 and [fact:1] are not claims


def test_dollar_figures_are_not_read_as_rupees():
    # Live dev run 1 (naive RAG): "$11,400 million" was read as INR million by the shared tokenizer.
    claims = numeric_claims_in_text("Revenue was $11,400 million, or US$ 30 billion, or USD 2 crore.")
    assert [c.unit for c in claims] == ["USD", "USD", "USD"]


def test_years_and_dates_are_not_numeric_claims():
    claims = numeric_claims_in_text("FY26 runs from 1 April 2025 to 31 March 2026, not calendar 2026.")
    assert claims == []


# ---------- gold matching ----------

@pytest.mark.parametrize("text,question,ok", [
    ("Revenue in FY26 was INR 267,021 crore.", q(), True),
    ("Revenue in FY26 was INR 2,67,021 crore.", q(), True),                     # Indian grouping
    ("Revenue in FY26 was INR 267,020 crore.", q(), False),                     # exact for reported facts
    ("Revenue in FY26 was INR 267,021 million.", q(), False),                   # wrong unit
    ("Revenue in FY25 was INR 267,021 crore.", q(), False),                     # wrong period
    ("Revenue was INR 267,021 crore. This is for FY26.", q(), True),            # period elsewhere in the answer
    ("Revenue was INR 267,021 crore.", q(), False),                             # no period stated at all
    ("EPS in FY26 was INR 136.01 per share.", q(gold_value=136.01, gold_unit="INR_PER_SHARE"), True),
    ("EPS in FY26 was INR 136 per share.", q(gold_value=136.01, gold_unit="INR_PER_SHARE"), False),
    ("Net margin in FY26 was 18.4%.", q(gold_value=18.43, gold_unit="PERCENT", tolerance=0.005), True),
    ("Net margin in FY26 was 18.0%.", q(gold_value=18.43, gold_unit="PERCENT", tolerance=0.005), False),
    ("FY26 revenue was INR 2.67 lakh crore.",
     q(gold_value=2.67021, gold_unit="INR_LAKH_CRORE", tolerance=0.005), True),
    # DCF: gold_period is a valuation date, not a period label, so no period is required
    ("The base-case value is INR 1,914.82 per share.",
     q(category="D", gold_value=1914.82, gold_unit="INR_PER_SHARE", gold_period="valuation 2026-03-31",
       tolerance=0.005, gold_sources=[]), True),
])
def test_claim_matches_gold_value_unit_and_period(text, question, ok):
    claims = numeric_claims_in_text(text)
    assert any(matches_gold(c, question, all_periods=_periods(claims, text)) for c in claims) is ok


def _periods(claims, text):
    from erp.agent.verifier import periods_in
    return periods_in(text)


# ---------- claims of real answers: citations and support ----------

def test_ratio_claim_cites_the_input_pages_and_is_supported(env):
    a = answer_question("Net margin FY26?", env, llm([NET_MARGIN_26], "Net margin in FY26 was 18.43%."), cfg=CFG)
    assert a.composed_by == "llm"
    numeric, _ = extract_claims(a)
    (c,) = numeric
    assert c.supported and c.tool_number_ids
    assert (1, 167) in {(p.source_id, p.page) for p in c.cited}               # via the calc's input facts


def test_verifier_off_ships_the_llm_text_and_records_the_report(env):
    bad = "Revenue in FY26 was INR 270,021 crore."
    on = answer_question("Revenue FY26?", env, llm([REVENUE_26], bad), cfg=CFG)
    off = answer_question("Revenue FY26?", env, llm([REVENUE_26], bad), cfg=CFG, verify=False)
    assert on.composed_by == "template" and "270,021" not in on.answer_text
    assert off.composed_by == "llm" and off.answer_text == bad
    assert off.verification is not None and not off.verification.ok           # recorded, not enforced
    assert any("verifier off" in w for w in off.warnings)
    (c,) = extract_claims(off)[0]
    assert not c.supported and c.cited == []
    s = score_question(q(), off)
    assert s.numeric_claims == 1 and s.unsupported_claims == 1 and not s.numeric_correct
    assert s.verifier_would_reject and not s.verifier_rejected


def test_template_answer_is_scored_like_any_other(env):
    on = answer_question("Revenue FY26?", env, llm([REVENUE_26], "Revenue in FY26 was INR 270,021 crore."), cfg=CFG)
    s = score_question(q(), on)
    assert s.numeric_correct and s.gold_citing_claims == s.numeric_claims_in_scope == 1
    assert s.verifier_rejected and s.behavior == "answered" and s.behavior_ok


# ---------- naive-RAG baseline ----------

def test_baseline_uses_one_llm_call_over_chunks_only(env):
    fake = llm(None, lambda p: f"No single customer accounts for 10% or more of revenue [{chunk_ids(p)[0]}].")
    a = naive_rag_answer("Does any customer account for 10% of revenue?", ticker="TCS",
                         collection=env.collection, embed_fn=env.embed_fn, llm_fn=fake, top_k=3, passage_chars=900)
    assert len(fake.calls) == 1                                                # no router, no composer step
    assert set(fake.calls[0]["schema"]["properties"]) == {"answer_text", "cited_evidence_ids"}
    assert a.route is None and a.verification is None and a.numbers_used == []
    assert [r.tool for r in a.tool_results] == ["search_documents"]
    assert a.citations and all(c.kind == "doc_chunk" for c in a.citations)
    (c,) = extract_claims(a)[0]
    assert c.unit == "PERCENT" and c.supported and (1, 226) in {(p.source_id, p.page) for p in c.cited}


def test_baseline_has_no_guards(env):
    # The baseline is a measurement of the naive approach: nothing filters its text. Its outputs
    # stay in eval/results (gitignored) and are scored for advice language, never shown as product output.
    a = naive_rag_answer("Should I buy TCS?", ticker="TCS", collection=env.collection, embed_fn=env.embed_fn,
                         llm_fn=llm(None, "You should buy."), top_k=3, passage_chars=900)
    assert not a.refused and a.answer_text == "You should buy."
    assert score_question(q(category="G", expected_behavior="refuse", must_refuse=True, gold_value=None,
                            gold_unit=None, gold_period=None, tolerance=None, gold_sources=[]), a).advice_language


# ---------- behaviour and routing ----------

def test_behavior_classes(env):
    refused = answer_question("Should I buy TCS shares?", env, llm([], ""), cfg=CFG)
    assert classify_behavior(refused) == "refuse"
    outside = answer_question("Revenue in FY19?", env, llm([], "", refuse="outside_data"), cfg=CFG)
    assert classify_behavior(outside) == "not_available"
    na = answer_question("Revenue FY26?", env, llm([REVENUE_26], "That figure is not available."), cfg=CFG)
    assert classify_behavior(na) == "not_available"
    partial = answer_question("Revenue FY26?", env, llm([REVENUE_26], "Revenue in FY26 was INR 267,021 crore; "
                                                                      "the quarter is not available."), cfg=CFG)
    assert classify_behavior(partial) == "partial"
    answered = answer_question("Revenue FY26?", env, llm([REVENUE_26], "Revenue in FY26 was INR 267,021 crore."),
                               cfg=CFG)
    assert classify_behavior(answered) == "answered"


@pytest.mark.parametrize("expected,observed,ok", [
    ("answer", "answered", True), ("answer", "partial", True), ("answer", "refuse", False),
    ("refuse", "refuse", True), ("refuse", "not_available", False), ("refuse", "answered", False),
    ("not_available", "not_available", True), ("not_available", "refuse", True),
    ("not_available", "answered", False),
])
def test_behavior_acceptance_matrix(expected, observed, ok):
    assert (observed in ECFG["behavior"]["accept"][expected]) is ok


def test_routing_check_by_category(env):
    a = answer_question("Revenue FY26?", env, llm([REVENUE_26], "Revenue in FY26 was INR 267,021 crore."), cfg=CFG)
    assert routing_check(q(), a) == (True, True)
    assert routing_check(q(gold_period="FY25"), a) == (True, False)                     # wrong period
    assert routing_check(q(category="C"), a) == (False, False)                          # wrong tool
    assert routing_check(q(category="B", gold_value=None), a) is None                   # period question: not scored
    refused = answer_question("Should I buy TCS shares?", env, llm([], ""), cfg=CFG)
    assert routing_check(q(category="G", expected_behavior="refuse", must_refuse=True), refused) == (True, True)
    assert routing_check(q(category="G", expected_behavior="refuse", must_refuse=True), a) == (False, False)
    assert routing_check(q(category="G", expected_behavior="not_available"), a) is None


# ---------- metrics ----------

def test_summary_reports_counts_per_category_and_headline(env):
    good = answer_question("Revenue FY26?", env, llm([REVENUE_26], "Revenue in FY26 was INR 267,021 crore."), cfg=CFG)
    wrong = answer_question("Revenue FY26?", env, llm([REVENUE_26], "Revenue in FY26 was INR 267,021 crore."),
                            cfg=CFG)
    refused = answer_question("Should I buy TCS shares?", env, llm([], ""), cfg=CFG)
    scores = [score_question(q(id="S1"), good),
              score_question(q(id="S2", gold_value=255324, gold_period="FY25"), wrong),
              score_question(q(id="S3", category="G", expected_behavior="refuse", must_refuse=True, gold_value=None,
                               gold_unit=None, gold_period=None, tolerance=None, gold_sources=[]), refused)]
    s = summarize(scores)
    assert s["headline"]["numeric_accuracy"] == {"k": 1, "n": 2, "text": "1 of 2"}
    assert s["headline"]["citation_numeric"]["text"] == "2 of 2"               # both claims cite PDF p.167
    assert s["secondary"]["refusal_G"]["text"] == "1 of 1"
    assert s["secondary"]["routing_tools"]["text"] == "3 of 3"
    assert s["by_category"]["A"]["numeric_accuracy"]["text"] == "1 of 2"
    assert s["by_category"]["G"]["behavior"]["text"] == "1 of 1"
    assert s["failures"]["numeric"] == ["S2"]


# ---------- qualitative labelling helper ----------

def test_qualitative_sample_csv_has_blank_labels_and_is_repeatable(env, tmp_path):
    def text(p):
        c = chunk_ids(p)[0]
        return f"TCS runs security operations centres [{c}]. It also holds cyber insurance for residual risk [{c}]."
    a = answer_question("How does TCS manage cyber risk?", env,
                        llm([{"tool": "search_documents", "query": "cyber attacks"}], text), cfg=CFG)
    records = [{"system": "full", "question_id": f"S{i}", "category": "E", "question": a.question,
                "gold_sources": [], "answer": a.model_dump(mode="json")} for i in range(15)]
    first = sample_claims(records, n=20, seed=0)
    assert len(first) == 20 and first == sample_claims(records, n=20, seed=0)
    out = tmp_path / "labels.csv"
    write_sample_csv(first, out)
    rows = list(csv.DictReader(out.open()))
    assert len(rows) == 20 and all(r["supports"] == "" for r in rows)
    assert rows[0]["cited_pages"] and rows[0]["cited_text"]
    rows[0]["supports"], rows[1]["supports"] = "yes", "no"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    assert tally_labels(out) == {"yes": 1, "no": 1, "unlabelled": 18}


# ---------- run_eval: dev runs and test-split safety ----------

SYN = [q(id="SYN-D1", split="dev"), q(id="SYN-D2", split="dev", category="G", expected_behavior="refuse",
                                       must_refuse=True, question="Should I buy TCS shares?", gold_value=None,
                                       gold_unit=None, gold_period=None, tolerance=None, gold_sources=[]),
       q(id="SYN-T1", split="test")]


@pytest.fixture
def harness(env, tmp_path):
    qfile = tmp_path / "questions.jsonl"
    qfile.write_text("".join(json.dumps(x.model_dump()) + "\n" for x in SYN))
    root = tmp_path / "results"
    answers = []

    def run(argv, typed="no"):
        return cli.main(argv, input_fn=lambda prompt: typed, make_env=lambda: env,
                        llm_fn=llm([REVENUE_26], "Revenue in FY26 was INR 267,021 crore."),
                        results_root=root, questions_path=qfile)
    return run, root, qfile, answers


def test_dev_runs_are_unlimited_and_saved_with_metadata(harness):
    run, root, qfile, _ = harness
    first = run([])
    second = run([])
    assert first != second and first.parent == second.parent == root / "dev"
    meta = json.loads((first / "run.json").read_text())
    for key in ("timestamp", "git_sha", "model", "split", "systems", "questions_sha256", "status"):
        assert key in meta
    assert meta["split"] == "dev" and meta["status"] == "finished"
    assert meta["systems"] == ["full", "full_no_verifier", "naive_rag"]
    rec = [json.loads(x) for x in (first / "full.jsonl").read_text().splitlines()]
    assert [r["question_id"] for r in rec] == ["SYN-D1", "SYN-D2"]                # dev only
    for field in ("answer", "numeric_claims", "qualitative_claims", "score", "seconds"):
        assert field in rec[0]
    assert "citations" in rec[0]["answer"] and "verification" in rec[0]["answer"]
    metrics = json.loads((first / "metrics.json").read_text())
    assert set(metrics) == {"full", "full_no_verifier", "naive_rag"}
    report = (first / "report.md").read_text()
    assert "Numeric accuracy" in report and "1 of 1" in report and "| A |" in report


def test_test_split_needs_the_flag_and_the_typed_phrase(harness):
    run, root, _, _ = harness
    with pytest.raises(SystemExit):
        run(["--test"], typed="yes")                                           # wrong phrase
    assert not (root / "test").exists() or not any((root / "test").iterdir())
    with pytest.raises(SystemExit):
        run(["--test", "--systems", "full"], typed=ECFG["test_confirmation_phrase"])   # all systems or none
    out = run(["--test"], typed=ECFG["test_confirmation_phrase"])
    assert out.parent == root / "test"
    rec = [json.loads(x) for x in (out / "naive_rag.jsonl").read_text().splitlines()]
    assert [r["question_id"] for r in rec] == ["SYN-T1"]


def test_test_split_refuses_a_second_run_without_force(harness):
    run, root, _, _ = harness
    phrase = ECFG["test_confirmation_phrase"]
    run(["--test"], typed=phrase)
    with pytest.raises(SystemExit):
        run(["--test"], typed=phrase)
    assert len(list((root / "test").iterdir())) == 1
    run(["--test", "--force"], typed=phrase)
    assert len(list((root / "test").iterdir())) == 2


def test_rescore_rewrites_metrics_without_calling_the_llm(harness):
    run, root, _, _ = harness
    out = run(["--systems", "full"])
    (out / "metrics.json").unlink()
    cli.main(["--rescore", str(out)], input_fn=lambda p: "", make_env=lambda: pytest.fail("no env needed"),
             llm_fn=lambda *a, **k: pytest.fail("no LLM needed"), results_root=root)
    assert set(json.loads((out / "metrics.json").read_text())) == {"full"}
