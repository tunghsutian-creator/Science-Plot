"""Validated unit conversions for rheology source quantities."""

from __future__ import annotations

import math
from sciplot_core.materials_rules.unit_formatting import format_unit_label


def _unit_conversion(source_unit: str, target_unit: str) -> tuple[str, float, str]:
    source = format_unit_label(source_unit.strip()).strip()
    target = format_unit_label(target_unit).strip()
    if source == target:
        return target, 1.0, "identity"
    conversions = {
        ("Hz", format_unit_label("rad/s")): (2 * math.pi, "Hz_to_rad_s"),
        ("1", "%"): (100.0, "fraction_to_percent"),
        ("fraction", "%"): (100.0, "fraction_to_percent"),
        ("%", "1"): (0.01, "percent_to_fraction"),
        ("fraction", "1"): (1.0, "fraction_identity"),
        ("kPa", "Pa"): (1000.0, "kPa_to_Pa"),
        ("MPa", "Pa"): (1_000_000.0, "MPa_to_Pa"),
        ("Pa", "kPa"): (0.001, "Pa_to_kPa"),
        ("Pa", "MPa"): (0.000001, "Pa_to_MPa"),
        ("Pa·s", "mPa·s"): (1000.0, "Pa_s_to_mPa_s"),
        ("cP", "mPa·s"): (1.0, "cP_to_mPa_s"),
    }
    conversion = conversions.get((source, target))
    if conversion is None:
        return source or target, 1.0, "source_unit_preserved"
    factor, method = conversion
    return target, factor, method
