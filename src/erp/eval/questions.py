"""Read the eval question file (plan 6.1). Read only: nothing in the harness writes to it.

eval/questions.jsonl (v1) and eval/questions_v1_1.jsonl (v1.1) are author-owned. Each line is one
question with its gold answer, split (dev | test) and expected_behavior (answer | refuse |
not_available). A malformed file is refused as a whole, so a run never scores against half a gold set.

Categories: A fact, B period/unit, C ratio, D DCF, E qualitative, F mixed, G guardrail, and (v1.1)
H history/trend: one question that needs several numbers across years.
"""
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from erp.config import REPO

QUESTIONS_PATH = REPO / "eval" / "questions.jsonl"


class QuestionFileError(ValueError):
    pass


class GoldSource(BaseModel):
    source_id: int
    page: int


class EvalQuestion(BaseModel):
    id: str
    category: Literal["A", "B", "C", "D", "E", "F", "G", "H"]
    question: str
    gold_answer: str
    gold_value: float | None
    gold_unit: str | None
    gold_period: str | None
    tolerance: float | None
    gold_sources: list[GoldSource]
    must_refuse: bool
    split: Literal["dev", "test"]
    expected_behavior: Literal["answer", "refuse", "not_available"]
    notes: str = ""
    entered_by: str = ""


def question_set(path: Path, default: Path = QUESTIONS_PATH) -> tuple[str, str | None]:
    """(label, results subfolder) for a question file. The original file (v1) keeps the original
    layout, results/dev and results/test (subfolder None). Any other file is labelled by its name
    without "questions_" (questions_v1_1.jsonl -> v1_1) and gets results/<label>/dev and
    results/<label>/test, so its runs, and its one-time test-split gate, are its own."""
    if Path(path).resolve() == Path(default).resolve():
        return "v1", None
    label = Path(path).stem.removeprefix("questions_")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", label) or label in ("dev", "test", "v1"):
        raise ValueError(f"cannot use {Path(path).name!r} as a question set name (label {label!r}); rename the file")
    return label, label


def load_questions(path: Path = QUESTIONS_PATH, split: str | None = None) -> list[EvalQuestion]:
    questions, problems, seen = [], [], set()
    for n, line in enumerate(Path(path).read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            missing = [f for f, info in EvalQuestion.model_fields.items() if info.is_required() and f not in raw]
            if missing:
                raise QuestionFileError(f"missing field(s) {missing}")
            question = EvalQuestion(**raw)
        except (json.JSONDecodeError, ValidationError, QuestionFileError) as e:
            problems.append(f"line {n}: {e}")
            continue
        if question.must_refuse != (question.expected_behavior == "refuse"):
            problems.append(f"line {n} ({question.id}): must_refuse={question.must_refuse} disagrees with "
                            f"expected_behavior={question.expected_behavior}")
        if question.gold_value is not None and (question.gold_unit is None or question.tolerance is None):
            problems.append(f"line {n} ({question.id}): gold_value needs gold_unit and tolerance")
        if question.id in seen:
            problems.append(f"line {n}: duplicate id {question.id}")
        seen.add(question.id)
        questions.append(question)
    if problems:
        raise QuestionFileError(f"{path}: " + "; ".join(problems))
    return [q for q in questions if split is None or q.split == split]
