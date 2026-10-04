"""Results tables for the README (M9), built only from saved eval runs.

Reads eval/results/<split>/<run>/run.json + metrics.json (written by eval/run_eval.py) and prints
markdown tables of "k of n" counts for the full system, verifier off and naive RAG, dev and test
separately. Nothing here is typed by hand: if a split has no finished run, the table says so.

A run whose git SHA ends in "-dirty" was made from uncommitted code; the table says that too.
"""
import hashlib
import json
from pathlib import Path

SYSTEMS = [("full", "Full system"), ("full_no_verifier", "Verifier off"), ("naive_rag", "Naive RAG")]

# (section in metrics.json, key, row label). Order = row order in the table.
ROWS = [
    ("headline", "numeric_accuracy", "Numeric accuracy (questions with a gold value)"),
    ("headline", "citation_numeric_gold_claims", "Gold-matching numeric claims citing a gold page"),
    ("headline", "citation_numeric", "All numeric claims citing a gold page"),
    ("secondary", "behavior_all", "Behaviour correct (answer / refuse / not available)"),
    ("secondary", "refusal_G", "Guardrail questions refused correctly (G)"),
    ("secondary", "over_refusal", "Over-refusal (refused an answerable question)"),
    ("secondary", "routing_tools", "Routing: right tools"),
    ("secondary", "routing_tools_period", "Routing: right tools and period"),
    ("secondary", "unsupported_claims", "Unsupported numeric claims"),
    ("secondary", "verifier_rejections", "Verifier rejections (template answer shipped)"),
    ("secondary", "advice_language", "Answers with advice words"),
    ("secondary", "errors", "Errors"),
]

START, END = "<!-- results:start -->", "<!-- results:end -->"


def finished_runs(split_dir: Path) -> list[Path]:
    """Run folders with a finished run.json and a metrics.json, oldest first (names start with a timestamp)."""
    if not split_dir.is_dir():
        return []
    out = []
    for p in sorted(split_dir.iterdir()):
        if (p / "run.json").is_file() and (p / "metrics.json").is_file():
            if json.loads((p / "run.json").read_text()).get("status") == "finished":
                out.append(p)
    return out


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _cell(metrics: dict, system: str, section: str, key: str) -> str:
    value = (metrics.get(system) or {}).get(section, {}).get(key)
    return value["text"] if value else "n/a"


def run_provenance(run_dir: Path, questions_path: Path | None) -> list[str]:
    meta = json.loads((run_dir / "run.json").read_text())
    sha = meta.get("git_sha", "unknown")
    lines = [
        f"- Run `{run_dir.name}`, model `{meta.get('model')}`, temperature {meta.get('temperature')}, "
        f"seed {meta.get('seed')}, {len(meta.get('question_ids', []))} questions.",
        f"- Code: git `{sha[:7]}{'-dirty' if sha.endswith('-dirty') else ''}`"
        + (" (**dirty tree**: made from uncommitted code; re-run on committed code before quoting)"
           if sha.endswith("-dirty") else " (committed code)") + ".",
        f"- Facts unverified by a human: {meta.get('facts_unverified', 'not recorded')}. "
        f"Gold answers pending author sign-off: {meta.get('gold_pending_author_check', 'not recorded')}.",
    ]
    if meta.get("rescored_at"):
        lines.append(f"- Re-scored without the model on {meta['rescored_at']} "
                     f"(git `{str(meta.get('rescored_git_sha', 'unknown'))[:7]}`).")
    if questions_path is not None:
        current = _sha256(questions_path)
        used = meta.get("rescored_questions_sha256") or meta.get("questions_sha256")
        if current and used and current != used:
            lines.append("- **Warning:** `eval/questions.jsonl` has changed since this run was scored.")
    return lines


def split_section(results_root: Path, split: str, questions_path: Path | None) -> str:
    runs = finished_runs(results_root / split)
    title = f"### {split.capitalize()} split"
    if not runs:
        return f"{title}\n\n{split.capitalize()} split not yet run."
    latest = runs[-1]
    metrics = json.loads((latest / "metrics.json").read_text())
    header = "| Metric | " + " | ".join(label for _, label in SYSTEMS) + " |"
    sep = "|---|" + "---|" * len(SYSTEMS)
    rows = [f"| {label} | " + " | ".join(_cell(metrics, s, sec, key) for s, _ in SYSTEMS) + " |"
            for sec, key, label in ROWS]
    parts = [title, "", "Latest finished run:", "", *run_provenance(latest, questions_path), "",
             header, sep, *rows]
    if len(runs) > 1:
        parts += ["", f"All finished {split} runs (the table shows the last one):", ""]
        for r in runs:
            sha = json.loads((r / "run.json").read_text()).get("git_sha", "unknown")
            dirty = "dirty tree" if sha.endswith("-dirty") else "committed"
            full = json.loads((r / "metrics.json").read_text()).get("full", {})
            acc = full.get("headline", {}).get("numeric_accuracy")
            parts.append(f"- `{r.name}`: git `{sha[:7]}`, {dirty}; full-system numeric accuracy "
                         f"{acc['text'] if acc else 'n/a'}")
    return "\n".join(parts)


def results_markdown(results_root: Path, questions_path: Path | None = None) -> str:
    note = ("_Generated by `scripts/make_results_table.py` from `eval/results/` (gitignored). "
            "Counts are \"k of n\"; n differs per row because each metric only counts the questions "
            "or claims it applies to. Do not edit by hand._")
    return "\n\n".join([note, split_section(results_root, "dev", questions_path),
                        split_section(results_root, "test", questions_path)])


def replace_block(text: str, block: str) -> str:
    """Put `block` between the results markers in `text` (markers must already exist, once each)."""
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
        raise ValueError(f"README must contain {START} ... {END} exactly once")
    head, rest = text.split(START)
    _, tail = rest.split(END)
    return f"{head}{START}\n{block}\n{END}{tail}"
