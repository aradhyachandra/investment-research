"""Unit conversion table: as-reported unit -> canonical unit.

Only the conversions M1 needs. M2 extends this module (unit handling for tools).
Unit math is universal, not company-specific, so it lives in code.
"""

# (reported_unit, canonical_unit) -> multiply reported_value by this to get value.
# 1 crore = 10 million, so 1 INR million = 0.1 INR crore.
CONVERSIONS = {
    ("INR_CRORE", "INR_CRORE"): 1,
    ("INR_MILLION", "INR_CRORE"): 0.1,
    ("INR_PER_SHARE", "INR_PER_SHARE"): 1,
}


class UnitError(ValueError):
    pass


def conversion_factor(reported_unit: str, canonical_unit: str) -> float:
    try:
        return CONVERSIONS[(reported_unit, canonical_unit)]
    except KeyError:
        raise UnitError(
            f"no conversion from reported unit {reported_unit!r} to canonical unit {canonical_unit!r}"
        ) from None
