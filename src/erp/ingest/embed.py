"""The one embedding function. Everything that needs vectors calls embed_texts().

The model name, Ollama URL and task prefixes come from config/ingest.yaml. The only network
call is to the local Ollama server (localhost). Tests pass a fake embedder instead.
"""
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from erp.ingest.pdf_to_chunks import load_ingest_config

PURPOSES = ("document", "query")


class EmbeddingError(RuntimeError):
    pass


def embed_texts(texts, purpose="document", cfg=None) -> list:
    """Embed a list of texts with the configured Ollama model. Returns one vector per text.

    purpose: "document" for chunks being stored, "query" for a search question. nomic-embed-text
    is trained with a different prefix for each, so they must not be mixed up.
    """
    if purpose not in PURPOSES:
        raise EmbeddingError(f"purpose must be one of {PURPOSES}, got {purpose!r}")
    texts = list(texts)
    if not texts:
        return []
    emb = (cfg or load_ingest_config())["embedding"]
    prefix = emb["document_prefix"] if purpose == "document" else emb["query_prefix"]
    body = json.dumps({"model": emb["model"], "input": [prefix + t for t in texts]}).encode()
    request = urllib.request.Request(f"{emb['ollama_url']}/api/embed", data=body,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=emb["timeout_seconds"]) as response:
            vectors = json.load(response).get("embeddings")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise EmbeddingError(f"Ollama embedding call failed ({emb['ollama_url']}, model {emb['model']}): {e}") from e
    if not vectors or len(vectors) != len(texts):
        raise EmbeddingError(f"Ollama returned {len(vectors or [])} vectors for {len(texts)} texts")
    return vectors


@dataclass
class OllamaStatus:
    ok: bool
    reason: str = ""


def ollama_status(cfg=None) -> OllamaStatus:
    """Is the local Ollama server up, with the configured embedding model pulled?"""
    emb = (cfg or load_ingest_config())["embedding"]
    try:
        with urllib.request.urlopen(f"{emb['ollama_url']}/api/tags", timeout=3) as response:
            models = [m["name"] for m in json.load(response).get("models", [])]
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        return OllamaStatus(False, f"Ollama not reachable at {emb['ollama_url']} ({e}); start it with `ollama serve`")
    wanted = emb["model"]
    if not any(m == wanted or m.split(":")[0] == wanted for m in models):
        return OllamaStatus(False, f"model {wanted!r} not pulled; run `ollama pull {wanted}`")
    return OllamaStatus(True)
