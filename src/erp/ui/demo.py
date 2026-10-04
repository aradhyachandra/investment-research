"""--demo mode: load saved Answer objects from an eval run folder, so the UI works with no model.

An eval run folder (eval/run_eval.py, M7) holds one <system>.jsonl per system; each line has
question_id, question and the full Answer under "answer". Read only.
"""
import json
from pathlib import Path

from pydantic import BaseModel

from erp.agent.answer_schema import Answer


class SavedAnswer(BaseModel):
    question_id: str
    answer: Answer


class DemoError(RuntimeError):
    pass


def newest_run(results_dir) -> Path:
    """The newest run folder holding saved answers (folder names start with a sortable timestamp)."""
    root = Path(results_dir)
    runs = sorted(p for p in root.iterdir() if p.is_dir() and any(p.glob("*.jsonl"))) if root.is_dir() else []
    if not runs:
        raise DemoError(f"no saved eval runs in {root}; run eval/run_eval.py first or pass a run folder")
    return runs[-1]


def resolve_run(path) -> Path:
    """A run folder itself, or a results folder whose newest run is used."""
    p = Path(path)
    if p.is_dir() and any(p.glob("*.jsonl")):
        return p
    return newest_run(p)


def load_saved_answers(run_dir, system: str = "full") -> list[SavedAnswer]:
    path = Path(run_dir) / f"{system}.jsonl"
    if not path.exists():
        raise DemoError(f"{path} not found (systems saved there: "
                        f"{', '.join(sorted(p.stem for p in Path(run_dir).glob('*.jsonl'))) or 'none'})")
    out = []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        try:
            out.append(SavedAnswer(question_id=row["question_id"], answer=Answer.model_validate(row["answer"])))
        except (KeyError, ValueError) as e:
            raise DemoError(f"{path} line {n} is not a saved Answer: {e}") from e
    return out
