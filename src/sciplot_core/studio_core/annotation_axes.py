"""Shared ordinary-curve scope and exact displayed annotation units."""

from __future__ import annotations

import copy
import math
import re
from typing import Any

from sciplot_core.studio_core.annotation_schema import AnnotationOperationError


def require_scope(spec: dict[str, Any]) -> None:
    if spec.get("template") not in {"curve", "point_line", "stacked_curve"} or any(
        spec.get(key) is not None for key in ("scalar_field", "categorical", "performance_comparison")
    ):
        raise AnnotationOperationError("unsupported_annotation_scope", "Annotations currently require ordinary Cartesian curves.")


def axis_unit(spec: dict[str, Any], axis: str) -> str:
    label = str(spec["axes"][axis]["label"])
    match = re.search(r"\(([^()]*)\)\s*$", label)
    return match[1] if match else ""


def change_display_range(spec: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    """Change only an explicit linear axis viewport; keep every series value."""
    from sciplot_core.studio_core.axis_data_visibility import axis_data_visibility_payload

    require_scope(spec)
    preserve_ticks = operation.get("op") == "set_axis_limits"
    required = {"op", "axis", "unit", "expected_min", "expected_max",
                "min", "max", "allow_clipping"} | (set() if preserve_ticks else {"ticks"})
    if set(operation) != required or operation["axis"] not in ("x", "y"):
        raise AnnotationOperationError("invalid_axis_range", "Use the advertised X/Y display-range fields.")
    name = operation["axis"]
    axis = spec["axes"][name]
    if axis.get("scale") != "linear" or axis.get("mode", "numeric") != "numeric":
        raise AnnotationOperationError("unsupported_axis_range", "Display-range edits require a linear numeric axis.")
    if operation["unit"] != axis_unit(spec, name):
        raise AnnotationOperationError("unit_mismatch", "Use the exact inspected axis unit.")
    numbers = [operation[k] for k in ("expected_min", "expected_max", "min", "max")]
    ticks = axis.get("ticks", []) if preserve_ticks else operation["ticks"]
    if (not isinstance(ticks, list) or (not preserve_ticks and not 2 <= len(ticks) <= 32)
            or any(isinstance(v, bool) or not isinstance(v, int | float)
                   or not math.isfinite(v) for v in [*numbers, *ticks])
            or not isinstance(operation["allow_clipping"], bool)):
        raise AnnotationOperationError("invalid_axis_range", "Bounds and ticks must be finite numbers; clipping consent must be boolean.")
    if preserve_ticks and operation["allow_clipping"]:
        raise AnnotationOperationError("axis_clipping_not_authorized", "Semantic axis limits cannot authorize hiding coordinates.")
    if (axis["min"], axis["max"]) != tuple(numbers[:2]):
        raise AnnotationOperationError("stale_axis_range", "Inspect the current saved axis bounds before changing its display range.")
    minimum, maximum = map(float, numbers[2:])
    if minimum == maximum or (minimum < maximum) != (axis["min"] < axis["max"]):
        raise AnnotationOperationError("invalid_axis_range", "Keep the existing axis direction and use distinct bounds.")
    low, high = sorted((minimum, maximum))
    if not preserve_ticks and (any(a >= b for a, b in zip(ticks, ticks[1:], strict=False))
                              or ticks[0] != low or ticks[-1] != high):
        raise AnnotationOperationError("invalid_axis_range", "Provide increasing ticks including both display endpoints.")
    options = spec.get("render_options", {})
    if any(options.get(key) for key in (f"{name}_axis_breaks", f"extra_{name}_axis")):
        raise AnnotationOperationError("unsupported_axis_range", "Broken or supplementary axes require a separate range contract.")
    clipped = sum(type(value) in {int, float} and math.isfinite(value) and not low <= value <= high
                  for series in spec.get("series", []) for value in series.get(f"{name}_values", []))
    if clipped and not operation["allow_clipping"]:
        raise AnnotationOperationError("axis_clipping_not_authorized", "The requested display window hides coordinates; explicit allow_clipping is required.")
    before = {key: axis[key] for key in ("min", "max")}
    previous_window = axis.get("display_window", {})
    source_axis = copy.deepcopy(previous_window.get("source_axis", axis))
    window = {"min": minimum, "max": maximum, "allow_clipping": operation["allow_clipping"],
              "source_axis": source_axis}
    axis.update(min=minimum, max=maximum, display_window=window)
    spec["render_options"] = {**options, f"{name}_min": low, f"{name}_max": high}
    if not preserve_ticks:
        axis["ticks"] = [float(v) for v in ticks]
        spec["render_options"][f"{name}_ticks"] = [float(v) for v in ticks]
    spec["axis_data_visibility"] = axis_data_visibility_payload(
        series_specs=spec.get("series"), axes=spec["axes"], render_options=spec["render_options"])
    return {"op": operation["op"], "axis": name, "before": before,
            "after": {"min": minimum, "max": maximum, "ticks": ticks},
            "allow_clipping": operation["allow_clipping"],
            "outside_display_coordinate_count": clipped,
            "series_values_unchanged": True}
