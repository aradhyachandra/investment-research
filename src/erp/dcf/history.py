"""D4: the DCF's operating assumptions beside the company's own record.

For each operating assumption (the drivers build_fcff uses), compute the same quantity from facts in
the database for the fiscal years ending with the valuation year (config/dcf.yaml `history`), then
compare each scenario value with the historical range. Plain arithmetic in code, no LLM.

The checks never block a run and never touch the valuation: they are reported next to the engine's
own checks, not inside them, so `all_checks_passed` keeps its meaning. A "warn" says an assumption
is outside what the company has done in these years: a deliberate departure or a mistake, for a
human to judge. It is not a verdict on the value.

A year whose facts are missing is shown as n/a with the reason (e.g. FY23 growth needs FY22). If no
history can be read at all (e.g. a company with no facts), every check warns and `note` says why.
"""
import sqlite3
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from erp.config import REPO, ConfigError
from erp.dcf.assumptions import Assumption, Scenario, load_scenario
from erp.periods import PeriodError, fiscal_year_ending_on, prior_year_label
from erp.tools.facts import FactLookupError, FactResult, company_info, get_financial_fact
from erp.tools.ratios import RatioError, _operand, cagr_percent, growth_percent

DCF_CONFIG = REPO / "config" / "dcf.yaml"

# The drivers build_fcff uses (dcf/engine.py): an engine contract, not a company detail.
OPERATING_ASSUMPTIONS = ("revenue_growth", "ebit_margin", "tax_rate", "da_pct_revenue", "capex_pct_revenue",
                         "nwc_pct_incremental_revenue")


class HistoryYear(BaseModel):
    period: str                       # e.g. 'FY26', or 'FY23-FY26' for a CAGR
    value: float | None               # decimal, same scale as the assumption; None = not computable
    numerator: float | None = None
    denominator: float | None = None
    formula: str | None = None        # with periods filled in
    fact_ids: list[int] = []
    missing: str | None = None        # why there is no value


class HistoryRow(BaseModel):
    assumption: str
    label: str
    definition: str
    definition_match: Literal["same", "approximate", "none"]
    match_note: str | None = None
    years: list[HistoryYear]
    min: float | None
    max: float | None
    average: float | None
    cagr: HistoryYear | None = None   # revenue growth: compound growth over the window
    facts: list[FactResult]           # every fact used, once (for page chips)


class HistoryCheck(BaseModel):
    check_id: str                     # 'history_<assumption>'
    assumption: str
    description: str
    status: Literal["pass", "warn"]
    blocking: bool = False            # never blocks
    values: list[float]               # the scenario's value(s); one per forecast year for a list
    tolerance: float
    outside: list[int] = []           # 1-based positions in `values` outside the band
    detail: str


class DCFHistory(BaseModel):
    periods: list[str]
    rows: list[HistoryRow]
    checks: list[HistoryCheck]
    unverified_fact_ids: list[str]    # facts used here that no human has checked yet
    tolerance_rule: str
    note: str | None = None           # e.g. why no history could be read


# ---------- config ----------

def load_history_config(path: Path = DCF_CONFIG) -> dict:
    with open(path) as f:
        cfg = (yaml.safe_load(f) or {}).get("history")
    if not cfg:
        raise ConfigError(f"{path}: no 'history' section")
    if type(cfg.get("years")) is not int or cfg["years"] < 2:
        raise ConfigError(f"{path}: history.years must be a whole number of at least 2")
    tol = cfg.get("tolerance") or {}
    if not isinstance(tol.get("default"), (int, float)) or tol["default"] < 0:
        raise ConfigError(f"{path}: history.tolerance.default must be a number >= 0")
    for name, e in (cfg.get("assumptions") or {}).items():
        if e.get("definition_match") not in ("same", "approximate", "none"):
            raise ConfigError(f"{path}: history.assumptions.{name}.definition_match must be same, approximate or none")
        if e["definition_match"] != "none" and e.get("kind") not in ("yoy_growth", "quotient"):
            raise ConfigError(f"{path}: history.assumptions.{name}.kind must be yoy_growth or quotient")
    return cfg


def tolerance_for(cfg: dict, name: str) -> float:
    return float((cfg["tolerance"].get("by_assumption") or {}).get(name, cfg["tolerance"]["default"]))


def tolerance_rule(cfg: dict, periods: list[str]) -> str:
    window = f"{periods[0]}-{periods[-1]}" if periods else f"the last {cfg['years']} fiscal years"
    tol = cfg["tolerance"]
    by = ", ".join(f"{k} {v}" for k, v in (tol.get("by_assumption") or {}).items())
    return (f"Pass if every scenario value lies within the {window} minimum-maximum, widened by "
            f"{tol['default']} on each side" + (f" ({by})" if by else "") + "; otherwise warn. "
            "Placeholder rule in config/dcf.yaml, TO VERIFY. A warning never stops a run.")


