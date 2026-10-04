"""run_eval: run the systems on one split of eval/questions.jsonl, score them, save everything.

  dev (default)  unlimited runs, results in eval/results/dev/<timestamp>_<sha>/
  --test         the frozen test split: needs the typed confirmation phrase (config/eval.yaml),
                 always runs all systems in one go, writes to eval/results/test/<...>/, and refuses
                 to run again once a test run exists, unless --force (and the phrase again).
                 Do not tune prompts or code on test results.
  --rescore DIR  re-score saved answers (no LLM, no tools), e.g. after the gold file is corrected.

Each run folder holds: run.json (timestamp, git SHA, model, split, file hashes, status),
<system>.jsonl (per question: the Answer with citations and verifier report, the numeric and
qualitative claims, the score), metrics.json, report.md.

Runtime errors from the LLM or the embedder (Ollama down, timeout) are recorded per question as
"error" and the run goes on; any other exception is a bug and stops the run.
"""
import argparse
import functools
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from erp.agent.answer_schema import Answer
from erp.agent.llm import LLMError, call_llm, load_agent_config
from erp.agent.loop import answer_question, open_env
from erp.config import REPO
from erp.eval.baseline import naive_rag_answer
from erp.eval.claims import extract_claims
from erp.eval.metrics import render_report, summarize
from erp.eval.questions import QUESTIONS_PATH, EvalQuestion, load_questions
from erp.eval.score import QuestionScore, load_eval_config, score_question
from erp.ingest.embed import EmbeddingError
from erp.version import code_version

SYSTEMS = ("full", "full_no_verifier", "naive_rag")


def _sha256(path) -> str | None:
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def answer_with(system: str, q: EvalQuestion, env, llm_fn, cfg: dict, ecfg: dict) -> Answer:
    if system == "full":
        return answer_question(q.question, env, llm_fn, cfg=cfg)
    if system == "full_no_verifier":
        return answer_question(q.question, env, llm_fn, cfg=cfg, verify=False)
    if system == "naive_rag":
        return naive_rag_answer(q.question, ticker=env.ticker, collection=env.collection, embed_fn=env.embed_fn,
                                llm_fn=llm_fn, top_k=ecfg["baseline"]["top_k"] or env.search_top_k,
                                passage_chars=env.passage_chars)
    raise ValueError(f"unknown system {system!r}")


def _error_answer(q: EvalQuestion, env, e: Exception) -> Answer:
    return Answer(question=q.question, ticker=env.ticker, answer_text=f"ERROR: {type(e).__name__}: {e}",
                  numbers_used=[], citations=[], refused=True, refusal_reason="harness_error", composed_by="refusal")


def record_for(system: str, q: EvalQuestion, answer: Answer, seconds: float, cfg: dict, ecfg: dict) -> dict:
    numeric, qualitative = extract_claims(answer, cfg)
    score = score_question(q, answer, ecfg, cfg, claims=(numeric, qualitative))
    return {"system": system, "question_id": q.id, "category": q.category, "split": q.split,
            "question": q.question, "gold_answer": q.gold_answer,
            "gold_sources": [g.model_dump() for g in q.gold_sources], "seconds": round(seconds, 2),
            "answer": answer.model_dump(mode="json"),
            "numeric_claims": [c.model_dump() for c in numeric],
            "qualitative_claims": [c.model_dump() for c in qualitative],
            "score": score.model_dump()}


def _new_run_dir(parent: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{stamp}_{code_version()[:8]}"
    out, n = parent / base, 1
    while out.exists():
        n += 1
        out = parent / f"{base}_{n}"
    out.mkdir(parents=True)
    return out


def _write_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, default=str) + "\n")


def _finish(out: Path, meta: dict, scores: dict[str, list[QuestionScore]], ecfg: dict) -> dict:
    metrics = {s: summarize(v) for s, v in scores.items()}
    _write_json(out / "metrics.json", metrics)
    report = render_report(meta, metrics, ecfg["systems"])
    (out / "report.md").write_text(report + "\n")
    print(report)
    return metrics


def rescore(run_dir: Path, ecfg: dict, cfg: dict, questions_path: Path | None = None) -> Path:
    meta = json.loads((run_dir / "run.json").read_text())
    qpath = Path(questions_path or REPO / meta["questions_path"])
    questions = {q.id: q for q in load_questions(qpath)}
    scores = {}
    for system in meta["systems"]:
        path = run_dir / f"{system}.jsonl"
        if not path.exists():
            continue
        records = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
        rewritten, scores[system] = [], []
        for r in records:
            answer = Answer.model_validate(r["answer"])
            new = record_for(system, questions[r["question_id"]], answer, r["seconds"], cfg, ecfg)
            rewritten.append(new)
            scores[system].append(QuestionScore(**new["score"]))
        path.write_text("".join(json.dumps(x) + "\n" for x in rewritten))
    meta.update(rescored_at=datetime.now().isoformat(timespec="seconds"),
                rescored_git_sha=code_version(), rescored_questions_sha256=_sha256(qpath))
    _write_json(run_dir / "run.json", meta)
    _finish(run_dir, meta, scores, ecfg)
    return run_dir


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run the eval on the dev split (default) or, once, the test split.")
    p.add_argument("--test", action="store_true", help="run the frozen test split (asks for a typed confirmation)")
    p.add_argument("--force", action="store_true", help="with --test: run again although a test run exists")
    p.add_argument("--systems", nargs="+", choices=SYSTEMS, help="dev only: which systems (default: all)")
    p.add_argument("--ids", nargs="+", help="dev only: just these question ids")
    p.add_argument("--rescore", type=Path, help="re-score a saved run folder (no LLM calls)")
    p.add_argument("--db", default=str(REPO / "data" / "db" / "sample.sqlite"))
    p.add_argument("--dcf-assumptions", default=None, help="path relative to the repo (default from config)")
    p.add_argument("--model", default=None, help="override the configured model (recorded in run.json)")
    return p


