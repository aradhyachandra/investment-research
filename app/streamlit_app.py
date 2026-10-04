"""Streamlit entry point (M8). Run from the repo root:

    .venv/bin/streamlit run app/streamlit_app.py              # live: calls the agent (needs Ollama)
    .venv/bin/streamlit run app/streamlit_app.py -- --demo    # saved eval answers, no model
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from erp.ui.app import main  # noqa: E402

main(sys.argv[1:])
