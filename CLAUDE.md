# Project instructions (read first)

This repo is an AI-powered equity research platform for Indian equities (v1: TCS only).
**Read `PROJECT_PLAN.md` fully before doing anything. Then read `PROGRESS.md` (create it if missing).**

Core principle: **AI interprets, code calculates, sources prove.**

## How to work
1. Work on **one milestone per session**, in the order given in PROJECT_PLAN.md (Section 9, and Section 2.5 for Week 1). Do not start the next milestone unprompted.
2. **Tests first** where the plan names an acceptance test. A milestone is done only when its test passes.
3. Keep changes small. Prefer plain, readable Python over clever abstractions. Pin dependencies in `requirements.txt`.
4. At the end of every session: update `PROGRESS.md` (done, next, known issues, decisions) and write a short plain-language note in `docs/` on what you built and why, so the author can explain it in their own words.

## Hard rules
- **No LLM arithmetic.** All calculation lives in deterministic Python (`tools/`, `dcf/`). The LLM only routes and explains.
- **Never invent** financial figures, assumptions, page numbers or sources. If something is missing, say so.
- **Do not edit** `eval/questions.jsonl`, anything in `data/manual/`, `data/sample/`, or `dcf_inputs.yaml` unless the author asks.
- **No network scraping.** Data comes from files the author placed in `data/`.
- **Never commit** anything from `data/raw/` (private data repo checkout) or any secret. Secrets go in `.env` (gitignored). Do not set or use `ANTHROPIC_API_KEY`.
- LLM-generated notes live only in `data/sample/generated/` and never enter SQLite, the eval, or the public repo.
- The runtime LLM is called through **one function**, model name from config.
- Company-specific details (metrics, units, assumptions, valuation method) go in config files, not code.
- Mark anything uncertain (library behavior, data semantics, licensing) as `TO VERIFY` in comments and `NOTES.md`. Do not guess.
- **Not investment advice.** Never produce buy/sell/hold language, target prices, or "undervalued/overvalued" verdicts.

## If something in PROJECT_PLAN.md seems wrong or conflicts with reality
Stop and tell the author in plain language, with your reasoning, before changing course.
