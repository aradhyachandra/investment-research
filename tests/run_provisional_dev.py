"""Live run of the agent on the PROVISIONAL dev questions. Not a pytest test (needs Ollama,
the real SQLite build and the real Chroma index).

PROVISIONAL: the questions are Claude's (tests/provisional_dev_questions.jsonl), not the
author's eval set (P0.4). Use the numbers as a plumbing check, not as a result.

  --route-only   step 1 only, for comparing models' routing accuracy quickly
  --e2e-only     only the questions marked "e2e": true (the M5 acceptance ten)
  --model NAME   override the configured model (repeatable: one run per model)
  --out FILE     save every Answer as JSON lines (default: print only)

Run:
  PYTHONPATH=src:tests .venv/bin/python tests/run_provisional_dev.py --route-only --model qwen2.5:3b --model llama3.2
  PYTHONPATH=src:tests .venv/bin/python tests/run_provisional_dev.py --e2e-only --out /tmp/m5_answers.jsonl
"""
import argparse
import functools
import json
import time
from pathlib import Path

from erp.agent.llm import call_llm, load_agent_config
from erp.agent.loop import answer_question, open_env
from erp.agent.route_score import RoutingTally, score_route
from erp.agent.router import build_catalog, route
from erp.config import REPO

QUESTIONS = Path(__file__).parent / "provisional_dev_questions.jsonl"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--route-only", action="store_true")
    p.add_argument("--e2e-only", action="store_true")
    p.add_argument("--model", action="append")
    p.add_argument("--db", default=str(REPO / "data" / "db" / "sample.sqlite"))
    p.add_argument("--dcf-assumptions", default=None)
    p.add_argument("--out", default=None)
    args = p.parse_args()

    cfg = load_agent_config()
    questions = [json.loads(x) for x in QUESTIONS.read_text().splitlines() if x.strip()]
    if args.e2e_only:
        questions = [q for q in questions if q["e2e"]]
    env = open_env(args.db, args.dcf_assumptions, cfg)
    out = open(args.out, "w") if args.out else None

    for model in args.model or [cfg["llm"]["model"]]:
        llm_fn = functools.partial(call_llm, model=model)
        tally, seconds = RoutingTally(), 0.0
        print(f"\n===== model {model} ({'route only' if args.route_only else 'end to end'}) =====")
        for q in questions:
            start = time.monotonic()
            if args.route_only:
                plan = route(q["question"], build_catalog(env.conn, env.ticker, env.dcf_assumptions), llm_fn,
                             max_calls=cfg["router"]["max_tool_calls"])
                answer = None
            else:
                answer = answer_question(q["question"], env, llm_fn, cfg=cfg)
                plan = answer.route
            took = time.monotonic() - start
            seconds += took
            s = score_route(plan, q["expected_route"])
            tally.add(q["id"], s)
            calls = "; ".join(f"{c.tool}({', '.join(f'{k}={v}' for k, v in c.args.items())})" for c in plan.calls)
            shown = f"REFUSE[{plan.refusal_reason}]" if plan.refuse else (calls or plan.question_type)
            print(f"{q['id']} {'OK ' if s.full_ok else ('TOOL' if s.tool_ok else 'BAD')} {took:5.1f}s  {shown}")
            if answer is not None:
                print(f"   answer ({answer.composed_by}): {answer.answer_text[:400]!r}")
                print(f"   numbers_used: {[(n.display, n.evidence_id) for n in answer.numbers_used]}")
                print(f"   citations: {[(c.evidence_id, c.page, c.period, c.basis) for c in answer.citations][:8]}")
                if answer.warnings:
                    print(f"   warnings: {answer.warnings}")
                if out:
                    out.write(json.dumps({"id": q["id"], "model": model, "seconds": round(took, 1),
                                          "answer": answer.model_dump(mode="json")}) + "\n")
        print(f"--- {model}: {tally.summary()}; total {seconds:.0f}s")
    if out:
        out.close()


if __name__ == "__main__":
    main()
