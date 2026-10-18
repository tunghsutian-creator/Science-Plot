"""Declared conversions reuse the registered scientific unit conversion owner."""
from copy import deepcopy
import math
from typing import Any

from sciplot_core.materials_rules.unit_conversion import convert_value
from sciplot_core.plot_document.errors import fail

TIME_UNITS = frozenset({"ms", "s", "min", "h"})


def canonical_unit_token(unit: str) -> str:
    """Remove unit delimiters, never infer missing units or scientific quantity."""
    token = unit.strip()
    if len(token) >= 2 and (token[0], token[-1]) in {("[", "]"), ("(", ")")}:
        token = token[1:-1].strip()
    return "C" if token == "°C" else token


def run_unit_builtin(node: dict[str, Any], source: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    result = deepcopy(source)
    parameters = node["parameters"]
    selected = parameters["columns"] if node["kind"] == "convert_unit" else [parameters["time_column"]]
    for name in selected:
        if name not in result["columns"]:
            fail("transform_column_missing", "A transform references an absent column.", "/parameters", "existing_column", column_id=name)
    details: dict[str, Any] = {"missing_values": "preserved", "row_order": "preserved"}
    if node["kind"] == "convert_unit":
        declared, target = parameters["from_unit"], parameters["to_unit"]
        original, canonical = canonical_unit_token(declared), canonical_unit_token(target)
        viscosity_aliases = {"Pa·s": "Pa.s", "Pa s": "Pa.s", "mPa·s": "mPa.s", "mPa s": "mPa.s"}
        original, canonical = viscosity_aliases.get(original, original), viscosity_aliases.get(canonical, canonical)
        try:
            offset = convert_value(0, original, canonical)
            factor = convert_value(1, original, canonical) - offset
        except ValueError as exc:
            fail("transform_unit_incompatible", str(exc), "/parameters/to_unit", "registered_unit_conversion", from_unit=declared, to_unit=target)
        for name in selected:
            column = result["columns"][name]
            if column["unit"] != declared:
                fail("transform_unit_conflict", "The declared original unit differs from the source-bound column.", "/parameters/from_unit", "exact_source_unit", column_id=name, expected=column["unit"], actual=declared)
            column["values"] = [None if value is None else convert_value(value, original, canonical) for value in column["values"]]
            column["unit"] = target
        details.update(from_unit=declared, to_unit=target, canonical_from_unit=original, canonical_to_unit=canonical, factor=factor, offset=offset, authority="materials_rules.unit_conversion")
    else:
        name = parameters["time_column"]
        column = result["columns"][name]
        if parameters["unit"] != column["unit"] or canonical_unit_token(column["unit"]) not in TIME_UNITS:
            fail("transform_time_unit_conflict", "Time offsets require the exact declared source time unit.", "/parameters/unit", "exact_time_unit", expected=column["unit"], actual=parameters["unit"])
        column["values"] = [None if value is None else value + parameters["offset"] for value in column["values"]]
        details.update(time_column=name, offset=parameters["offset"], unit=parameters["unit"])
    if any(value is not None and not math.isfinite(value) for name in selected for value in result["columns"][name]["values"]):
        fail("transform_nonfinite_result", "This transform overflows the finite numeric domain.", "/parameters", "finite_result")
    result["id"] = node["output"]
    return result, details
