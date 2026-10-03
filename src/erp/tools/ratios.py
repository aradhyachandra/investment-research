"""compute_ratio: deterministic ratios from stored facts. No LLM inside.

Which metrics a ratio uses is defined in config/ratios.yaml. This module only knows how
to do the two kinds of arithmetic (quotient, year-on-year growth), fetch inputs with
get_financial_fact, and record every result as a computed_metric row (formula, input
fact_ids, git SHA). A ratio is verified only if every input fact is verified.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel

from erp.config import ConfigError
from erp.periods import prior_year_label
from erp.tools.facts import FactResult, company_info, get_financial_fact
from erp.version import REPO, code_version

RATIOS_CONFIG = REPO / "config" / "ratios.yaml"
METRICS_CONFIG = REPO / "config" / "metrics.yaml"

COMMON_FIELDS = ("display_name", "kind", "multiplier", "unit", "formula_version", "definition")
KIND_FIELDS = {"quotient": ("numerator", "denominator"), "yoy_growth": ("metric",)}


class RatioError(ValueError):
    pass


class UnknownRatioError(RatioError):
    pass


class RatioInput(BaseModel):
    role: str            # 'numerator' / 'denominator' / 'current' / 'prior_year'
    fact: FactResult


class RatioResult(BaseModel):
    computed_id: int     # row in computed_metric
    ratio_id: str
    display_name: str
    ticker: str
    period_label: str
    basis: str
    value: float
    unit: str
    formula: str         # with the actual periods filled in, e.g. 'profit_after_tax[FY26] / ...'
    formula_version: str
    inputs: list[RatioInput]
    input_fact_ids: list[int]
    verified: bool       # True only if every input fact is verified
    code_version: str
    computed_at: str


# ---------- config ----------

def load_ratios(path: Path = RATIOS_CONFIG, metrics_config: Path = METRICS_CONFIG) -> dict:
    with open(path) as f:
        ratios = yaml.safe_load(f)["ratios"]
    with open(metrics_config) as f:
        metric_ids = set(yaml.safe_load(f)["metrics"])
    for ratio_id, r in ratios.items():
        missing = [k for k in COMMON_FIELDS if k not in r]
        if missing:
            raise ConfigError(f"ratio {ratio_id!r} missing fields: {missing}")
        if r["kind"] not in KIND_FIELDS:
            raise ConfigError(f"ratio {ratio_id!r}: unknown kind {r['kind']!r}, expected one of {list(KIND_FIELDS)}")
        for field in KIND_FIELDS[r["kind"]]:
            if field not in r:
                raise ConfigError(f"ratio {ratio_id!r} missing field {field!r}")
            if r[field] not in metric_ids:
                raise ConfigError(f"ratio {ratio_id!r}: {field} {r[field]!r} is not a metric in {metrics_config}")
    return ratios


# ---------- arithmetic ----------

def quotient(numerator: float, denominator: float, multiplier: float) -> float:
    if denominator == 0:
        raise RatioError("denominator is zero")
    return numerator / denominator * multiplier


def growth_percent(current: float, prior: float, multiplier: float = 100) -> float:
    if prior <= 0:
        # Growth over a zero or negative base has no meaningful sign or size.
        raise RatioError(f"prior-year base is {prior}; growth needs a positive base")
    return (current - prior) / prior * multiplier


# ---------- the tool ----------

def compute_ratio(conn: sqlite3.Connection, ticker: str, ratio_id: str, period_label: str,
                  basis: str = "consolidated", *, ratios_config: Path = RATIOS_CONFIG) -> RatioResult:
    ratios = load_ratios(ratios_config)
    if ratio_id not in ratios:
        raise UnknownRatioError(f"unknown ratio {ratio_id!r}; defined ratios: {sorted(ratios)}")
    r = ratios[ratio_id]
    company_id, fy_end_month = company_info(conn, ticker)

    def fact(metric_id, label):
        return get_financial_fact(conn, ticker, metric_id, label, basis)

    if r["kind"] == "quotient":
        num, den = fact(r["numerator"], period_label), fact(r["denominator"], period_label)
        if num.unit != den.unit:
            raise RatioError(f"{ratio_id}: numerator unit {num.unit} differs from denominator unit {den.unit}")
        label = num.period_label
        value = quotient(num.value, den.value, r["multiplier"])
        inputs = [RatioInput(role="numerator", fact=num), RatioInput(role="denominator", fact=den)]
        formula = f"{r['numerator']}[{label}] / {r['denominator']}[{label}] * {r['multiplier']}"
    else:  # yoy_growth
        m = r["metric"]
        cur = fact(m, period_label)
        label = cur.period_label
        prior_label = prior_year_label(label, fy_end_month)
        prior = fact(m, prior_label)
        value = growth_percent(cur.value, prior.value, r["multiplier"])
        inputs = [RatioInput(role="current", fact=cur), RatioInput(role="prior_year", fact=prior)]
        formula = f"({m}[{label}] - {m}[{prior_label}]) / {m}[{prior_label}] * {r['multiplier']}"

    fact_ids = [i.fact.fact_id for i in inputs]
    verified = all(i.fact.verified for i in inputs)
    version = code_version()
    computed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # The plan's DDL has no formula/basis/verified columns, so they go in inputs_json with the fact_ids.
    inputs_json = json.dumps({
        "fact_ids": fact_ids,
        "inputs": [{"role": i.role, "fact_id": i.fact.fact_id, "metric_id": i.fact.metric_id,
                    "period": i.fact.period_label} for i in inputs],
        "formula": formula,
        "basis": basis,
        "verified": verified,
    })
    period_id = conn.execute(
        "SELECT period_id FROM period WHERE company_id = ? AND label = ?", (company_id, label)).fetchone()[0]
    with conn:
        cur_row = conn.execute(
            "INSERT INTO computed_metric (company_id, ratio_id, period_id, value, unit, formula_version,"
            " inputs_json, code_version, computed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (company_id, ratio_id, period_id, value, r["unit"], r["formula_version"], inputs_json,
             version, computed_at))

    return RatioResult(
        computed_id=cur_row.lastrowid, ratio_id=ratio_id, display_name=r["display_name"], ticker=ticker,
        period_label=label, basis=basis, value=value, unit=r["unit"], formula=formula,
        formula_version=r["formula_version"], inputs=inputs, input_fact_ids=fact_ids,
        verified=verified, code_version=version, computed_at=computed_at,
    )
