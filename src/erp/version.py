"""Code version (git SHA) recorded with every computed result."""
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def code_version() -> str:
    """HEAD commit SHA, with '-dirty' if the working tree has uncommitted changes.

    Returns 'unknown' (never a made-up SHA) if git or the repository is not available.
    """
    try:
        sha = _git("rev-parse", "HEAD")
        dirty = _git("status", "--porcelain")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{sha}-dirty" if dirty else sha
