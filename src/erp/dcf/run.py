"""run_dcf: one named scenario from the assumptions YAML -> full DCF result + a dcf_run row.

Steps: load and validate assumptions (refuses on missing rationale/source) -> blocking checks
-> WACC -> FCFF from drivers -> valuation and bridge -> non-blocking checks -> sensitivity grid
-> store a dcf_run row (full YAML copy, every intermediate, checks, git SHA).

Never takes numbers from an LLM, never uses a market price. The output means "what these
assumptions imply", not a prediction or a recommendation.

Inputs the assumptions file marks `from_db` (base-year revenue and bridge items, D2) are read
from the facts database by dcf/db_inputs.py before anything is computed: their fact ids and pages
go into the dcf_run row and the result, and a missing fact makes the run refuse. Judgement
adjustments to those figures stay in the YAML, each with a rationale and source.

D4: every run also carries the operating assumptions beside the company's own record (dcf/history.py),
with a non-blocking pass/warn check per assumption. Those checks are kept apart from the engine's
`checks` (and from `all_checks_passed`); they never stop a run and never change a value.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel

from erp.config import REPO
from erp.dcf.assumptions import Assumption, AssumptionError, load_scenario
from erp.dcf.history import DCFHistory, history_for, load_history_config
from erp.dcf.db_inputs import DBInput, resolve_db_inputs, unverified_fact_ids, unverified_note
from erp.dcf.checks import (
    CheckResult,
    check_required_inputs,
    check_terminal_growth_below_risk_free,
    check_terminal_growth_below_wacc,
    check_tv_share,
)
from erp.dcf.engine import (
    Bridge,
    DCFError,
    FCFFYear,
    SensitivityGrid,
    ValuationResult,
    WACCResult,
    build_fcff,
    compute_wacc,
    sensitivity_grid,
    value_firm,
)
from erp.units import MONEY_UNITS, SHARE_UNITS
from erp.version import code_version

DEFAULT_ASSUMPTIONS = REPO / "data" / "manual" / "dcf_inputs.yaml"   # written by the author (P0.3)
DCF_CONFIG = REPO / "config" / "dcf.yaml"

DISCLAIMER = ("Illustrative calculation: the value these assumptions imply, not a prediction. "
              "Not investment advice.")


class DCFCheckError(DCFError):
    """A blocking sanity check failed; nothing was stored."""


class DCFResult(BaseModel):
    run_id: int                  # row in dcf_run
    ticker: str
    scenario: str
    description: str
    label: str
    valuation_date: str
    units: dict[str, str]        # money / shares units of the inputs
    per_share_unit: str          # always INR_PER_SHARE
    assumptions: dict[str, Assumption]   # database inputs carry their resolved value
    db_inputs: list[DBInput]             # what was read from the facts database (fact ids, pages)
    unverified_fact_ids: list[str]       # database inputs no human has checked yet
    notes: list[str]                     # e.g. "This DCF uses 2 facts not yet verified by a human"
    fcff_build: list[FCFFYear]
    wacc_build: WACCResult
    valuation: ValuationResult
    sensitivity: SensitivityGrid
    checks: list[CheckResult]
    all_checks_passed: bool              # the engine's checks only (history checks are in `history`)
    history: DCFHistory                  # D4: operating assumptions vs FY23-FY26 record, non-blocking checks
    code_version: str
    run_at: str
    disclaimer: str


def _refuse_if_failed(check: CheckResult) -> CheckResult:
    if check.blocking and check.status == "fail":
        raise DCFCheckError(f"refusing to run: check {check.check_id!r} failed: {check.detail}")
    return check


def _stored(i: DBInput) -> dict:
    """A database input as kept in dcf_run.assumptions_json: enough to cite each fact and its page."""
    return {
        "assumption": i.assumption, "period": i.period, "basis": i.basis, "unit": i.unit,
        "facts": [{"fact_id": f.fact_id, "metric_id": f.metric_id, "value": f.value, "unit": f.unit,
                   "value_in_input_unit": x, "source_id": f.source_id, "source_title": f.source_title,
                   "source_page": f.source_page, "source_page_label": f.source_page_label, "verified": f.verified}
                  for f, x in zip(i.facts, i.fact_values)],
        "facts_total": i.facts_total, "adjustments": [a.model_dump() for a in i.adjustments],
        "treat_as": i.treat_as, "factor": i.factor, "value": i.value,
    }


def run_dcf(conn: sqlite3.Connection, ticker: str, scenario: str, *, assumptions_path=None,
            dcf_config: Path = DCF_CONFIG) -> DCFResult:
    s = load_scenario(assumptions_path or DEFAULT_ASSUMPTIONS, scenario)
    if s.ticker != ticker:
        raise AssumptionError(f"assumptions file is for {s.ticker!r} but run_dcf was asked for {ticker!r}")
    row = conn.execute("SELECT company_id FROM company WHERE ticker_nse = ?", (ticker,)).fetchone()
    if row is None:
        raise DCFError(f"unknown company ticker {ticker!r}")
    company_id = row[0]
    with open(dcf_config) as f:
        cfg = yaml.safe_load(f)

    checks = [_refuse_if_failed(check_required_inputs(s))]
    assumptions, db_inputs = resolve_db_inputs(conn, ticker, s)   # refuses if a fact is missing
    unverified = unverified_fact_ids(db_inputs)
    notes = unverified_note(unverified)

    def v(name):
        return assumptions[name].value

    w = compute_wacc(v("risk_free_rate"), v("beta"), v("equity_risk_premium"), v("debt_weight"),
                     v("cost_of_debt_pre_tax"), v("debt_tax_rate"))
    g = v("terminal_growth")
    checks.append(_refuse_if_failed(check_terminal_growth_below_wacc(g, w.wacc)))
    checks.append(check_terminal_growth_below_risk_free(g, v("risk_free_rate")))

    years = build_fcff(v("base_year_revenue"), v("revenue_growth"), v("ebit_margin"), v("tax_rate"),
                       v("da_pct_revenue"), v("capex_pct_revenue"), v("nwc_pct_incremental_revenue"),
                       horizon=v("forecast_horizon_years"))
    fcff = [y.fcff for y in years]
    bridge = Bridge(cash_and_investments=v("cash_and_investments"), debt=v("debt"),
                    lease_liabilities=v("lease_liabilities"), minority_interest=v("minority_interest"),
                    diluted_shares=v("diluted_shares"))
    scale = {"money_per_unit": MONEY_UNITS[s.units["money"]], "shares_per_unit": SHARE_UNITS[s.units["shares"]]}
    valuation = value_firm(fcff, w.wacc, g, bridge, **scale)

    band = cfg["checks"]["tv_share_of_ev_warning_band"]
    checks.append(check_tv_share(valuation.tv_share_of_ev, band["min"], band["max"]))

    sens = cfg["sensitivity"]
    # Rounded so grid labels read 0.11, not 0.10999999999999999.
    grid = sensitivity_grid(fcff, [round(w.wacc + o, 10) for o in sens["wacc_offsets"]],
                            [round(g + o, 10) for o in sens["terminal_growth_offsets"]], bridge, **scale)

    history = history_for(conn, ticker, s, load_history_config(dcf_config))   # never raises for missing data

    version = code_version()
    run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    assumptions_json = json.dumps({
        "file": s.file, "sha256": s.sha256, "scenario": scenario, "label": s.label, "units": s.units,
        "resolved": {k: a.model_dump(exclude_defaults=True) for k, a in assumptions.items()},   # typed: as before D2
        "facts_basis": s.facts_basis,
        "db_inputs": [_stored(i) for i in db_inputs],
        "unverified_fact_ids": unverified,
        "yaml_text": s.yaml_text,
    })
    outputs_json = json.dumps({
        "per_share_unit": "INR_PER_SHARE",
        "fcff_build": [y.model_dump() for y in years],
        "wacc_build": w.model_dump(),
        "valuation": valuation.model_dump(),
        "sensitivity": grid.model_dump(),
        "history": history.model_dump(mode="json"),
    })
    checks_json = json.dumps([c.model_dump() for c in checks])
    valuation_date = v("valuation_date")
    with conn:
        cur = conn.execute(
            "INSERT INTO dcf_run (company_id, scenario_name, valuation_date, assumptions_json, outputs_json,"
            " checks_json, code_version, run_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (company_id, scenario, valuation_date, assumptions_json, outputs_json, checks_json, version, run_at))

    return DCFResult(
        run_id=cur.lastrowid, ticker=ticker, scenario=scenario, description=s.description, label=s.label,
        valuation_date=valuation_date, units=s.units, per_share_unit="INR_PER_SHARE",
        assumptions=assumptions, db_inputs=db_inputs, unverified_fact_ids=unverified, notes=notes, fcff_build=years, wacc_build=w, valuation=valuation, sensitivity=grid,
        checks=checks, all_checks_passed=all(c.status == "pass" for c in checks), history=history, code_version=version,
        run_at=run_at, disclaimer=DISCLAIMER,
    )
