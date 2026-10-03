"""call_llm: the ONE function through which the app talks to its runtime LLM.

Local Ollama only (`/api/chat`), model name and settings from config/agent.yaml. No API key,
no hosted model. Every other module receives this function as `llm_fn`, so tests swap in a
scripted fake and a model can be swapped in config and compared on the same questions.

`schema`: a JSON schema passed as Ollama's `format`, which constrains the model's output to
JSON matching it (Ollama "structured outputs"). TO VERIFY: Ollama converts the schema to a
grammar; keywords it does not support may be ignored silently, so callers still validate.
`tools`: native tool definitions (only used by the P0.6 comparison of free-form tool calling).
"""
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml
from pydantic import BaseModel

from erp.config import REPO

AGENT_CONFIG = REPO / "config" / "agent.yaml"


class LLMError(RuntimeError):
    pass


class LLMReply(BaseModel):
    text: str                      # the assistant message content (JSON text when a schema was given)
    tool_calls: list[dict] = []    # native tool calls, if `tools` was given and the model used them
    model: str
    seconds: float


def load_agent_config(path: Path = AGENT_CONFIG) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def call_llm(messages: list[dict], *, schema: dict | None = None, tools: list[dict] | None = None,
             model: str | None = None, cfg: dict | None = None) -> LLMReply:
    """messages: [{'role': 'system'|'user'|'assistant', 'content': str}, ...].
    model: override the configured model (only for side-by-side model tests)."""
    llm = (cfg or load_agent_config())["llm"]
    body = {
        "model": model or llm["model"],
        "messages": messages,
        "stream": False,
        "keep_alive": llm["keep_alive"],
        "options": {"temperature": llm["temperature"], "seed": llm["seed"], "num_ctx": llm["num_ctx"]},
    }
    if schema is not None:
        body["format"] = schema
    if tools is not None:
        body["tools"] = tools
    request = urllib.request.Request(f"{llm['ollama_url']}/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=llm["timeout_seconds"]) as response:
            data = json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LLMError(f"Ollama chat call failed ({llm['ollama_url']}, model {body['model']}): {e}") from e
    message = data.get("message") or {}
    return LLMReply(text=message.get("content", ""), tool_calls=message.get("tool_calls") or [],
                    model=data.get("model", body["model"]), seconds=round(time.monotonic() - start, 2))
