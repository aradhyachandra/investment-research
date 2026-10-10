"""Print (or write into README.md) the eval results tables, built only from eval/results/.

    PYTHONPATH=src .venv/bin/python scripts/make_results_table.py            # print (v1 only)
    PYTHONPATH=src .venv/bin/python scripts/make_results_table.py --sets v1 v1_1   # side by side
    PYTHONPATH=src .venv/bin/python scripts/make_results_table.py --readme   # update README.md

The README block between <!-- results:start --> and <!-- results:end --> is replaced. If a split
has no finished run, the block says "... split not yet run" instead of numbers. Question sets
come from config/eval.yaml (question_sets); each set's results folder follows run_eval.py's rule.
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from erp.eval.questions import question_set  # noqa: E402
from erp.eval.results_table import QuestionSet, replace_block, results_markdown  # noqa: E402
from erp.eval.score import load_eval_config  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    known = load_eval_config()["question_sets"]
    ap.add_argument("--results", default=str(REPO / "eval" / "results"))
    ap.add_argument("--questions", default=str(REPO / "eval" / "questions.jsonl"),
                    help="the v1 question file (only without --sets)")
    ap.add_argument("--sets", nargs="+", choices=list(known), default=None,
                    help="question sets to show side by side, e.g. --sets v1 v1_1 (default: v1 only)")
    ap.add_argument("--readme", action="store_true", help="write the tables into README.md")
    args = ap.parse_args(argv)
    root = Path(args.results)
    sets = None
    if args.sets:
        sets = []
        for label in args.sets:
            path = REPO / known[label]
            _, subdir = question_set(path)
            sets.append(QuestionSet(label, path, root / subdir if subdir else root))
    block = results_markdown(root, Path(args.questions), sets=sets)
    if args.readme:
        path = REPO / "README.md"
        path.write_text(replace_block(path.read_text(), block))
        print(f"updated {path.relative_to(REPO)}")
    else:
        print(block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
