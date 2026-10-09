"""Read DCF assumptions from YAML. Every assumption needs a value, a rationale and a source.

The loader REFUSES (raises AssumptionError) if any assumption anywhere in the file has a
missing or blank rationale or source, uses an unknown name, or has a value of the wrong kind
(e.g. a rate written as 12 instead of 0.12). It does NOT refuse when a required assumption is
simply absent: that is reported by the 'required_inputs_present' check (checks.py), which
run_dcf treats as blocking.

File shape (see tests/fixtures/dcf_toy_assumptions.yaml for a commented example):
    ticker, label, units: {money, shares}, facts_basis, shared: {<assumptions>}, scenarios: {<name>: {...}}
A scenario's own assumptions override `shared` ones of the same name.

An assumption is written in one of two ways (D2):
  - typed:    {value, rationale, source}
  - database: {from_db: [metric_id, ...], rationale, source, adjustments: [{value, rationale, source}],
               treat_as}  (base-year revenue and bridge items only, see DB_INPUT_KINDS)
    The value is the sum of those facts for the fiscal year ending on the valuation date, in the
    file's `facts_basis` (fetched by dcf/db_inputs.py at run time), plus the adjustments. Each
    adjustment is a judgement call with its own value, rationale and source (signed: -609 subtracts).
    lease_liabilities must say `treat_as`: 'debt' (subtracted in the bridge) or 'operating_cost'
    (lease cost stays inside EBIT, so the bridge uses 0). The loader leaves `value` empty for these;
    run_dcf fills it in, and refuses if a fact is missing. It never falls back to a typed number.
"""
import datetime
import hashlib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from erp.config import REPO
from erp.units import MONEY_UNITS, SHARE_UNITS


class AssumptionError(ValueError):
    pass


# name -> kind. Generic DCF inputs (PROJECT_PLAN.md 5.2), not company-specific.
#   date: ISO date; years: whole number >= 1; positive: > 0; amount: >= 0;
#   rate: decimal between -1 and 1; rate_per_year: a rate, or a list of rates (one per year);
#   number: any number.
REQUIRED_ASSUMPTIONS = {
    "valuation_date": "date",
    "forecast_horizon_years": "years",
    "base_year_revenue": "positive",
    "revenue_growth": "rate_per_year",
    "ebit_margin": "rate_per_year",
    "tax_rate": "rate_per_year",
    "da_pct_revenue": "rate_per_year",
    "capex_pct_revenue": "rate_per_year",
    "nwc_pct_incremental_revenue": "rate_per_year",
    "risk_free_rate": "rate",
    "equity_risk_premium": "rate",
    "beta": "number",
    "debt_weight": "rate",
    "cost_of_debt_pre_tax": "rate",
    "debt_tax_rate": "rate",
    "terminal_growth": "rate",
    "cash_and_investments": "amount",
    "debt": "amount",
    "lease_liabilities": "amount",
    "minority_interest": "amount",
    "diluted_shares": "positive",
}
ENTRY_KEYS = {"value", "rationale", "source"}
# Assumptions that may be read from the facts database, and which units table their facts use.
DB_INPUT_KINDS = {
    "base_year_revenue": "money",
    "cash_and_investments": "money",
    "debt": "money",
    "lease_liabilities": "money",
    "minority_interest": "money",
    "diluted_shares": "shares",
}
DB_ENTRY_KEYS = {"from_db", "rationale", "source", "adjustments", "treat_as"}
ADJUSTMENT_KEYS = {"value", "rationale", "source"}
LEASE_TREATMENTS = ("operating_cost", "debt")
TOP_LEVEL_KEYS = {"ticker", "label", "units", "facts_basis", "shared", "scenarios"}
SCENARIO_META_KEYS = {"description"}


class Adjustment(BaseModel):
    """A judgement adjustment to a database figure, in the file's units (signed)."""
    value: float
    rationale: str
    source: str


class Assumption(BaseModel):
    value: Any                   # None for a database input until run_dcf resolves it
    rationale: str
    source: str
    defined_in: str              # 'shared' or 'scenario:<name>'
    from_db: list[str] | None = None      # metric_ids summed from the facts database
    adjustments: list[Adjustment] = []
    treat_as: str | None = None           # lease_liabilities only: 'debt' or 'operating_cost'


class Scenario(BaseModel):
    ticker: str
    label: str
    scenario: str
    description: str
    units: dict[str, str]
    facts_basis: str | None              # basis of database inputs (e.g. 'consolidated')
    assumptions: dict[str, Assumption]   # only the ones present; see checks.check_required_inputs
    file: str
    sha256: str
    yaml_text: str

    def value(self, name: str):
        return self.assumptions[name].value

    def missing(self) -> list[str]:
        return [n for n in REQUIRED_ASSUMPTIONS if n not in self.assumptions]


# ---------- validation of one entry ----------

