"""Explicit table operations preserve acquisition order and every missing value."""

from copy import deepcopy
import math
from typing import Any

from sciplot_core.plot_document.errors import fail


def run_builtin(node: dict[str, Any], source: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    result, details = deepcopy(source), {}
    columns, params = result["columns"], node["parameters"]
    selected = params["columns"]
    if any(name not in columns for name in selected):
        fail("transform_column_missing", "A transform references an absent column.", "/parameters/columns",
             "existing_column", allowed=sorted(columns))
    if node["kind"] == "select":
        result["columns"] = {name: columns[name] for name in selected}
    elif node["kind"] == "rename":
        renamed = {}
        for name, column in columns.items():
            identity = selected.get(name, {"id": name, "label": column["label"]})
            if identity["id"] in renamed:
                fail("transform_column_collision", "Renaming cannot overwrite another column.", "/parameters/columns", "unique_ids")
            column["label"] = identity["label"]
            renamed[identity["id"]] = column
        result["columns"] = renamed
    else:
        factors: dict[str, float] = {}
        divisors: dict[str, float] = {}
        for name in selected:
            column = columns[name]
            if node["kind"] == "scale":
                factor = params["factor"]
                values = [None if value is None else value * factor for value in column["values"]]
                factors[name] = factor
            else:
                finite = [value for value in column["values"] if value is not None]
                if not finite:
                    fail("transform_normalization_empty", "Normalization requires an observed value.", "/parameters/columns", "observed_value")
                divisor = (params["constant"] if params["method"] == "constant" else
                           finite[0] if params["method"] == "first" else max(abs(value) for value in finite))
                if divisor == 0:
                    fail("transform_zero_divisor", "Normalization cannot divide by zero.", "/parameters", "nonzero_divisor")
                values = [None if value is None else value / divisor for value in column["values"]]
                divisors[name] = divisor
                column["unit"] = params["output_unit"]
            if any(value is not None and not math.isfinite(value) for value in values):
                fail("transform_nonfinite_result", "This transform overflows the finite numeric domain.", "/parameters", "finite_result")
            column["values"] = values
        details = {"multipliers": factors, "divisors": divisors, "missing_values": "preserved", "row_order": "preserved"}
    result["id"] = node["output"]
    return result, details