def main(argv=None, *, input_fn=input, make_env=None, llm_fn=None, results_root: Path | None = None,
         questions_path: Path | None = None) -> Path:
    parser = _parser()
    args = parser.parse_args(argv)
    cfg, ecfg = load_agent_config(), load_eval_config()
    root = Path(results_root or REPO / ecfg["results_dir"])
    if args.rescore:
        return rescore(args.rescore, ecfg, cfg, questions_path)

    split = "test" if args.test else "dev"
    if args.force and not args.test:
        parser.error("--force only applies to --test")
    if args.test and (args.systems or args.ids):
        parser.error("the test split always runs every system on every test question, in one go")
    systems = list(args.systems or SYSTEMS)

    if args.test:
        earlier = sorted(d.name for d in (root / "test").glob("*") if (d / "run.json").exists())
        if earlier and not args.force:
            sys.exit(f"The test split has already been run ({', '.join(earlier)}). It runs once. "
                     "Use --force only for a reason you can defend (e.g. the first run crashed).")
        phrase = ecfg["test_confirmation_phrase"]
        typed = input_fn(f"This runs the FROZEN TEST SPLIT (do not tune anything on its results). "
                         f"Type '{phrase}' to continue: ")
        if typed.strip() != phrase:
            sys.exit("Confirmation did not match; nothing was run.")

    qpath = Path(questions_path or QUESTIONS_PATH)
    questions = load_questions(qpath, split=split)
    if args.ids:
        unknown = set(args.ids) - {q.id for q in questions}
        if unknown:
            parser.error(f"not in the {split} split: {sorted(unknown)}")
        questions = [q for q in questions if q.id in args.ids]
    env = make_env() if make_env else open_env(args.db, args.dcf_assumptions, cfg)
    if llm_fn is None:
        llm_fn = functools.partial(call_llm, model=args.model) if args.model else call_llm

    out = _new_run_dir(root / split)
    facts = env.conn.execute("SELECT COUNT(*), COALESCE(SUM(verified_by IS NULL), 0) FROM fact").fetchone()
    meta = {
        "timestamp": datetime.now().isoformat(timespec="seconds"), "git_sha": code_version(),
        "model": args.model or cfg["llm"]["model"], "temperature": cfg["llm"]["temperature"],
        "seed": cfg["llm"]["seed"], "split": split, "systems": systems, "question_ids": [q.id for q in questions],
        "questions_path": str(qpath.relative_to(REPO)) if qpath.is_relative_to(REPO) else str(qpath),
        "questions_sha256": _sha256(qpath), "dcf_assumptions": str(env.dcf_assumptions),
        "dcf_assumptions_sha256": _sha256(env.dcf_assumptions), "db": args.db if not make_env else "(test env)",
        "facts_unverified": f"{facts[1]} of {facts[0]}",
        "gold_pending_author_check": f"{sum('pending' in q.entered_by for q in questions)} of {len(questions)}",
        "argv": list(argv) if argv is not None else sys.argv[1:], "status": "started",
    }
    _write_json(out / "run.json", meta)

    scores, models = {}, set()
    for system in systems:
        scores[system] = []
        with open(out / f"{system}.jsonl", "w") as f:
            for q in questions:
                start = time.monotonic()
                try:
                    answer = answer_with(system, q, env, llm_fn, cfg, ecfg)
                except (LLMError, EmbeddingError) as e:
                    answer = _error_answer(q, env, e)
                rec = record_for(system, q, answer, time.monotonic() - start, cfg, ecfg)
                f.write(json.dumps(rec) + "\n")
                f.flush()
                scores[system].append(QuestionScore(**rec["score"]))
                if answer.model:
                    models.add(answer.model)
                s = rec["score"]
                print(f"[{system}] {q.id} {rec['seconds']:6.1f}s behaviour={s['behavior']}"
                      f"{'' if s['behavior_ok'] else ' (WRONG)'} numeric_correct={s['numeric_correct']}",
                      file=sys.stderr)

    meta.update(status="finished", finished_at=datetime.now().isoformat(timespec="seconds"),
                models_reported=sorted(models))
    _write_json(out / "run.json", meta)
    _finish(out, meta, scores, ecfg)
    print(f"\nSaved to {out}", file=sys.stderr)
    return out
