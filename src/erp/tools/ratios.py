"""compute_ratio: deterministic ratios from stored facts. No LLM inside.

Which metrics a ratio uses is defined in config/ratios.yaml. This module only knows how
to do the two kinds of arithmetic (quotient, year-on-year growth), fetch inputs with
get_financial_fact, and record every result as a computed_metric row (formula, input
fact_ids, git SHA). A ratio is verified only if every input fact is verified.

A quotient's numerator or denominator is a metric_id, or (D1) one of two operands:
  {sum: [{metric, sign}, ...]}   sign x value added up, same period (e.g. EBIT, total capex)
  {average: metric}              (value this period + value one fiscal year earlier) / 2
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel

from erp.config import REPO, ConfigError
from erp.periods import prior_year_label
from erp.tools.facts import FactResult, company_info, get_financial_fact
from erp.version import code_version

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


class Operand(BaseModel):
    value: float
    inputs: list[RatioInput]
    formula: str


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
    # Quotients only: the computed numerator and denominator (e.g. EBIT, average equity), and the
    # config's name for a sum/average operand. None for growth ratios.
    numerator_value: float | None = None
    denominator_value: float | None = None
    numerator_label: str | None = None
    denominator_label: str | None = None


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
            if r["kind"] == "quotient":
                _check_operand(ratio_id, field, r[field], metric_ids, metrics_config)
            elif r[field] not in metric_ids:
                raise ConfigError(f"ratio {ratio_id!r}: {field} {r[field]!r} is not a metric in {metrics_config}")
    return ratios


def _check_operand(ratio_id, field, spec, metric_ids, metrics_config) -> None:
    where = f"ratio {ratio_id!r}: {field}"
    if isinstance(spec, str):
        if spec not in metric_ids:
            raise ConfigError(f"{where} {spec!r} is not a metric in {metrics_config}")
        return
    if not isinstance(spec, dict) or len(spec) != 1 or next(iter(spec)) not in ("sum", "average"):
        raise ConfigError(f"{where} must be a metric_id, {{sum: [...]}} or {{average: metric_id}}, got {spec!r}")
    if "average" in spec:
        if spec["average"] not in metric_ids:
            raise ConfigError(f"{where}: average of {spec['average']!r}, which is not a metric in {metrics_config}")
        return
    terms = spec["sum"]
    if not isinstance(terms, list) or len(terms) < 2:
        raise ConfigError(f"{where}: a sum needs at least two terms")
    for t in terms:
        if t.get("metric") not in metric_ids:
            raise ConfigError(f"{where}: sum term {t.get('metric')!r} is not a metric in {metrics_config}")
        if t.get("sign") not in (1, -1):
            raise ConfigError(f"{where}: sign of sum term {t['metric']!r} must be 1 or -1, got {t.get('sign')!r}")


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


def _operand(spec, role: str, label: str, fact, prior_of) -> Operand:
    """Fetch the facts for one side of a quotient and combine them. `fact(metric, label)` looks a
    fact up; `prior_of(label)` gives the period one fiscal year earlier."""
    if isinstance(spec, str):
        f = fact(spec, label)
        return Operand(value=f.value, inputs=[RatioInput(role=role, fact=f)], formula=f"{spec}[{f.period_label}]")
    if "average" in spec:
        m = spec["average"]
        cur = fact(m, label)
        prior = fact(m, prior_of(cur.period_label))
        return Operand(value=(cur.value + prior.value) / 2,
                       inputs=[RatioInput(role=f"{role} (current year end)", fact=cur),
                               RatioInput(role=f"{role} (prior year end)", fact=prior)],
                       formula=f"(({m}[{cur.period_label}] + {m}[{prior.period_label}]) / 2)")
    inputs, value, text = [], 0.0, ""
    for t in spec["sum"]:
        f = fact(t["metric"], label)
        sign = "+" if t["sign"] > 0 else "-"
        value += t["sign"] * f.value
        inputs.append(RatioInput(role=f"{role} ({sign})", fact=f))
        term = f"{t['metric']}[{f.period_label}]"
        text = (f"- {term}" if sign == "-" else term) if not text else f"{text} {sign} {term}"
    return Operand(value=value, inputs=inputs, formula=f"({text})")


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

    extra = {}
    if r["kind"] == "quotient":
        prior_of = lambda lbl: prior_year_label(lbl, fy_end_month)
        num = _operand(r["numerator"], "numerator", period_label, fact, prior_of)
        den = _operand(r["denominator"], "denominator", period_label, fact, prior_of)
        inputs = num.inputs + den.inputs
        units = {i.fact.unit for i in inputs}
        if len(units) > 1:
            raise RatioError(f"{ratio_id}: inputs have different units {sorted(units)}")
        label = inputs[0].fact.period_label
        value = quotient(num.value, den.value, r["multiplier"])
        formula = f"{num.formula} / {den.formula} * {r['multiplier']}"
        extra = dict(numerator_value=num.value, denominator_value=den.value,
                     numerator_label=r.get("numerator_label"), denominator_label=r.get("denominator_label"))
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
        **{k: v for k, v in extra.items() if k.endswith("_value")},
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
        verified=verified, code_version=version, computed_at=computed_at, **extra,
    )
