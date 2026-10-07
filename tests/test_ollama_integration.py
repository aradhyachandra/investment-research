"""Integration test against the real local embedding model. Only talks to localhost.

OPT-IN: runs only when ERP_LIVE_TESTS=1 is set AND Ollama is running with nomic-embed-text pulled.
A plain `pytest` never calls the live model (keeps the 8 GB Mac free and test runs fast):
    ERP_LIVE_TESTS=1 PYTHONPATH=src:tests .venv/bin/python -m pytest tests/test_ollama_integration.py
"""
import math
import os

import pytest

from erp.ingest.embed import embed_texts, ollama_status

if os.environ.get("ERP_LIVE_TESTS") != "1":
    pytestmark = pytest.mark.skip(reason="live-model test; set ERP_LIVE_TESTS=1 to run")
else:
    status = ollama_status()
    pytestmark = pytest.mark.skipif(not status.ok, reason=f"Ollama not usable: {status.reason}")


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def test_real_embeddings_have_fixed_size_and_rank_sensibly():
    docs = embed_texts([
        "The company returns cash to shareholders through dividends and share buybacks.",
        "Employee attrition fell and the company hired many fresh graduates.",
    ], purpose="document")
    query = embed_texts(["What is the capital allocation policy?"], purpose="query")[0]
    assert len(docs) == 2 and len(docs[0]) == len(docs[1]) == len(query) > 100
    assert cosine(query, docs[0]) > cosine(query, docs[1])


def test_real_embeddings_are_repeatable():
    a = embed_texts(["Tata Consultancy Services"], purpose="document")[0]
    b = embed_texts(["Tata Consultancy Services"], purpose="document")[0]
    assert cosine(a, b) > 0.9999
