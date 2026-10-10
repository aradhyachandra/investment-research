"""DCF tab (M8.1): chart records built from run_dcf results.

Every value is the DCF engine's own output, called through the agent's tool layer (run_tool), and every
label is formatted by tools.format_number. Two things here are display geometry, not figures:
  - the heatmap colour is the engine's per-share value for that cell;
  - the waterfall's bar ends are running totals of the engine's bridge items, used only to place the
    bars. The labels show the engine's own values, and the last bar ends at the engine's equity value
    (tested).
Which scenarios are shown is config (config/ui.yaml `dcf`); the scenarios themselves live in the
author's assumptions file.

D4: "Assumptions vs history" puts each operating assumption (value per scenario) beside the same quantity
computed by dcf/history.py for FY23-FY26, with the range, each scenario's pass/warn status and page chips
for the facts used. Every figure is from the run's own `history` record, formatted here.
"""
from pathlib import Path

import yaml
from pydantic import BaseModel

from erp.agent.tools import ToolCall, ToolEnv, _fact_evidence, format_number, run_tool
from erp.tools.facts import FactResult
from erp.ui.view_model import CitationView, DCFPath, citation_view, dcf_path, load_ui_config


class ScenarioBar(BaseModel):
    scenario: str                     # key in the assumptions file (e.g. "bear")
    name: str                         # display name from config/ui.yaml (e.g. "Low growth")
    label: str                        # the scenario's description from the assumptions file
    value: float                      # engine value per share (for the bar length)
    display: str
    run_id: int


class HeatCell(BaseModel):
    wacc: str                         # display, e.g. "11.50%"
    growth: str
    wacc_order: int                   # row / column position in the engine's grid
    growth_order: int
    value: float | None               # None where growth >= WACC (undefined)
    display: str
    short: str                        # cell label without unit words, e.g. "2,345.67"
    is_scenario: bool                 # the scenario's own WACC and growth (grid centre)


class WaterfallStep(BaseModel):
    label: str
    kind: str                         # total / add / subtract
    start: float                      # bar placement only (running total before this step)
    end: float
    display: str                      # the engine's value for this item


class HeadlineFigure(BaseModel):
    label: str
    display: str                      # engine output, formatted by tools.format_number


class HistoryTableRow(BaseModel):
    assumption: str                   # key, e.g. ebit_margin
    label: str                        # e.g. "EBIT margin (lease-adjusted)"
    scenario_values: dict[str, str]   # scenario key -> value(s) as used, e.g. "24.70%"
    years: dict[str, str]             # period -> history value, or "n/a"
    range: str                        # "min to max (average x)"
    status: dict[str, str]            # scenario key -> pass / warn
    details: dict[str, str]           # scenario key -> the check's detail
    note: str                         # definition, match note, CAGR, why a year is n/a
    definition_match: str             # same / approximate / none
    chips: list[CitationView]         # one per page the facts came from


class HistoryTable(BaseModel):
    periods: list[str]
    rows: list[HistoryTableRow]
    tolerance_rule: str
    unverified_fact_ids: list[str]
    note: str | None = None


class DCFTabView(BaseModel):
    scenarios: list[ScenarioBar]
    base_name: str = ""               # display name of the base scenario
    headline: list[HeadlineFigure] = []   # firm-level figures of the base scenario, shown before per-share values
    base: DCFPath | None              # full calculation path of the base scenario
    base_detail: dict | None          # run_dcf output of the base scenario
    heatmap: list[HeatCell]
    waterfall: list[WaterfallStep]
    per_share_unit: str | None
    errors: list[str]
    history: HistoryTable | None = None   # D4: assumptions vs FY23-FY26 record


def scenario_names(assumptions_file, preferred: list[str]) -> list[str]:
    """Scenarios to show: those in `preferred` (config order) that the assumptions file defines."""
    path = Path(assumptions_file)
    if not path.is_file():
        return []
    defined = (yaml.safe_load(path.read_text()) or {}).get("scenarios", {}) or {}
    return [s for s in preferred if s in defined]


def heatmap_cells(detail: dict, display: dict) -> list[HeatCell]:
    g, unit, v = detail["sensitivity"], detail["per_share_unit"], detail["valuation"]
    cells = []
    for i, w in enumerate(g["wacc_values"]):
        for j, gr in enumerate(g["growth_values"]):
            value = g["value_per_share"][i][j]
            cells.append(HeatCell(
                wacc=format_number(w * 100, "PERCENT", display), growth=format_number(gr * 100, "PERCENT", display),
                wacc_order=i, growth_order=j, value=value,
                display=format_number(value, unit, display) if value is not None else "undefined (growth >= WACC)",
                short=format_number(value, "PLAIN", {"decimals": {"PLAIN": display["decimals"].get(unit, 2)},
                                                     "templates": {"PLAIN": "{v}"}}) if value is not None else "n/a",
                is_scenario=abs(w - v["wacc"]) < 1e-9 and abs(gr - v["terminal_growth"]) < 1e-9))  # grid values are rounded
    return cells