# ---------- history ----------

def window(conn: sqlite3.Connection, ticker: str, valuation_date: str, years: int) -> tuple[list[str], int]:
    """The `years` fiscal-year labels ending with the year that ends on the valuation date, oldest first."""
    _, fy_end_month = company_info(conn, ticker)
    if fy_end_month is None:
        raise PeriodError(f"no fiscal year end month recorded for {ticker}")
    last = fiscal_year_ending_on(date.fromisoformat(valuation_date), fy_end_month)
    labels = [last]
    for _ in range(years - 1):
        labels.insert(0, prior_year_label(labels[0], fy_end_month))
    return labels, fy_end_month


class _Facts:
    """Fact lookups for one company and basis, remembering every fact used."""

    def __init__(self, conn, ticker, basis):
        self.conn, self.ticker, self.basis, self.used = conn, ticker, basis, {}

    def __call__(self, metric_id: str, label: str) -> FactResult:
        f = get_financial_fact(self.conn, self.ticker, metric_id, label, self.basis)
        self.used[f.fact_id] = f
        return f


LOOKUP_ERRORS = (FactLookupError, PeriodError, RatioError, ConfigError)   # ConfigError: no company config


def _year(entry: dict, label: str, facts: _Facts, prior_of) -> HistoryYear:
    try:
        if entry["kind"] == "yoy_growth":
            m = entry["metric"]
            cur, prior = facts(m, label), facts(m, prior_of(label))
            return HistoryYear(period=label, value=growth_percent(cur.value, prior.value, 1), numerator=cur.value,
                               denominator=prior.value, fact_ids=[cur.fact_id, prior.fact_id],
                               formula=f"({m}[{label}] - {m}[{prior.period_label}]) / {m}[{prior.period_label}]")
        num = _operand(entry["numerator"], "numerator", label, facts, prior_of)
        den_spec = entry["denominator"]
        if isinstance(den_spec, dict) and "change" in den_spec:
            m = den_spec["change"]
            cur, prior = facts(m, label), facts(m, prior_of(label))
            den_value, den_ids = cur.value - prior.value, [cur.fact_id, prior.fact_id]
            den_formula = f"({m}[{label}] - {m}[{prior.period_label}])"
        else:
            den = _operand(den_spec, "denominator", label, facts, prior_of)
            den_value, den_ids, den_formula = den.value, [i.fact.fact_id for i in den.inputs], den.formula
        if den_value <= 0:
            return HistoryYear(period=label, value=None, missing=f"denominator is {den_value:g}, not positive")
        return HistoryYear(period=label, value=num.value / den_value, numerator=num.value, denominator=den_value,
                           fact_ids=[i.fact.fact_id for i in num.inputs] + den_ids,
                           formula=f"{num.formula} / {den_formula}")
    except LOOKUP_ERRORS as e:
        return HistoryYear(period=label, value=None, missing=str(e))


def history_row(name: str, entry: dict | None, periods: list[str], facts: _Facts, prior_of) -> HistoryRow:
    if entry is None or entry.get("definition_match") == "none":
        return HistoryRow(
            assumption=name, label=(entry or {}).get("label", name), definition=(entry or {}).get("definition", ""),
            definition_match="none", match_note=(entry or {}).get("match_note") or
            "No history definition in config/dcf.yaml: this assumption cannot be matched to the company's record.",
            years=[HistoryYear(period=p, value=None, missing="no history definition") for p in periods],
            min=None, max=None, average=None, facts=[])
    years = [_year(entry, p, facts, prior_of) for p in periods]
    values = [y.value for y in years if y.value is not None]
    cagr = None
    if entry.get("cagr") and len(periods) > 1:
        m, n = entry["metric"], len(periods) - 1
        label = f"{periods[0]}-{periods[-1]}"
        try:
            first, last = facts(m, periods[0]), facts(m, periods[-1])
            cagr = HistoryYear(period=label, value=cagr_percent(last.value, first.value, n, 1), numerator=last.value,
                               denominator=first.value, fact_ids=[last.fact_id, first.fact_id],
                               formula=f"({m}[{periods[-1]}] / {m}[{periods[0]}]) ^ (1 / {n}) - 1")
        except LOOKUP_ERRORS as e:
            cagr = HistoryYear(period=label, value=None, missing=str(e))
    ids = [i for y in years + ([cagr] if cagr else []) for i in y.fact_ids]
    used = [facts.used[i] for i in dict.fromkeys(ids)]
    return HistoryRow(
        assumption=name, label=entry.get("label", name), definition=" ".join(entry["definition"].split()),
        definition_match=entry["definition_match"],
        match_note=" ".join(entry["match_note"].split()) if entry.get("match_note") else None,
        years=years, min=min(values) if values else None, max=max(values) if values else None,
        average=sum(values) / len(values) if values else None, cagr=cagr, facts=used)


