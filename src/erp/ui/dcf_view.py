"""DCF tab (M8.1): chart records built from run_dcf results.

Every value is the DCF engine's own output, called through the agent's tool layer (run_tool), and every
label is formatted by tools.format_number. Two things here are display geometry, not figures:
  - the heatmap colour is the engine's per-share value for that cell;
  - the waterfall's bar ends are running totals of the engine's bridge items, used only to place the
    bars. The labels show the engine's own values, and the last bar ends at the engine's equity value
    (tested).
Which scenarios are shown is config (config/ui.yaml `dcf`); the scenarios themselves live in the
author's assumptions file.
"""
from pathlib import Path

import yaml
from pydantic import BaseModel

from erp.agent.tools import ToolCall, ToolEnv, format_number, run_tool
from erp.ui.view_model import DCFPath, dcf_path


class ScenarioBar(BaseModel):
    scenario: str
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


class DCFTabView(BaseModel):
    scenarios: list[ScenarioBar]
    base: DCFPath | None              # full calculation path of the base scenario
    base_detail: dict | None          # run_dcf output of the base scenario
    heatmap: list[HeatCell]
    waterfall: list[WaterfallStep]
    per_share_unit: str | None
    errors: list[str]


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


def build_dcf_tab(env: ToolEnv, scenarios: list[str], *, base: str, assumptions_file, footer: str) -> DCFTabView:
    errors, bars, base_result = [], [], None
    if not Path(assumptions_file).is_file():
        errors.append(f"DCF assumptions file {Path(assumptions_file).name} not found, so no DCF can be shown.")
    else:
        for name in scenario_names(assumptions_file, scenarios):
            r = run_tool(ToolCall(tool="run_dcf", args={"scenario": name, "include_sensitivity": name == base}), env)
            if not r.ok:
                errors.append(f"Scenario '{name}': {r.error}")
                continue
            d = r.detail
            per_share = next(n for n in r.numbers if n.number_id.endswith("#value_per_share"))
            bars.append(ScenarioBar(scenario=name, label=d["description"], value=per_share.value,
                                    display=per_share.display, run_id=d["run_id"]))
            if name == base:
                base_result = r
    if base_result is None:
        if not errors:
            errors.append(f"Scenario '{base}' is not defined in the assumptions file.")
        return DCFTabView(scenarios=bars, base=None, base_detail=None, heatmap=[], waterfall=[],
                          per_share_unit=None, errors=errors)
    d = base_result.detail
    return DCFTabView(scenarios=bars, base=dcf_path(base_result, env.display, assumptions_file, footer),
                      base_detail=d, heatmap=heatmap_cells(d, env.display), waterfall=waterfall_steps(d, env.display),
                      per_share_unit=d["per_share_unit"], errors=errors)
