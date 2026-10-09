"""D2: fill in DCF inputs that the assumptions file says come from the facts database.

For each assumption written as {from_db: [metric_id, ...], adjustments: [...], treat_as: ...}:
  1. fetch every metric with get_financial_fact for the fiscal year that ends on the valuation
     date, in the file's facts_basis (e.g. consolidated FY26);
  2. convert each fact to the file's unit (units.money or units.shares);
  3. value = sum of the facts + sum of the adjustments (judgement calls from the file, each with
     its own rationale and source);
  4. lease_liabilities with treat_as: operating_cost -> the bridge uses 0 (factor 0), because the
     lease cost already stays inside EBIT. The facts are still fetched and recorded.

Refuses (DCFInputError) if any fact is missing, unknown or ambiguous, or if the valuation date is
not a fiscal year end. It never falls back to a typed number. Plain arithmetic, no LLM.
"""
import sqlite3
from datetime import date

from pydantic import BaseModel

from erp.dcf.assumptions import DB_INPUT_KINDS, REQUIRED_ASSUMPTIONS, Adjustment, Assumption, Scenario
from erp.dcf.engine import DCFError
from erp.periods import PeriodError, fiscal_year_ending_on
from erp.tools.facts import FactLookupError, FactResult, company_info, get_financial_fact
from erp.units import MONEY_UNITS, SHARE_UNITS


class DCFInputError(DCFError):
    """A database input for the DCF could not be read; nothing was run or stored."""


class DBInput(BaseModel):
    assumption: str              # e.g. 'cash_and_investments'
    period: str                  # e.g. 'FY26'
    basis: str
    unit: str                    # the assumptions file's unit for this input
    facts: list[FactResult]
    fact_values: list[float]     # each fact in `unit`
    facts_total: float
    adjustments: list[Adjustment]
    treat_as: str | None
    factor: int                  # 0 when leases are an operating cost, else 1
    value: float                 # what the engine uses: factor x (facts_total + adjustments)


def valuation_period(conn: sqlite3.Connection, ticker: str, valuation_date: str) -> str:
    _, fy_end_month = company_info(conn, ticker)
    try:
        return fiscal_year_ending_on(date.fromisoformat(valuation_date), fy_end_month)
    except PeriodError as e:
        raise DCFInputError(f"refusing to run: database inputs are read for the fiscal year ending on the "
                            f"valuation date, but {e}. Stub periods are not handled.") from None


def _to_unit(f: FactResult, unit: str, table: dict, name: str) -> float:
    if f.unit == unit:
        return f.value
    if f.unit not in table or unit not in table:
        raise DCFInputError(f"refusing to run: {name} uses fact:{f.fact_id} ({f.metric_id}) in {f.unit}, "
                            f"which cannot be converted to the assumptions file's unit {unit}")
    return f.value * table[f.unit] / table[unit]


def resolve_db_input(conn: sqlite3.Connection, ticker: str, name: str, a: Assumption, period: str, basis: str,
                     units: dict[str, str]) -> DBInput:
    kind = DB_INPUT_KINDS[name]
    unit, table = (units["money"], MONEY_UNITS) if kind == "money" else (units["shares"], SHARE_UNITS)
    facts = []
    for metric in a.from_db:
        try:
            facts.append(get_financial_fact(conn, ticker, metric, period, basis))
        except FactLookupError as e:
            raise DCFInputError(f"refusing to run: {name} needs {metric} for {period} ({basis}) from the facts "
                                f"database, and it could not be read: {e}") from None
    values = [_to_unit(f, unit, table, name) for f in facts]
    total = sum(values)
    factor = 0 if a.treat_as == "operating_cost" else 1
    value = factor * (total + sum(adj.value for adj in a.adjustments))
    if value < 0 or (REQUIRED_ASSUMPTIONS[name] == "positive" and value <= 0):
        raise DCFInputError(f"refusing to run: {name} from the database plus adjustments is {value}, "
                            f"which is not allowed for this input")
    return DBInput(assumption=name, period=period, basis=basis, unit=unit, facts=facts, fact_values=values,
                   facts_total=total, adjustments=a.adjustments, treat_as=a.treat_as, factor=factor, value=value)


def resolve_db_inputs(conn: sqlite3.Connection, ticker: str, s: Scenario) -> tuple[dict[str, Assumption], list[DBInput]]:
    """The scenario's assumptions with database inputs filled in, and a record of each one."""
    names = [n for n, a in s.assumptions.items() if a.from_db]
    if not names:
        return dict(s.assumptions), []
    if "valuation_date" not in s.assumptions:
        return dict(s.assumptions), []        # reported by the blocking required-inputs check
    period = valuation_period(conn, ticker, s.assumptions["valuation_date"].value)
    resolved, records = dict(s.assumptions), []
    for name in names:
        rec = resolve_db_input(conn, ticker, name, s.assumptions[name], period, s.facts_basis, s.units)
        resolved[name] = s.assumptions[name].model_copy(update={"value": rec.value})
        records.append(rec)
    return resolved, records


def unverified_fact_ids(records: list[DBInput]) -> list[str]:
    return [f"fact:{f.fact_id}" for r in records for f in r.facts if not f.verified]


def unverified_note(ids: list[str]) -> list[str]:
    if not ids:
        return []
    n = len(ids)
    return [f"This DCF uses {n} {'fact' if n == 1 else 'facts'} not yet verified by a human: {', '.join(ids)}."]
