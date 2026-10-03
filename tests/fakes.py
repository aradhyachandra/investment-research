"""A deterministic fake embedder so the test suite runs without Ollama.

Bag of words hashed into a small vector: texts sharing words get similar vectors, so search
tests can check ranking. md5 (not Python's salted hash) keeps it identical across runs.
"""
import hashlib
import math
import re

DIM = 64


def fake_embed(texts, purpose="document"):
    vectors = []
    for text in texts:
        v = [0.0] * DIM
        for word in re.findall(r"[a-z]+", text.lower()):
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        vectors.append([x / norm for x in v] if any(v) else [1.0 / math.sqrt(DIM)] * DIM)
    return vectors


class CountingEmbedder:
    """fake_embed that counts how many texts it was asked to embed."""

    def __init__(self):
        self.calls = 0
        self.texts = 0

    def __call__(self, texts, purpose="document"):
        self.calls += 1
        self.texts += len(texts)
        return fake_embed(texts, purpose)