def _where(block: str) -> str:
    return "shared" if block == "shared" else f"scenario {block.split(':', 1)[1]!r}"


def _check_text(label: str, entry: dict, where: str) -> None:
    for field in ("rationale", "source"):
        text = entry.get(field)
        if not isinstance(text, str) or not text.strip():
            raise AssumptionError(f"{label} ({where}) has a missing or empty {field}. "
                                  f"Every assumption needs a value, rationale and source. Refusing to run.")


def _check_db_entry(name: str, entry: dict, where: str) -> None:
    if "value" in entry:
        raise AssumptionError(f"assumption {name!r} ({where}) has both 'value' and 'from_db'; "
                              "a database input must not also carry a typed number")
    if name not in DB_INPUT_KINDS:
        raise AssumptionError(f"assumption {name!r} ({where}) cannot use from_db; only "
                              f"{sorted(DB_INPUT_KINDS)} can be read from the database")
    extra = set(entry) - DB_ENTRY_KEYS
    if extra:
        raise AssumptionError(f"assumption {name!r} ({where}) has unexpected keys {sorted(extra)}; "
                              f"allowed: {sorted(DB_ENTRY_KEYS)}")
    metrics = entry["from_db"]
    if not isinstance(metrics, list) or not metrics or not all(isinstance(m, str) and m.strip() for m in metrics):
        raise AssumptionError(f"assumption {name!r} ({where}): from_db must be a non-empty list of metric ids, "
                              f"got {metrics!r}")
    if len(set(metrics)) != len(metrics):
        raise AssumptionError(f"assumption {name!r} ({where}): a metric is listed twice in from_db {metrics}")
    _check_text(f"assumption {name!r}", entry, where)
    adjustments = entry.get("adjustments", [])
    if not isinstance(adjustments, list):
        raise AssumptionError(f"assumption {name!r} ({where}): adjustments must be a list of "
                              "{value, rationale, source} blocks")
    for n, adj in enumerate(adjustments, 1):
        label = f"adjustment {n} of {name!r}"
        if not isinstance(adj, dict):
            raise AssumptionError(f"{label} ({where}) must be a block with value, rationale and source")
        extra = set(adj) - ADJUSTMENT_KEYS
        if extra:
            raise AssumptionError(f"{label} ({where}) has unexpected keys {sorted(extra)}; "
                                  "allowed: value, rationale, source")
        if not _is_number(adj.get("value")):
            raise AssumptionError(f"{label} ({where}) must have a number as its value, got {adj.get('value')!r}")
        _check_text(label, adj, where)
    if name == "lease_liabilities":
        if entry.get("treat_as") not in LEASE_TREATMENTS:
            raise AssumptionError(f"assumption 'lease_liabilities' ({where}) read from the database must say "
                                  f"treat_as: one of {LEASE_TREATMENTS}; got {entry.get('treat_as')!r}")
    elif "treat_as" in entry:
        raise AssumptionError(f"assumption {name!r} ({where}): treat_as is only for lease_liabilities")


def _check_entry(name: str, entry, block: str) -> None:
    where = _where(block)
    if name not in REQUIRED_ASSUMPTIONS:
        raise AssumptionError(f"unknown assumption {name!r} ({where}); known names: {sorted(REQUIRED_ASSUMPTIONS)}")
    if not isinstance(entry, dict):
        raise AssumptionError(f"assumption {name!r} ({where}) must be a block with value, rationale and source; "
                              f"got {entry!r}. Refusing to run.")
    if "from_db" in entry:
        _check_db_entry(name, entry, where)
        return
    extra = set(entry) - ENTRY_KEYS
    if extra:
        raise AssumptionError(f"assumption {name!r} ({where}) has unexpected keys {sorted(extra)}; "
                              f"allowed: value, rationale, source")
    if "value" not in entry or entry["value"] is None:
        raise AssumptionError(f"assumption {name!r} ({where}) has no value. Refusing to run.")
    _check_text(f"assumption {name!r}", entry, where)


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_rate(name: str, v, where: str) -> None:
    if not _is_number(v):
        raise AssumptionError(f"{name} ({where}) must be a number, got {v!r}")
    if not -1 < v < 1:
        raise AssumptionError(f"{name} ({where}) is {v}; write rates as decimals (0.12 for 12%)")


