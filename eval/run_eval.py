"""Run the eval harness (M7). The code lives in src/erp/eval/; this is the command.

  PYTHONPATH=src .venv/bin/python eval/run_eval.py                      # dev split, all systems
  PYTHONPATH=src .venv/bin/python eval/run_eval.py --systems full --ids EV-A01 EV-C01
  PYTHONPATH=src .venv/bin/python eval/run_eval.py --test               # frozen test split, once
  PYTHONPATH=src .venv/bin/python eval/run_eval.py --rescore eval/results/dev/<run>

Needs Ollama running (qwen2.5:3b and nomic-embed-text), data/db/sample.sqlite and the Chroma index.
"""
import sys

from erp.eval.cli import main

if __name__ == "__main__":
    main(sys.argv[1:])