def waterfall_steps(detail: dict, display: dict) -> list[WaterfallStep]:
    b, money = detail["valuation"]["bridge"], detail["units"]["money"]
    steps = [WaterfallStep(label="Enterprise value", kind="total", start=0, end=b["enterprise_value"],
                           display=format_number(b["enterprise_value"], money, display))]
    running = b["enterprise_value"]
    for key, label, sign in [("cash_and_investments", "+ Cash and investments", 1), ("debt", "- Debt", -1),
                             ("lease_liabilities", "- Lease liabilities", -1),
                             ("minority_interest", "- Minority interest", -1)]:
        nxt = running + sign * b[key]          # placement only; the label is the engine's figure
        steps.append(WaterfallStep(label=label, kind="add" if sign > 0 else "subtract", start=running, end=nxt,
                                   display=format_number(b[key], money, display)))
        running = nxt
    steps.append(WaterfallStep(label="Equity value", kind="total", start=0, end=b["equity_value"],
                               display=format_number(b["equity_value"], money, display)))
    return steps


def headline_figures(detail: dict, display: dict) -> list[HeadlineFigure]:
    """Firm-level outputs of one run: enterprise value, equity value, TV share of EV, WACC."""
    v, money = detail["valuation"], detail["units"]["money"]
    return [HeadlineFigure(label="Enterprise value", display=format_number(v["enterprise_value"], money, display)),
            HeadlineFigure(label="Equity value", display=format_number(v["equity_value"], money, display)),
            HeadlineFigure(label="Terminal value share of EV",
                           display=format_number(v["tv_share_of_ev"] * 100, "PERCENT", display)),
            HeadlineFigure(label="WACC", display=format_number(v["wacc"] * 100, "PERCENT", display))]


def _pct(x: float, display: dict) -> str:
    return format_number(x * 100, "PERCENT", display)


def _chips(facts: list[dict], ui_cfg: dict) -> list[CitationView]:
    """One page chip per document page the facts came from."""
    out = {}
    for f in facts:
        e = _fact_evidence(FactResult.model_validate(f))
        c = citation_view(e, {f["source_id"]: f["source_doc_type"]}, {}, ui_cfg,
                          {e.evidence_id: f["reported_value"]})
        out.setdefault((c.source_title, c.page_text), c)
    return list(out.values())


def history_table(details: dict[str, dict], display: dict, ui_cfg: dict) -> HistoryTable | None:
    """Rows from the runs' `history` records (one run per scenario; the history itself is the same in each)."""
    runs = {k: d["history"] for k, d in details.items() if d.get("history")}
    if not runs:
        return None
    first = next(iter(runs.values()))
    periods = first["periods"]
    rows = []
    for row in first["rows"]:
        name = row["assumption"]
        checks = {k: next(c for c in h["checks"] if c["assumption"] == name) for k, h in runs.items()}
        years = {y["period"]: _pct(y["value"], display) if y["value"] is not None else "n/a" for y in row["years"]}
        rng = (f"{_pct(row['min'], display)} to {_pct(row['max'], display)} (average {_pct(row['average'], display)})"
               if row["min"] is not None else "n/a")
        note = [row["definition"]] if row["definition"] else []
        if row.get("match_note"):
            note.append(row["match_note"])
        if row.get("cagr") and row["cagr"]["value"] is not None:
            note.append(f"Compound annual growth {row['cagr']['period']}: {_pct(row['cagr']['value'], display)}.")
        missing = {y["missing"] for y in row["years"] if y["value"] is None and y.get("missing")}
        note += [f"n/a: {m}" for m in sorted(missing)]
        rows.append(HistoryTableRow(
            assumption=name, label=row["label"],
            scenario_values={k: ", ".join(_pct(v, display) for v in c["values"]) for k, c in checks.items()},
            years=years, range=rng, status={k: c["status"] for k, c in checks.items()},
            details={k: c["detail"] for k, c in checks.items()}, note=" ".join(note),
            definition_match=row["definition_match"], chips=_chips(row["facts"], ui_cfg)))
    return HistoryTable(periods=periods, rows=rows, tolerance_rule=first["tolerance_rule"],
                        unverified_fact_ids=first["unverified_fact_ids"], note=first.get("note"))


def build_dcf_tab(env: ToolEnv, scenarios: list[str], *, base: str, assumptions_file, footer: str,
                  labels: dict | None = None) -> DCFTabView:
    labels = labels or {}
    errors, bars, base_result, details = [], [], None, {}
    if not Path(assumptions_file).is_file():
        errors.append(f"DCF assumptions file {Path(assumptions_file).name} not found, so no DCF can be shown.")
    else:
        for name in scenario_names(assumptions_file, scenarios):
            r = run_tool(ToolCall(tool="run_dcf", args={"scenario": name, "include_sensitivity": name == base}), env)
            if not r.ok:
                errors.append(f"Scenario '{name}': {r.error}")
                continue
            d = r.detail
            details[name] = d
            per_share = next(n for n in r.numbers if n.number_id.endswith("#value_per_share"))
            bars.append(ScenarioBar(scenario=name, name=labels.get(name, name), label=d["description"], value=per_share.value,
                                    display=per_share.display, run_id=d["run_id"]))
            if name == base:
                base_result = r
    if base_result is None:
        if not errors:
            errors.append(f"Scenario '{base}' is not defined in the assumptions file.")
        return DCFTabView(scenarios=bars, base=None, base_detail=None, heatmap=[], waterfall=[],
                          per_share_unit=None, errors=errors)
    d = base_result.detail
    return DCFTabView(scenarios=bars, base_name=labels.get(base, base), headline=headline_figures(d, env.display),
                      base=dcf_path(base_result, env.display, assumptions_file, footer),
                      base_detail=d, heatmap=heatmap_cells(d, env.display), waterfall=waterfall_steps(d, env.display),
                      per_share_unit=d["per_share_unit"], errors=errors,
                      history=history_table(details, env.display, load_ui_config()))
