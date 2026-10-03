# Prompts to paste into the coding tool

## Session 1 (Week 1, Day 1: M1)

```
Read CLAUDE.md and PROJECT_PLAN.md fully. Then do Milestone M1 only (Section 9; Week 1, Day 1 in Section 2.5).

Scope:
- Repo skeleton as in Section 8.2 (create only the folders needed for M1).
- SQLite schema from Section 4.3, including source_page_label and the generated_sample doc_type.
- A loader that reads a CSV of facts from data/sample/ and writes to SQLite.
- Load-time validation checks from Section 4.4 and design rules from Section 4.1 (units match the metric's canonical unit, value = reported_value * conversion_factor, every row has a source page, plausibility bands).
- pytest tests written first. Include tests where deliberately bad rows are rejected (wrong unit, missing page, value that does not match the conversion).

Fixtures: about 10 real TCS facts that I typed into data/sample/ (do not change them and do not invent any numbers). If the CSV format I used does not match the schema, tell me what to change instead of guessing.

Rules: Section 8 and CLAUDE.md. Do not start M2. When done, update PROGRESS.md, write a short plain-language note in docs/ explaining what you built, and tell me in a few sentences what to check before I commit.
```

## Template for later sessions

```
Read CLAUDE.md, PROJECT_PLAN.md and PROGRESS.md. Do Milestone M<N> only, using its acceptance test in Section 9 as the definition of done. Tests first. Do not touch gold files or my data files. Mark uncertain things TO VERIFY. When done, update PROGRESS.md, add a plain-language note in docs/, and list what I should review before moving on.
```

## Before each session checklist
- `git status` is clean (commit or stash first).
- `ANTHROPIC_API_KEY` is not set in this shell.
- You know what you will explain back at the end of the session.
