"""The structured Answer the agent returns (plan 8.3, simplified for M5).

Every figure in `numbers_used` is a ToolNumber copied from a tool result, never parsed from
the LLM's text; each points at an evidence_id that is listed in `citations`.
The verifier (M6) will add the check that every number written in `answer_text` is one of
these. Until then, `answer_text` is the LLM's prose held to the tool output by the prompt,
the constrained id lists and the advice-language guard only.
"""
from typing import Literal

from pydantic import BaseModel

from erp.agent.router import RoutePlan
from erp.agent.tools import Evidence, ToolNumber, ToolResult

DISCLAIMER = ("Illustrative analysis of published filings and stated assumptions. "
              "Not investment advice.")

NumberUsed = ToolNumber


class Answer(BaseModel):
    question: str
    ticker: str
    answer_text: str
    numbers_used: list[NumberUsed]   # each points at an evidence_id in citations
    citations: list[Evidence]        # sources, pages, periods, bases, formulas, DCF runs
    refused: bool
    refusal_reason: str | None = None
    limitations: list[str] = []      # unverified facts, failed lookups, failed DCF checks ...
    route: RoutePlan | None = None
    tool_results: list[ToolResult] = []
    composed_by: Literal["llm", "template", "refusal"]
    model: str | None = None         # runtime LLM name as Ollama reports it
    warnings: list[str] = []         # what the code had to correct in the LLM's output
    disclaimer: str = DISCLAIMER
