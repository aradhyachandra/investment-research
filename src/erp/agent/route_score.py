"""Routing accuracy: compare a RoutePlan with a question's expected route. Its own metric
(plan 6.2, secondary), reported as counts.

  tool_ok: refused when it should (and only then), and the same multiset of tools.
  full_ok: tool_ok and the same key arguments per call (metric_id / ratio_id / period / basis /
           scenario / include_sensitivity). Search query text is free wording, so not compared.
  reason_ok: for refusals, the same refusal reason (reported, not part of full_ok).
Call order does not matter; an extra or missing call is wrong.
"""
from collections import Counter

from pydantic import BaseModel

from erp.agent.router import RoutePlan
from erp.agent.tools import ARGS_MODELS

KEY_ARGS = ("metric_id", "ratio_id", "period", "basis", "scenario", "include_sensitivity")


class RouteScore(BaseModel):
    tool_ok: bool
    full_ok: bool
    reason_ok: bool | None = None


def _key(tool: str, args: dict) -> tuple:
    if tool not in ARGS_MODELS or tool == "search_documents":
        return (tool,)
    # Fill defaults (basis -> consolidated, include_sensitivity -> False) the way the tool would.
    defaults = {k: f.default for k, f in ARGS_MODELS[tool].model_fields.items() if not f.is_required()}
    merged = {**defaults, **{k: v for k, v in args.items() if v is not None}}
    return (tool, *((k, merged.get(k)) for k in KEY_ARGS if k in ARGS_MODELS[tool].model_fields))


def score_route(plan: RoutePlan, expected: dict) -> RouteScore:
    if expected["refuse"] or plan.refuse:
        both = bool(expected["refuse"]) and plan.refuse
        reason_ok = (plan.refusal_reason == expected.get("refusal_reason")) if both else None
        return RouteScore(tool_ok=both, full_ok=both, reason_ok=reason_ok)
    got = [(c.tool, c.args) for c in plan.calls]
    want = [(c["tool"], {k: v for k, v in c.items() if k != "tool"}) for c in expected["calls"]]
    tool_ok = Counter(t for t, _ in got) == Counter(t for t, _ in want)
    full_ok = tool_ok and Counter(_key(*g) for g in got) == Counter(_key(*w) for w in want)
    return RouteScore(tool_ok=tool_ok, full_ok=full_ok)


class RoutingTally:
    def __init__(self):
        self.rows = []

    def add(self, question_id: str, score: RouteScore):
        self.rows.append((question_id, score))

    @property
    def n(self):
        return len(self.rows)

    @property
    def tool_correct(self):
        return sum(s.tool_ok for _, s in self.rows)

    @property
    def full_correct(self):
        return sum(s.full_ok for _, s in self.rows)

    def summary(self) -> str:
        wrong = [q for q, s in self.rows if not s.full_ok]
        return (f"routing: tools right {self.tool_correct} of {self.n}; tools and arguments right "
                f"{self.full_correct} of {self.n}" + (f"; wrong: {', '.join(wrong)}" if wrong else ""))
