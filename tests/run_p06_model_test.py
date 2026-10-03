"""P0.6 model test: which small local model routes reliably? Not a pytest test (needs Ollama).

5 TOY prompts about a made-up company ("ACME", not TCS, so nothing here can leak into the eval).
Each model is asked to pick a toy tool and its arguments in three ways:
  schema   - JSON constrained by Ollama's `format` (what the two-step router uses)
  prompted - JSON asked for in the prompt only, no constraint (raw instruction following)
  native   - Ollama native tool calling (`tools`), i.e. free-form tool calling (Router v0)
Scored per prompt: output parses, matches the toy schema, right tool(s) and arguments.

Run:  PYTHONPATH=src .venv/bin/python tests/run_p06_model_test.py qwen2.5:3b phi4-mini llama3.2
"""
import json
import subprocess
import sys

from erp.agent.llm import LLMError, call_llm

TOOLS = ["lookup_metric", "search_report"]
METRICS = ["revenue", "operating_profit", "net_income"]
YEARS = ["2022", "2023", "2024"]

SYSTEM = (
    "You route questions about the company ACME to tools. Tools:\n"
    "- lookup_metric(metric, year): one reported figure. metric is one of revenue, operating_profit, "
    "net_income. year is one of 2022, 2023, 2024.\n"
    "- search_report(query): search ACME's annual report text for qualitative questions.\n"
    "A question can need several calls. If the question asks for a forecast, an opinion on whether to "
    "invest, or anything the tools cannot answer, make no calls and set refuse to true."
)
JSON_SHAPE = ('Reply with JSON only: {"refuse": true|false, "calls": [{"tool": "...", "metric": "...", '
              '"year": "...", "query": "..."}]} (leave out fields a tool does not use).')

SCHEMA = {
    "type": "object",
    "properties": {
        "refuse": {"type": "boolean"},
        "calls": {"type": "array", "maxItems": 3, "items": {
            "type": "object",
            "properties": {"tool": {"enum": TOOLS}, "metric": {"enum": METRICS},
                           "year": {"enum": YEARS}, "query": {"type": "string"}},
            "required": ["tool"]}},
    },
    "required": ["refuse", "calls"],
}

NATIVE_TOOLS = [
    {"type": "function", "function": {
        "name": "lookup_metric", "description": "One reported figure for ACME.",
        "parameters": {"type": "object", "required": ["metric", "year"], "properties": {
            "metric": {"type": "string", "enum": METRICS}, "year": {"type": "string", "enum": YEARS}}}}},
    {"type": "function", "function": {
        "name": "search_report", "description": "Search ACME's annual report text.",
        "parameters": {"type": "object", "required": ["query"], "properties": {
            "query": {"type": "string"}}}}},
]

# expected: sorted list of (tool, metric, year); search calls carry no args to compare.
PROMPTS = [
    ("What was ACME's revenue in 2024?", [("lookup_metric", "revenue", "2024")], False),
    ("What does ACME's annual report say about supply-chain risks?", [("search_report", None, None)], False),
    ("What was ACME's operating profit in 2023, and how does management explain it?",
     [("lookup_metric", "operating_profit", "2023"), ("search_report", None, None)], False),
    ("Where will ACME's share price be next month?", [], True),
    ("Net income for 2022, please.", [("lookup_metric", "net_income", "2022")], False),
]


def _key(call: dict):
    tool = call.get("tool") or call.get("name")
    args = call.get("arguments", call)
    if tool == "search_report":
        return ("search_report", None, None)
    return (tool, args.get("metric"), str(args.get("year")) if args.get("year") is not None else None)


def _schema_ok(obj) -> bool:
    if not isinstance(obj, dict) or not isinstance(obj.get("refuse"), bool) or not isinstance(obj.get("calls"), list):
        return False
    for c in obj["calls"]:
        if not isinstance(c, dict) or c.get("tool") not in TOOLS:
            return False
        if c["tool"] == "lookup_metric" and (c.get("metric") not in METRICS or str(c.get("year")) not in YEARS):
            return False
    return True


def run_one(model: str, mode: str, question: str):
    messages = [{"role": "system", "content": SYSTEM + ("" if mode == "native" else "\n" + JSON_SHAPE)},
                {"role": "user", "content": question}]
    reply = call_llm(messages, model=model, schema=SCHEMA if mode == "schema" else None,
                     tools=NATIVE_TOOLS if mode == "native" else None)
    if mode == "native":
        calls = [{"name": c["function"]["name"], "arguments": c["function"].get("arguments") or {}}
                 for c in reply.tool_calls]
        valid = all(c["name"] in TOOLS and (c["name"] != "lookup_metric" or (
            c["arguments"].get("metric") in METRICS and str(c["arguments"].get("year")) in YEARS)) for c in calls)
        return True, valid, sorted(map(_key, calls)), not calls, reply
    try:
        obj = json.loads(reply.text)
    except json.JSONDecodeError:
        return False, False, None, None, reply
    ok = _schema_ok(obj)
    calls = obj.get("calls") if isinstance(obj, dict) and isinstance(obj.get("calls"), list) else []
    refuse = obj.get("refuse") if isinstance(obj, dict) else None
    return True, ok, sorted(_key(c) for c in calls if isinstance(c, dict)), refuse, reply


def main(models):
    summary = {}
    for model in models:
        for mode in ("schema", "prompted", "native"):
            parsed = valid = correct = 0
            seconds = 0.0
            for question, expected, must_refuse in PROMPTS:
                try:
                    p, v, calls, refuse, reply = run_one(model, mode, question)
                except LLMError as e:
                    print(f"{model:14} {mode:8} ERROR {e}")
                    continue
                seconds += reply.seconds
                right = calls == sorted(expected) and (refuse is True) == must_refuse \
                    if mode != "native" else calls == sorted(expected)
                parsed += p
                valid += v
                correct += bool(right)
                shown = reply.text[:160].replace("\n", " ") if mode != "native" else json.dumps(reply.tool_calls)[:160]
                print(f"{model:14} {mode:8} {'OK ' if right else 'BAD'} {reply.seconds:6.1f}s  {question[:45]:45} | {shown}")
            summary[(model, mode)] = (parsed, valid, correct, round(seconds, 1))
        ps = subprocess.run(["ollama", "ps"], capture_output=True, text=True).stdout.strip()
        print(f"--- ollama ps after {model}:\n{ps}\n")
    print("\nmodel          mode      parsed  schema-valid  correct  total_s   (out of 5)")
    for (model, mode), (p, v, c, s) in summary.items():
        print(f"{model:14} {mode:8} {p:6} {v:13} {c:8} {s:8}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["qwen2.5:3b", "phi4-mini", "llama3.2"])
