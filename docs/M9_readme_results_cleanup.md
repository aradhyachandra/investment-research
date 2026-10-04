# M9: README, results table, demo script, cleanup

## What was built

**README.md.** Follows the plan's Section 12 outline (13 sections). The top says, before anything
else: not investment advice, v1 is TCS only, and "AI interprets, code calculates, sources prove".
Section 8, "How this was built and what is not verified", lists everything a reader should not take
on trust: AI-drafted gold answers with no author sign-off yet, AI-drafted DCF assumptions with no
finance review, AI-read facts with no human check, the small local model and its licence question,
no author-written notes yet, and the known weaknesses.

**Results table, generated, never typed.** `scripts/make_results_table.py` (logic in
`src/erp/eval/results_table.py`) reads `eval/results/<split>/<run>/run.json` and `metrics.json`,
takes the newest *finished* run per split, and prints "k of n" counts for the full system, verifier
off and naive RAG. With `--readme` it replaces the block between `<!-- results:start -->` and
`<!-- results:end -->` in the README. For each run it states the model, the git SHA and whether
the tree was dirty, how many facts are unverified and how many gold answers are pending sign-off, and
warns if `eval/questions.jsonl` changed since the run was scored. A split with no finished run prints
"Test split not yet run." (that is what it prints today, because the test split has not been run).

Why a script: so no number in the README can come from anywhere but the harness, and so the README
can be refreshed after a new run with one command.

**Clean-clone check.** `scripts/clean_clone_check.sh` copies the repo into a temp folder (a real
`git clone`, or `--worktree` for "what would be committed right now"), checks that none of the
private or generated folders came along, creates a venv, installs `requirements.txt`, runs the tests,
builds the sample database, starts the UI in `--demo` mode headlessly, waits for the health endpoint,
then renders the demo page once to see what a reader actually gets.

What it found:
- In a copy without `.git`, a test that checks the git SHA failed. A real clone always has `.git`,
  so the `--worktree` mode now makes the copy a one-commit git repo.
- In a clone, `--demo` mode starts but shows "no saved eval runs", because `eval/results/` is
  gitignored. The README now says this plainly in a "what you can and cannot reproduce" table.
- The loader builds the sample database without the PDFs (it uses the hashes in
  `sources_hashes.txt`), and `run_dcf` works on it. Ingest, live questions and the eval need the
  PDFs and Ollama.
- Once (out of four full runs in clones) the test suite hung inside ChromaDB's Rust code while
  opening a client in the last test. It did not happen again. Noted as TO VERIFY.

**Demo script.** `docs/DEMO.md`: five saved questions (fact, ratio, DCF terminal-value share,
qualitative, refusal), what to point at for each, and one optional honest failure. The DCF example
is the terminal-value share rather than the per-share value, so a per-share figure is not the thing
on screen. No screenshots: headless Chrome only caught the Streamlit loading skeleton.

**Cleanup.** Removed two unused functions (`numeric_value` in `eval/claims.py`,
`embedding_model_name` in `ingest/embed.py`) and the import that only they used. Added `.claude/` to
`.gitignore` (the other required entries were already there). Synced one missing line in
`AGENTS.md` with `CLAUDE.md`. Scanned everything that would be committed for tokens, keys, home
paths, emails and long annual-report extracts (results in PROGRESS.md).

## Things to be able to explain

- Why the results block is generated, and what "-dirty" means (the code that produced the numbers
  was not a commit anyone can check out).
- Why dev and test are reported separately, and why the test split is still unrun.
- Why the README's numbers are labelled as a plumbing check (plan 2.5: no accuracy claims until the
  full data, the hand DCF and the test split exist).
- What a reader can reproduce without the PDFs (tests, sample DB, DCF engine) and what they cannot
  (ingest, live answers, eval).
