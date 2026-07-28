"""Convert numeric values between compatible canonical units."""

from __future__ import annotations


from sciplot_core.materials_rules.unit_data import (
    _UNIT_RULES,
)


def convert_value(value: float, source_unit: str, target_unit: str) -> float:
    if source_unit == target_unit:
        return float(value)
    rule = _UNIT_RULES.get((source_unit, target_unit))
    if rule is None:
        raise ValueError(
            f"No SciPlot material unit conversion from `{source_unit}` to `{target_unit}`."
        )
    return float(value) * rule.factor + rule.offset