# ---------- checks ----------

def _pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def history_check(row: HistoryRow, a: Assumption | None, tolerance: float, periods: list[str]) -> HistoryCheck:
    desc = f"{row.label}: scenario value(s) inside the {periods[0]}-{periods[-1]} range" if periods else row.label
    raw = [] if a is None else (a.value if isinstance(a.value, list) else [a.value])
    values = [float(v) for v in raw]
    if len(set(values)) == 1:
        values = values[:1]           # a single rate (the loader repeats it for every forecast year)
    base = dict(check_id=f"history_{row.assumption}", assumption=row.assumption, description=desc, values=values,
                tolerance=tolerance)
    if row.definition_match == "none":
        return HistoryCheck(**base, status="warn", detail="definition cannot be matched to history; not compared")
    if row.min is None:
        return HistoryCheck(**base, status="warn", detail="no historical value could be computed; not compared")
    lo, hi = row.min - tolerance, row.max + tolerance
    below = [i for i, v in enumerate(values, 1) if v < lo]
    above = [i for i, v in enumerate(values, 1) if v > hi]
    rng = f"historical range {_pct(row.min)} to {_pct(row.max)}" + (f" (+/- {_pct(tolerance)})" if tolerance else "")
    approx = " Definitions differ (approximate match)." if row.definition_match == "approximate" else ""
    if not below and not above:
        return HistoryCheck(**base, status="pass", detail=f"inside the {rng}.{approx}")

    def where(idx, side):
        if not idx:
            return ""
        if len(values) == 1:
            return f"{side} the {rng}"
        return f"forecast year{'s' if len(idx) > 1 else ''} {', '.join(map(str, idx))} {side} the {rng}"
    parts = [p for p in (where(above, "above"), where(below, "below")) if p]
    return HistoryCheck(**base, status="warn", outside=sorted(below + above), detail="; ".join(parts) + "." + approx)


# ---------- entry points ----------

def history_for(conn: sqlite3.Connection, ticker: str, s: Scenario, cfg: dict) -> DCFHistory:
    """History table and checks for one loaded scenario. Never raises for missing data."""
    entries = cfg.get("assumptions") or {}
    names = list(OPERATING_ASSUMPTIONS)
    note, periods, prior_of = None, [], None
    try:
        periods, fy_end = window(conn, ticker, s.assumptions["valuation_date"].value, cfg["years"])
        prior_of = lambda lbl: prior_year_label(lbl, fy_end)   # noqa: E731
    except (KeyError, ValueError, ConfigError, FactLookupError, PeriodError) as e:
        note = f"No history could be read: {e}"
    facts = _Facts(conn, ticker, s.facts_basis or "consolidated")
    if periods:
        rows = [history_row(n, entries.get(n), periods, facts, prior_of) for n in names]
        if all(r.min is None for r in rows):
            note = (f"No history could be read from the facts database for {periods[0]}-{periods[-1]} "
                    f"({s.facts_basis or 'consolidated'}).")
    else:
        rows = [HistoryRow(assumption=n, label=(entries.get(n) or {}).get("label", n),
                           definition=" ".join((entries.get(n) or {}).get("definition", "").split()),
                           definition_match=(entries.get(n) or {}).get("definition_match", "none"),
                           years=[], min=None, max=None, average=None, facts=[]) for n in names]
    checks = [history_check(r, s.assumptions.get(r.assumption), tolerance_for(cfg, r.assumption), periods)
              for r in rows]
    unverified = list(dict.fromkeys(f"fact:{f.fact_id}" for r in rows for f in r.facts if not f.verified))
    return DCFHistory(periods=periods, rows=rows, checks=checks, unverified_fact_ids=unverified,
                      tolerance_rule=tolerance_rule(cfg, periods), note=note)


def assumptions_vs_history(conn: sqlite3.Connection, ticker: str, scenario: str, assumptions_path,
                           *, dcf_config: Path = DCF_CONFIG) -> DCFHistory:
    return history_for(conn, ticker, load_scenario(assumptions_path, scenario), load_history_config(dcf_config))
