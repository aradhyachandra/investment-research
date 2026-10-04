"""Print (or write into README.md) the eval results tables, built only from eval/results/.

    PYTHONPATH=src .venv/bin/python scripts/make_results_table.py            # print
    PYTHONPATH=src .venv/bin/python scripts/make_results_table.py --readme   # update README.md

The README block between <!-- results:start --> and <!-- results:end --> is replaced. If a split
has no finished run, the block says "... split not yet run" instead of numbers.
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from erp.eval.results_table import replace_block, results_markdown  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", default=str(REPO / "eval" / "results"))
    ap.add_argument("--questions", default=str(REPO / "eval" / "questions.jsonl"))
    ap.add_argument("--readme", action="store_true", help="write the tables into README.md")
    args = ap.parse_args(argv)
    block = results_markdown(Path(args.results), Path(args.questions))
    if args.readme:
        path = REPO / "README.md"
        path.write_text(replace_block(path.read_text(), block))
        print(f"updated {path.relative_to(REPO)}")
    else:
        print(block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
