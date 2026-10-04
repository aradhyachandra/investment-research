"""The structured Answer the agent returns (plan 8.3, simplified for M5).

Every figure in `numbers_used` is a ToolNumber copied from a tool result; each points at an
evidence_id that is listed in `citations`. Since M6 the verifier (verifier.py) checks that every
number written in `answer_text` is one of the tool numbers, and `numbers_used` is the list of
tool numbers the text actually says. If the verifier finds an error, `answer_text` is the
code-written template instead of the LLM's prose (`composed_by = "template"`).
"""
from typing import Literal

from pydantic import BaseModel

from erp.agent.router import RoutePlan
from erp.agent.tools import Evidence, ToolNumber, ToolResult
from erp.agent.verifier import VerifierReport

DISCLAIMER = ("Illustrative analysis of published filings and stated assumptions. "
              "Not investment advice.")

NumberUsed = ToolNumber


class Answer(BaseModel):
    question: str
    ticker: str
    answer_text: str
    numbers_used: list[NumberUsed]   # the tool numbers the text says; each points at a citation
    citations: list[Evidence]        # sources, pages, periods, bases, formulas, DCF runs
    refused: bool
    refusal_reason: str | None = None
    limitations: list[str] = []      # unverified facts, failed lookups, failed DCF checks ...
    route: RoutePlan | None = None
    tool_results: list[ToolResult] = []
    composed_by: Literal["llm", "template", "refusal"]
    model: str | None = None         # runtime LLM name as Ollama reports it
    warnings: list[str] = []         # what the code had to correct in the LLM's output
    verification: VerifierReport | None = None   # the verifier's report on the LLM's text (M6)
    rejected_text: str | None = None  # the LLM's text when it was replaced by the template (for review)
    disclaimer: str = DISCLAIMER