def _normalise_value(name: str, value, horizon, where: str):
    """Check the value's kind and return it in normal form (dates as ISO text, per-year as a list)."""
    kind = REQUIRED_ASSUMPTIONS[name]
    if kind == "date":
        if isinstance(value, datetime.date):
            return value.isoformat()
        try:
            return datetime.date.fromisoformat(str(value)).isoformat()
        except ValueError:
            raise AssumptionError(f"{name} ({where}) must be an ISO date like 2026-03-31, got {value!r}") from None
    if kind == "years":
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise AssumptionError(f"{name} ({where}) must be a whole number of years, at least 1; got {value!r}")
        return value
    if kind in ("positive", "amount", "number"):
        if not _is_number(value):
            raise AssumptionError(f"{name} ({where}) must be a number, got {value!r}")
        if kind == "positive" and value <= 0:
            raise AssumptionError(f"{name} ({where}) must be greater than 0, got {value}")
        if kind == "amount" and value < 0:
            raise AssumptionError(f"{name} ({where}) must not be negative, got {value}")
        return value
    if kind == "rate":
        _check_rate(name, value, where)
        return value
    # rate_per_year
    values = value if isinstance(value, list) else None
    if values is None:
        _check_rate(name, value, where)
        return [value] * horizon if horizon else value
    for v in values:
        _check_rate(name, v, where)
    if horizon and len(values) != horizon:
        raise AssumptionError(f"{name} ({where}) has {len(values)} values; forecast_horizon_years is {horizon}")
    return values


# ---------- loading ----------

def _read(path: Path) -> tuple[dict, str]:
    if not path.exists():
        raise AssumptionError(f"assumptions file not found: {path}")
    text = path.read_text()
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise AssumptionError(f"{path} is not valid YAML: {e}") from None
    if not isinstance(data, dict):
        raise AssumptionError(f"{path} must be a YAML mapping")
    return data, text


def _resolve(data: dict, name: str) -> dict[str, Assumption]:
    block = data["scenarios"][name] or {}
    if not isinstance(block, dict):
        raise AssumptionError(f"scenario {name!r} must be a mapping")
    merged = {}
    for source_block, entries in (("shared", data.get("shared") or {}), (f"scenario:{name}", block)):
        for key, entry in entries.items():
            if source_block != "shared" and key in SCENARIO_META_KEYS:
                continue
            _check_entry(key, entry, source_block)
            merged[key] = (entry, source_block)

    horizon = None     # per-year lists are checked against it (if it is missing, the required check fails)
    if "forecast_horizon_years" in merged:
        entry, source_block = merged["forecast_horizon_years"]
        horizon = _normalise_value("forecast_horizon_years", entry["value"], None, _where(source_block))
    out = {}
    for key, (entry, source_block) in merged.items():
        if "from_db" in entry:     # value filled in by run_dcf from the database (dcf/db_inputs.py)
            out[key] = Assumption(
                value=None, rationale=entry["rationale"].strip(), source=entry["source"].strip(),
                defined_in=source_block, from_db=list(entry["from_db"]), treat_as=entry.get("treat_as"),
                adjustments=[Adjustment(value=a["value"], rationale=a["rationale"].strip(), source=a["source"].strip())
                             for a in entry.get("adjustments", [])])
            continue
        out[key] = Assumption(value=_normalise_value(key, entry["value"], horizon, _where(source_block)),
                              rationale=entry["rationale"].strip(), source=entry["source"].strip(),
                              defined_in=source_block)
    return out


def load_scenario(path, scenario: str) -> Scenario:
    """Validate the whole file (every scenario), then return the named scenario resolved."""
    path = Path(path)
    data, text = _read(path)

    unknown = set(data) - TOP_LEVEL_KEYS
    if unknown:
        raise AssumptionError(f"{path}: unknown top-level keys {sorted(unknown)}; allowed: {sorted(TOP_LEVEL_KEYS)}")
    for key in ("ticker", "units", "scenarios"):
        if not data.get(key):
            raise AssumptionError(f"{path}: missing {key!r}")
    units = data["units"]
    if units.get("money") not in MONEY_UNITS:
        raise AssumptionError(f"money unit {units.get('money')!r} not supported; use one of {list(MONEY_UNITS)}")
    if units.get("shares") not in SHARE_UNITS:
        raise AssumptionError(f"share unit {units.get('shares')!r} not supported; use one of {list(SHARE_UNITS)}")

    resolved = {name: _resolve(data, name) for name in data["scenarios"]}
    uses_db = any(a.from_db for r in resolved.values() for a in r.values())
    facts_basis = data.get("facts_basis")
    if uses_db and (not isinstance(facts_basis, str) or not facts_basis.strip()):
        raise AssumptionError(f"{path}: some assumptions are read from the database (from_db), so the file needs "
                              "facts_basis (e.g. consolidated)")
    if scenario not in resolved:
        raise AssumptionError(f"unknown scenario {scenario!r}; defined scenarios: {list(resolved)}")

    try:
        shown = str(path.resolve().relative_to(REPO))
    except ValueError:
        shown = str(path)
    return Scenario(
        ticker=str(data["ticker"]), label=str(data.get("label") or ""), scenario=scenario,
        description=str((data["scenarios"][scenario] or {}).get("description") or ""),
        units={"money": units["money"], "shares": units["shares"]},
        facts_basis=facts_basis.strip() if isinstance(facts_basis, str) else None, assumptions=resolved[scenario],
        file=shown, sha256=hashlib.sha256(text.encode()).hexdigest(), yaml_text=text,
    )
