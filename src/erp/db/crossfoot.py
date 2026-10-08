"""Cross-foot identities at load time (PROJECT_PLAN.md Section 4.4; added in D1).

Which identities to check lives in the company config (`cross_foot_checks`), e.g.
profit before tax = profit before exceptional items and tax - each exceptional item.

Checked on the facts in the CSV being loaded, per (period, basis, source document, accounting
standard): when the total and every part are present, total must equal sum(sign x part) within
the printing rounding of all the figures involved (each figure's half-step, added together).
If any figure is missing, the identity is skipped for that group; that is not an error.
"""
from collections import defaultdict

from erp.config import LoadContext
from erp.db.validate import Fact


def check_cross_foots(facts: list[Fact], ctx: LoadContext) -> list[str]:
    groups = defaultdict(dict)
    for f in facts:
        groups[(f.period_label, f.basis, f.source_doc, f.accounting_standard)][f.metric_id] = f

    errors = []
    for (period, basis, source_doc, _), by_metric in groups.items():
        for check in ctx.cross_foot_checks or []:
            names = [check["total"], *(p["metric"] for p in check["parts"])]
            if not all(n in by_metric for n in names):
                continue
            total = by_metric[check["total"]]
            parts = [(p["sign"], by_metric[p["metric"]]) for p in check["parts"]]
            expected = sum(sign * f.value for sign, f in parts)
            slack = total.tolerance + sum(f.tolerance for _, f in parts)
            if abs(total.value - expected) > slack + 1e-9 * max(abs(total.value), 1.0):
                terms = " ".join(f"{'+' if sign > 0 else '-'} {f.metric_id} {f.value:,.10g} (row {f.row_number})"
                                 for sign, f in parts)
                errors.append(
                    f"cross-foot {check['name']!r} fails for {period} {basis} ({source_doc}): "
                    f"{check['total']} {total.value:,.10g} (row {total.row_number}) but {terms.lstrip('+ ')} "
                    f"= {expected:,.10g}; difference {total.value - expected:,.10g} {total.unit}, "
                    f"allowed rounding {slack:g}")
    return errors
