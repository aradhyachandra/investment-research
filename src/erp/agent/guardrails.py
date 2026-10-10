"""Refusal pre-check (M6). Plain pattern matching, no LLM.

Runs before the router. A question asking for investment advice (including valuation verdicts
such as "undervalued"), a share-price forecast, about another company, or about a period later
than the latest data (a forecast, e.g. "revenue in FY28") is refused here with the fixed text
from loop.py, and no LLM or tool is called. The router's own refusal stays as a
second line for phrasings these patterns miss. Exception (loop.py): a period after the latest data
is refused unless the router sends the question only to explain_period ("which dates does Q2 FY27
cover?" is not a forecast).

The patterns live in config/agent.yaml (`guardrails`); other-company names live in the company
config, because which companies are "other" depends on the company being researched.
"""
import re
import sqlite3

import yaml

from erp.agent.verifier import period_key, periods_in
from erp.config import REPO


def other_company_names(ticker: str) -> list[str]:
    path = REPO / "config" / "companies" / f"{ticker.lower()}.yaml"
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    return list((cfg.get("guardrails") or {}).get("other_company_names") or [])


def latest_period(conn: sqlite3.Connection, ticker: str) -> str | None:
    """The latest period with any data: a fact, or a source document's period_covered."""
    labels = [r[0] for r in conn.execute(
        "SELECT p.label FROM period p JOIN fact f USING (period_id) JOIN company c ON c.company_id = f.company_id "
        "WHERE c.ticker_nse = ? UNION SELECT s.period_covered FROM source_document s JOIN company c "
        "USING (company_id) WHERE c.ticker_nse = ?", (ticker, ticker))]
    keyed = [label for label in labels if period_key(label)]
    return max(keyed, key=period_key) if keyed else None


def precheck(question: str, patterns: dict[str, list[str]], other_companies: list[str],
             latest: str | None = None) -> str | None:
    """The refusal reason for a question, or None if it may go to the router."""
    other = any(re.search(rf"\b{re.escape(name)}\b", question, re.I) for name in other_companies)
    for reason, regexes in patterns.items():
        if any(re.search(p, question, re.I) for p in regexes):
            # Another company's share price: the other-company reason is the more useful one.
            return "other_company" if reason == "no_market_data" and other else reason
    if other:
        return "other_company"
    if latest and any(period_key(p) > period_key(latest) for p in periods_in(question)):
        return "outside_data"
    return None


def about_intent(question: str, patterns: list[str]) -> bool:
    """U1: a help / about question ("what can you do?", "who made you?"). The patterns match the
    whole question, so a real question that starts the same way still goes to the router."""
    return any(re.search(p, question.strip(), re.I) for p in patterns)
