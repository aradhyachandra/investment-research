#!/usr/bin/env bash
# Clean-clone check (M9): does the repo set up and run from the README alone?
#
# What it does, in a fresh temp folder:
#   1. gets a copy of the repo (git clone of committed code, or --worktree: the files git would
#      commit right now, including uncommitted and new files, excluding everything gitignored)
#   2. creates a venv and installs requirements.txt
#   3. runs the test suite (no Ollama, no PDFs, no database: tests that need them skip)
#   4. builds the SQLite database from data/manual/financials_tcs.csv (README step)
#   5. starts the UI in --demo mode headlessly, checks the health endpoint, then stops it
#
# It never touches the original checkout. The temp folder is deleted at the end unless --keep.
#
# Usage:
#   scripts/clean_clone_check.sh                  # clone committed HEAD of this repo
#   scripts/clean_clone_check.sh --worktree       # what would be committed now (pre-commit check)
#   scripts/clean_clone_check.sh --source <url>   # clone from a remote instead
#   options: --python <exe> (default python3), --port <n> (default 8599), --keep
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$REPO"
MODE=clone
PYTHON=python3
PORT=8599
KEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --worktree) MODE=worktree ;;
    --source) SOURCE="$2"; shift ;;
    --python) PYTHON="$2"; shift ;;
    --port) PORT="$2"; shift ;;
    --keep) KEEP=1 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/erp-clean-clone.XXXXXX")"
DEST="$WORK/repo"
UI_PID=""
cleanup() {
  [ -n "$UI_PID" ] && kill "$UI_PID" 2>/dev/null || true
  if [ "$KEEP" = 1 ]; then echo "kept: $WORK"; else rm -rf "$WORK"; fi
}
trap cleanup EXIT

step() { echo; echo "=== $*"; }

step "1. copy of the repo ($MODE) -> $DEST"
if [ "$MODE" = clone ]; then
  git clone --quiet "$SOURCE" "$DEST"
else
  mkdir -p "$DEST"
  # Tracked files plus untracked files that are not gitignored = what `git add -A` would commit.
  (cd "$REPO" && git ls-files --cached --others --exclude-standard -z) \
    | (cd "$REPO" && xargs -0 tar -cf - 2>/dev/null) | (cd "$DEST" && tar -xf -)
  # Make it a git repo with one commit, as a real clone would be (code_version reads the git SHA).
  (cd "$DEST" && git init --quiet && git add -A \
    && git -c user.name=clean-clone-check -c user.email=check@invalid commit --quiet -m snapshot)
fi
cd "$DEST"
for p in data/raw data/db data/chroma eval/results .env; do
  if [ -e "$p" ]; then echo "FAIL: $p is present in the copy (should be gitignored)"; exit 1; fi
done
echo "ok: no data/raw, data/db, data/chroma, eval/results or .env in the copy"

step "2. venv + pip install -r requirements.txt ($("$PYTHON" --version))"
"$PYTHON" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
.venv/bin/python -m pip check

step "3. tests (no PDFs, no database; tests that need them, or Ollama, skip)"
set +e
.venv/bin/python -m pytest -q -p no:cacheprovider > "$WORK/pytest.log" 2>&1
rc=$?
set -e
grep -E "passed|failed|error" "$WORK/pytest.log" | tail -n 5
if [ "$rc" != 0 ]; then echo "FAIL: tests (exit $rc); log: $WORK/pytest.log"; KEEP=1; exit 1; fi

step "4. build the sample database"
PYTHONPATH=src .venv/bin/python -m erp.db.load_facts --csv data/manual/financials_tcs.csv \
  --entry-method llm_extracted --replace

step "5. UI in --demo mode, headless, port $PORT"
.venv/bin/streamlit run app/streamlit_app.py --server.headless true --server.port "$PORT" \
  -- --demo > "$WORK/ui.log" 2>&1 &
UI_PID=$!
ok=0
for _ in $(seq 1 60); do
  if curl -fsS "http://localhost:$PORT/_stcore/health" 2>/dev/null | grep -q ok; then ok=1; break; fi
  sleep 1
done
if [ "$ok" != 1 ]; then echo "FAIL: UI did not report healthy"; cat "$WORK/ui.log"; exit 1; fi
echo "ok: UI healthy at http://localhost:$PORT"
# The health endpoint only proves the server is up. Render the demo page once, headless, to see
# what a reader without saved eval runs gets (eval/results/ is gitignored, so a clone has none).
.venv/bin/python - <<'EOF'
from streamlit.testing.v1 import AppTest
import sys
sys.argv = ["streamlit_app.py", "--demo"]  # the app reads its options from sys.argv
at = AppTest.from_file("app/streamlit_app.py", default_timeout=60)
at.run()
if at.exception:
    print("FAIL: page raised:", at.exception[0].message); sys.exit(1)
errors = [e.value for e in at.error]
print("page rendered; title:", at.title[0].value if at.title else "(none)")
print("errors shown on page:", errors or "none")
EOF
kill "$UI_PID" 2>/dev/null || true
UI_PID=""

step "done: clean-clone check passed"
