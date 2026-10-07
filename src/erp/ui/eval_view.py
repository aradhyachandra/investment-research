"""Evaluation tab (M8.1): the headline rows of the latest saved eval runs, for a chart and a "k of n" table.

Reads eval/results/<split>/<run>/run.json + metrics.json (written by eval/run_eval.py), the same files and
the same "latest finished run" rule as the README results block (erp.eval.results_table). Nothing is typed
in. The only number made here is k / n, used for the chart's bar length; the table shows "k of n".
The caveats are read from the README, so the page and the README cannot drift apart.
"""
import json
from pathlib import Path

from pydantic import BaseModel

from erp.eval.results_table import finished_runs

SYSTEMS = [("full", "Full system"), ("naive_rag", "Naive RAG")]
# (section in metrics.json, key, label). Order = chart and table order.
HEADLINE_ROWS = [
    ("headline", "numeric_accuracy", "Numeric accuracy"),
    ("headline", "citation_numeric_gold_claims", "Gold-matching citations"),
    ("secondary", "behavior_all", "Behaviour correct"),
    ("secondary", "unsupported_claims", "Unsupported numeric claims (lower is better)"),
]
CAVEATS_START = "Read it with these caveats:"
CAVEATS_END = "<!-- results:start -->"


class EvalRow(BaseModel):
    metric: str
    system: str
    k: int | None
    n: int | None
    text: str                         # "k of n", or "n/a"
    share: float | None               # k / n for the chart; None when n is 0 or the row is missing


class SplitResult(BaseModel):
    split: str
    run_name: str
    git_sha: str
    dirty: bool
    model: str | None
    questions: int
    rows: list[EvalRow]


def _row(metrics: dict, system: str, label: str, section: str, key: str, metric: str) -> EvalRow:
    m = (metrics.get(system) or {}).get(section, {}).get(key)
    if not m:
        return EvalRow(metric=metric, system=label, k=None, n=None, text="n/a", share=None)
    return EvalRow(metric=metric, system=label, k=m["k"], n=m["n"], text=m["text"],
                   share=m["k"] / m["n"] if m["n"] else None)


def latest_results(results_root) -> list[SplitResult]:
    """Latest finished run per split (dev, then test). Splits with no finished run are left out."""
    out = []
    for split in ("dev", "test"):
        runs = finished_runs(Path(results_root) / split)
        if not runs:
            continue
        run = runs[-1]
        meta = json.loads((run / "run.json").read_text())
        metrics = json.loads((run / "metrics.json").read_text())
        sha = meta.get("git_sha", "unknown")
        rows = [_row(metrics, s, label, section, key, metric)
                for section, key, metric in HEADLINE_ROWS for s, label in SYSTEMS]
        out.append(SplitResult(split=split, run_name=run.name, git_sha=sha[:7], dirty=sha.endswith("-dirty"),
                               model=meta.get("model"), questions=len(meta.get("question_ids", [])), rows=rows))
    return out


def readme_caveats(readme_path) -> list[str]:
    """The bullet list under 'Read it with these caveats:' in README section 7, one string per bullet."""
    path = Path(readme_path)
    if not path.is_file():
        return []
    text = path.read_text()
    if CAVEATS_START not in text:
        return []
    block = text.split(CAVEATS_START, 1)[1].split(CAVEATS_END, 1)[0]
    bullets = []
    for line in block.splitlines():
        if line.startswith("- "):
            bullets.append(line[2:].strip())
        elif line.startswith("  ") and bullets:
            bullets[-1] += " " + line.strip()
    return bullets
