"""Read the eval question file (plan 6.1). Read only: nothing in the harness writes to it.

eval/questions.jsonl is author-owned. Each line is one question with its gold answer, split
(dev | test) and expected_behavior (answer | refuse | not_available). A malformed file is
refused as a whole, so a run never scores against half a gold set.
"""
import json
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
    category: Literal["A", "B", "C", "D", "E", "F", "G"]
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
