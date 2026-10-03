"""Integration test against the real local embedding model. Skipped automatically if Ollama is
not running or nomic-embed-text is not pulled. Only talks to localhost."""
import math

import pytest

from erp.ingest.embed import embed_texts, ollama_status

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
