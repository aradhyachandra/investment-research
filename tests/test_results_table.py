"""M9: README results tables come only from saved eval runs."""
import json

import pytest

from erp.eval.results_table import END, START, replace_block, results_markdown


def _run(root, split, name, sha, full_acc=(10, 14), status="finished"):
    d = root / split / name
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps({
        "git_sha": sha, "model": "m", "temperature": 0, "seed": 0, "question_ids": ["a", "b"],
        "status": status, "facts_unverified": "1 of 1", "gold_pending_author_check": "2 of 2",
        "questions_sha256": "x"}))
    k, n = full_acc
    acc = {"k": k, "n": n, "text": f"{k} of {n}"}
    (d / "metrics.json").write_text(json.dumps({
        "full": {"headline": {"numeric_accuracy": acc}, "secondary": {}},
        "naive_rag": {"headline": {"numeric_accuracy": {"k": 1, "n": 14, "text": "1 of 14"}},
                      "secondary": {"routing_tools": None}}}))
    return d


def test_no_results_says_not_run(tmp_path):
    md = results_markdown(tmp_path / "missing")
    assert "Dev split not yet run." in md and "Test split not yet run." in md
    assert " of " not in md.replace('"k of n"', "")


def test_dev_numbers_come_from_latest_finished_run_and_test_missing(tmp_path):
    _run(tmp_path, "dev", "20260101-000000_a", "a" * 40 + "-dirty", (9, 14))
    _run(tmp_path, "dev", "20260102-000000_b", "b" * 40, (10, 14))
    _run(tmp_path, "dev", "20260103-000000_c", "c" * 40, (99, 99), status="started")  # unfinished
    md = results_markdown(tmp_path)
    dev, test = md.split("### Test split")
    assert "| Numeric accuracy (questions with a gold value) | 10 of 14 | n/a | 1 of 14 |" in dev
    assert "99 of 99" not in md
    assert "(committed code)" in dev
    assert "`20260101-000000_a`: git `aaaaaaa`, dirty tree" in dev
    assert "Test split not yet run." in test


def test_dirty_run_is_flagged(tmp_path):
    _run(tmp_path, "dev", "20260101-000000_a", "a" * 40 + "-dirty")
    assert "dirty tree" in results_markdown(tmp_path)


def test_changed_questions_file_is_warned(tmp_path):
    _run(tmp_path, "dev", "20260101-000000_a", "a" * 40)
    q = tmp_path / "questions.jsonl"
    q.write_text("{}\n")
    assert "has changed since this run" in results_markdown(tmp_path, q)


def test_replace_block():
    text = f"top\n{START}\nold\n{END}\nbottom\n"
    assert replace_block(text, "new") == f"top\n{START}\nnew\n{END}\nbottom\n"
    with pytest.raises(ValueError):
        replace_block("no markers", "new")
