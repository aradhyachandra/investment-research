"""Sample ~20 qualitative claims from a saved run into a CSV for hand labelling (M7, plan 6.2).

  PYTHONPATH=src .venv/bin/python eval/sample_qualitative.py eval/results/dev/<run>
  PYTHONPATH=src .venv/bin/python eval/sample_qualitative.py eval/results/dev/<run> --systems full naive_rag
  PYTHONPATH=src .venv/bin/python eval/sample_qualitative.py --tally eval/results/dev/<run>/qualitative_labels.csv

Fill the `supports` column with yes / partly / no (see src/erp/eval/qualitative.py).
"""
import argparse
import json
from pathlib import Path

from erp.eval.qualitative import sample_claims, tally_labels, write_sample_csv
from erp.eval.score import load_eval_config


def main():
    cfg = load_eval_config()["qualitative_sample"]
    p = argparse.ArgumentParser()
    p.add_argument("run_dir", nargs="?", type=Path)
    p.add_argument("--systems", nargs="+", default=["full"])
    p.add_argument("--n", type=int, default=cfg["n"])
    p.add_argument("--seed", type=int, default=cfg["seed"])
    p.add_argument("--out", type=Path, default=None, help="default: <run_dir>/qualitative_labels.csv")
    p.add_argument("--tally", type=Path, help="count the labels in a filled-in CSV")
    args = p.parse_args()
    if args.tally:
        counts = tally_labels(args.tally)
        total = sum(counts.values())
        for label, k in sorted(counts.items()):
            print(f"{label}: {k} of {total}")
        return
    if args.run_dir is None:
        p.error("give a run folder, or --tally CSV")
    records = [json.loads(x) for s in args.systems
               for x in (args.run_dir / f"{s}.jsonl").read_text().splitlines() if x.strip()]
    rows = sample_claims(records, n=args.n, seed=args.seed)
    out = args.out or args.run_dir / "qualitative_labels.csv"
    if out.exists():
        p.error(f"{out} exists (it may hold your labels); pass --out for a new file")
    write_sample_csv(rows, out)
    print(f"{len(rows)} claims written to {out} (from {len(records)} answers, systems {args.systems}, seed {args.seed})")


if __name__ == "__main__":
    main()
