"""Company snapshot tab (M8.1): headline figure cards built from the existing tools.

Every value comes from get_financial_fact / compute_ratio through the agent's tool layer (run_tool),
formatted by the tool layer. Nothing is typed in and nothing is computed here. Which figures appear is
config (config/ui.yaml `snapshot`), not code.

compute_ratio writes an audit row (computed_metric) on every call. So the page never writes to the
database file, it works on an in-memory copy of it (readonly_copy): the file on disk is only read.
"""
import sqlite3
from pathlib import Path

from pydantic import BaseModel

from erp.agent.tools import ToolCall, ToolEnv, ToolResult, run_tool
from erp.config import REPO
from erp.ui.page_preview import number_needles
from erp.ui.view_model import CitationView, PreviewTarget, chip_text, citation_view, doc_types, reported_values


class SnapshotError(RuntimeError):
    pass


class SnapshotCard(BaseModel):
    label: str
    period: str
    compare_period: str
    current: str | None               # display string from the tool layer; None if the lookup failed
    compare: str | None
    change: str | None = None         # e.g. "Revenue growth (year on year), FY26: 4.58%" (a ratio tool result)
    citations: list[CitationView] = []  # documents and pages behind the current-period figure
    verified_by: str | None = None    # from the database's verified_by, if every fact behind the figure has one
    verified_line: str = ""
    error: str | None = None


def readonly_copy(db_path) -> sqlite3.Connection:
    """An in-memory copy of the database, so tool calls that log rows never touch the file."""
    path = Path(db_path)
    if not path.is_file():
        raise SnapshotError(f"database {path} not found")
    disk = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    mem = sqlite3.connect(":memory:", check_same_thread=False)
    disk.backup(mem)
    disk.close()
    mem.execute("PRAGMA foreign_keys = ON")
    return mem


def tool_env(conn: sqlite3.Connection, like: ToolEnv) -> ToolEnv:
    return like.model_copy(update={"conn": conn})


def env_for(conn: sqlite3.Connection, agent_cfg: dict) -> ToolEnv:
    """Tool settings from config/agent.yaml, on the given connection (as agent.loop.open_env does)."""
    return ToolEnv(conn=conn, ticker=agent_cfg["default_ticker"], display=agent_cfg["display"],
                   search_top_k=agent_cfg["tools"]["search_top_k"], passage_chars=agent_cfg["tools"]["passage_chars"],
                   dcf_assumptions=REPO / agent_cfg["tools"]["dcf_assumptions"])


def _facts(r: ToolResult) -> list[dict]:
    """The fact records (FactResult as stored in the tool output) behind a fact or ratio result."""
    if r.tool == "get_financial_fact":
        return [r.detail]
    return [i["fact"] for i in r.detail["inputs"]]


def verified_line(facts: list[dict]) -> tuple[str | None, str]:
    """(verifier name, line to show). The name is given only if one person verified every fact."""
    if not facts:
        return None, ""
    unverified = [f"fact:{f['fact_id']}" for f in facts if not f.get("verified")]
    if unverified:
        return None, f"Not yet checked by a human: {', '.join(unverified)}"
    names = sorted({f["verified_by"] for f in facts})
    dates = sorted({f["verified_on"] for f in facts if f.get("verified_on")})
    who = " and ".join(names)
    return (names[0] if len(names) == 1 else None), f"Verified by {who} ({', '.join(dates)})"


def _call(card: dict, period: str, basis: str, env: ToolEnv) -> ToolResult:
    if card["tool"] == "get_financial_fact":
        args = {"metric_id": card["metric_id"], "period": period, "basis": basis}
    else:
        args = {"ratio_id": card["ratio_id"], "period": period, "basis": basis}
    return run_tool(ToolCall(tool=card["tool"], args=args), env)


def _main_number(r: ToolResult):
    return r.numbers[0]                   # fact: the value; ratio: the ratio (inputs follow it)


def build_card(card: dict, cfg: dict, env: ToolEnv, ui_cfg: dict) -> SnapshotCard:
    period, compare, basis = cfg["period"], cfg["compare_period"], cfg.get("basis", "consolidated")
    now, before = _call(card, period, basis, env), _call(card, compare, basis, env)
    base = SnapshotCard(label=card["label"], period=period, compare_period=compare, current=None, compare=None)
    if not now.ok:
        return base.model_copy(update={"error": now.error})
    types = doc_types([now])
    facts = _facts(now)
    fact_ids = {f"fact:{f['fact_id']}" for f in facts}
    reported = reported_values([now])
    citations = [citation_view(e, types, {}, ui_cfg, reported) for e in now.evidence if e.evidence_id in fact_ids]
    who, line = verified_line(facts + (_facts(before) if before.ok else []))
    change = None
    if card.get("change_ratio"):
        g = _call({"tool": "compute_ratio", "ratio_id": card["change_ratio"]}, period, basis, env)
        change = f"{g.detail['display_name']}, {period}: {_main_number(g).display}" if g.ok else None
    return base.model_copy(update={
        "current": _main_number(now).display, "compare": _main_number(before).display if before.ok else None,
        "change": change, "citations": citations, "verified_by": who, "verified_line": line,
        "error": None if before.ok else f"{compare}: {before.error}"})


def build_snapshot(env: ToolEnv, cfg: dict, ui_cfg: dict) -> list[SnapshotCard]:
    return [build_card(card, cfg, env, ui_cfg) for card in cfg["cards"]]


def snapshot_targets(cards: list[SnapshotCard]) -> list[PreviewTarget]:
    """The pages behind the cards, for the source page preview (each fact once)."""
    out, seen = [], set()
    for card in cards:
        for c in card.citations:
            if c.evidence_id in seen or c.page is None or c.reported_value is None:
                continue
            seen.add(c.evidence_id)
            out.append(PreviewTarget(evidence_id=c.evidence_id, kind=c.kind, label=f"{card.label} · {chip_text(c)}",
                                     source_title=c.source_title, page=c.page,
                                     needles=number_needles(c.reported_value)))
    return out
