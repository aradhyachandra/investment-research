"""Altair charts for the DCF and Evaluation tabs (M8.1). Each function takes display records
(dcf_view / eval_view) and returns a chart; no figures are computed here.

Colours: a validated colour-blind-safe set (light surface): blue, orange, aqua. A heatmap uses one
blue ramp (light = low, dark = high). Every bar carries a direct label, so colour is never the only cue.
"""
import altair as alt
import pandas as pd

from erp.ui.dcf_view import HeatCell, ScenarioBar, WaterfallStep
from erp.ui.eval_view import EvalRow

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED = "#1a1d24", "#52514e"
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


def _style(chart: alt.Chart) -> alt.Chart:
    return (chart.configure_axis(grid=False, domainColor="#d9d8d3", tickColor="#d9d8d3", labelColor=MUTED,
                                 titleColor=MUTED, labelFontSize=12, titleFontSize=12, titleFontWeight="normal")
            .configure_view(stroke=None)
            .configure_legend(labelColor=MUTED, titleColor=MUTED, orient="top"))


def scenario_chart(bars: list[ScenarioBar]) -> alt.Chart:
    df = pd.DataFrame([{"Scenario": b.name, "Value": b.value, "Label": b.display, "Description": b.label}
                       for b in bars])
    order = [b.name for b in bars]
    base = alt.Chart(df).encode(
        x=alt.X("Scenario:N", sort=order, title=None, axis=alt.Axis(labelAngle=0, labelFontSize=13)),
        y=alt.Y("Value:Q", title="INR per share", axis=alt.Axis(format=",.0f", grid=True, gridColor="#eeede9")),
        tooltip=[alt.Tooltip("Scenario:N"), alt.Tooltip("Label:N", title="Value per share"),
                 alt.Tooltip("Description:N")])
    bar = base.mark_bar(color=BLUE, cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=56)
    text = base.mark_text(dy=-8, color=INK, fontSize=12).encode(text="Label:N")
    return _style((bar + text).properties(height=300))


def heatmap_chart(cells: list[HeatCell]) -> alt.Chart:
    df = pd.DataFrame([{"WACC": c.wacc, "Terminal growth": c.growth, "w": c.wacc_order, "g": c.growth_order,
                        "Value": c.value, "Cell": c.short, "Label": c.display, "Scenario": c.is_scenario}
                       for c in cells])
    wacc_order = [c.wacc for c in sorted(cells, key=lambda c: c.wacc_order) if c.growth_order == 0]
    growth_order = [c.growth for c in sorted(cells, key=lambda c: c.growth_order) if c.wacc_order == 0]
    enc = dict(x=alt.X("Terminal growth:N", sort=growth_order, axis=alt.Axis(labelAngle=0, orient="top")),
               y=alt.Y("WACC:N", sort=wacc_order),
               tooltip=["WACC:N", "Terminal growth:N", alt.Tooltip("Label:N", title="Value per share")])
    rect = alt.Chart(df).mark_rect(stroke="#fcfcfb", strokeWidth=2, cornerRadius=4).encode(
        color=alt.condition("datum.Value === null", alt.value("#e8e7e3"),
                            alt.Color("Value:Q", scale=alt.Scale(range=BLUE_RAMP), legend=None)), **enc)
    centre = alt.Chart(df[df["Scenario"]]).mark_rect(filled=False, stroke=INK, strokeWidth=2.5,
                                                     cornerRadius=4).encode(**enc)
    # Dark cells get light text: the ramp's upper half (by rank of the value) switches the ink.
    text = alt.Chart(df).mark_text(fontSize=12).encode(
        text="Cell:N",
        color=alt.condition("datum.Value !== null && datum.Value > " + str(df["Value"].median(skipna=True)),
                            alt.value("#ffffff"), alt.value(INK)), **enc)
    return _style((rect + centre + text).properties(height=280))


def waterfall_chart(steps: list[WaterfallStep], money_title: str) -> alt.Chart:
    colours = {"total": BLUE, "add": AQUA, "subtract": ORANGE}
    df = pd.DataFrame([{"Step": s.label, "start": s.start, "end": s.end, "Label": s.display, "kind": s.kind,
                        "top": max(s.start, s.end)} for s in steps])
    order = [s.label for s in steps]
    base = alt.Chart(df).encode(x=alt.X("Step:N", sort=order, title=None, axis=alt.Axis(labelAngle=0, labelLimit=160)))
    bar = base.mark_bar(size=56, cornerRadius=3).encode(
        y=alt.Y("start:Q", title=money_title, axis=alt.Axis(format=",.0f", grid=True, gridColor="#eeede9")),
        y2="end:Q",
        color=alt.Color("kind:N", scale=alt.Scale(domain=list(colours), range=list(colours.values())), legend=None),
        tooltip=[alt.Tooltip("Step:N"), alt.Tooltip("Label:N", title="Value")])
    text = base.mark_text(dy=-8, color=INK, fontSize=12).encode(y="top:Q", text="Label:N")
    return _style((bar + text).properties(height=320))


def eval_chart(rows: list[EvalRow]) -> alt.Chart:
    """Share of questions / claims per headline row, full system vs naive RAG. Label = "k of n"."""
    df = pd.DataFrame([{"Metric": r.metric, "System": r.system, "Share": r.share, "Label": r.text}
                       for r in rows if r.share is not None])
    metrics = list(dict.fromkeys(r.metric for r in rows))
    systems = list(dict.fromkeys(r.system for r in rows))
    base = alt.Chart(df).encode(
        y=alt.Y("Metric:N", sort=metrics, title=None, axis=alt.Axis(labelLimit=320, labelFontSize=12)),
        yOffset=alt.YOffset("System:N", sort=systems),
        tooltip=["Metric:N", "System:N", alt.Tooltip("Label:N", title="Count")])
    bar = base.mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4, height=14).encode(
        x=alt.X("Share:Q", title=None, scale=alt.Scale(domain=[0, 1]),
                axis=alt.Axis(format="%", grid=True, gridColor="#eeede9", tickCount=5)),
        color=alt.Color("System:N", sort=systems, scale=alt.Scale(domain=systems, range=[BLUE, ORANGE][:len(systems)]),
                        title=None))
    text = base.mark_text(align="left", dx=4, color=INK, fontSize=11).encode(x="Share:Q", text="Label:N")
    return _style((bar + text).properties(height=alt.Step(18)))
