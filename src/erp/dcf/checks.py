"""DCF sanity checks (PROJECT_PLAN.md 5.3), stored with every run in dcf_run.checks_json.

status: 'pass', 'fail' or 'warn'. A failed BLOCKING check makes run_dcf refuse (nothing is
stored). A failed non-blocking check or a warning is stored with the run so it is visible.

Checks that need historical data from SQLite (margin/growth jumps vs history, all facts from
the same basis and period) are TODO: see NOTES.md.
"""
from typing import Literal

from pydantic import BaseModel

from erp.dcf.assumptions import Scenario
from erp.dcf.engine import growth_below_wacc


class CheckResult(BaseModel):
    check_id: str
    description: str
    status: Literal["pass", "fail", "warn"]
    blocking: bool
    detail: str


def check_required_inputs(scenario: Scenario) -> CheckResult:
    missing = scenario.missing()
    return CheckResult(
        check_id="required_inputs_present", description="All required assumptions are present",
        status="fail" if missing else "pass", blocking=True,
        detail=f"missing: {', '.join(missing)}" if missing else "all present",
    )


def check_terminal_growth_below_wacc(terminal_growth: float, wacc: float) -> CheckResult:
    ok = growth_below_wacc(terminal_growth, wacc)
    return CheckResult(
        check_id="terminal_growth_below_wacc", description="Terminal growth is below WACC",
        status="pass" if ok else "fail", blocking=True,
        detail=f"terminal growth {terminal_growth} {'<' if ok else 'is not below'} WACC {wacc}",
    )


def check_terminal_growth_below_risk_free(terminal_growth: float, risk_free_rate: float) -> CheckResult:
    # Not blocking: the maths still works, but the plan says terminal growth must stay below the
    # risk-free rate, so a breach is stored as a visible failure. TO VERIFY with the finance
    # partner whether this should refuse instead.
    ok = terminal_growth < risk_free_rate
    return CheckResult(
        check_id="terminal_growth_below_risk_free", description="Terminal growth is below the risk-free rate",
        status="pass" if ok else "fail", blocking=False,
        detail=f"terminal growth {terminal_growth} {'<' if ok else 'is not below'} risk-free rate {risk_free_rate}",
    )


def check_tv_share(tv_share: float | None, band_min: float, band_max: float) -> CheckResult:
    desc = "Terminal value share of enterprise value is inside the warning band"
    if tv_share is None:
        return CheckResult(check_id="tv_share_of_ev_in_band", description=desc, status="fail", blocking=False,
                           detail="enterprise value is not positive, so the share is undefined")
    ok = band_min <= tv_share <= band_max
    return CheckResult(
        check_id="tv_share_of_ev_in_band", description=desc, status="pass" if ok else "warn", blocking=False,
        detail=f"TV share {tv_share:.4f}; band {band_min}-{band_max}",
    )
