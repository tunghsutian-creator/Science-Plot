"""Explicit ordinary axis transforms using the existing central domain policy."""
import math
from copy import deepcopy
from typing import Any, NoReturn

from sciplot_core.plot_grammar.domain_values import nonnegative_minimum, numeric_axis
from sciplot_core.task_errors import TaskControlError


def _error(code: str, message: str, **facts: Any) -> NoReturn:
    error = TaskControlError(code, message)
    error.issues = [{"path": "/intent", "constraint": code, **facts}]
    error.repair = {"action": "revise_intent", "message": "Preserve all original observations. Correct the requested axis or exact column binding in this same draft; no nonpositive or missing point is removed to satisfy a log axis."}
    raise error


def ordinary_axis(role: str, coordinate: dict[str, Any], unit: str, values: list[float]) -> tuple[list[float], list[float], str, str]:
    label_unit = "°C" if unit == "C" and coordinate["quantity"] == "temperature" else unit
    label = coordinate.get("label") or coordinate["quantity"].replace("_", " ").title() + (f" ({label_unit})" if unit else "")
    transform = coordinate.get("scale", "linear")
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        _error("semantic_empty_coordinate", "The selected coordinate has no finite observations.")
    if transform == "log" and any(not math.isfinite(value) or value <= 0 for value in values):
        _error("semantic_log_domain", "Logarithmic axes require every original mapped observation to be positive and finite; no point is dropped or shifted.", role=role)
    try:
        domain, ticks = numeric_axis(finite, quantity=coordinate["quantity"], transform=transform,
            dimension="x" if role == "x" else "y", minimum=coordinate.get("minimum"), maximum=coordinate.get("maximum"))
    except (ValueError, OverflowError) as exc:
        _error("semantic_log_domain" if transform == "log" else "semantic_invalid_domain", str(exc), role=role)
    return domain, ticks, label, transform


def axis_spec(role: str, coordinate: dict[str, Any], side: str, unit: str, values: list[float],
              raw_plan: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    effective = coordinate
    automatic_zero = raw_plan.get("rule_id") == "xrd_pattern" and "minimum" not in coordinate
    if automatic_zero:
        minimum = nonnegative_minimum(values)
        if minimum is not None:
            effective = {**coordinate, "minimum": minimum}
    domain, ticks, label, scale_transform = ordinary_axis(role, effective, unit, values)
    scale = {"id": "scale:" + role, "dimension": "x" if role == "x" else "y", "transform": scale_transform,
                   "domain": domain, "unit": unit, "quantity": coordinate["quantity"], "direction": coordinate.get("direction", "ascending"),
                   "domain_rule": {name: ({"mode": "fixed", "value": coordinate[name]} if name in coordinate
                                         else {"mode": "auto_zero_if_nonnegative" if name == "minimum" and automatic_zero else "auto"})
                                   for name in ("minimum", "maximum")} | ({"empty_log_ticks": coordinate["empty_log_ticks"]}
                                                                              if "empty_log_ticks" in coordinate else {}),
                   **({"quantity_members": deepcopy(coordinate["quantity_members"])} if "quantity_members" in coordinate else {})}
    label = raw_plan.get("axis_labels", {}).get(role, label)
    qualitative_y = role == "y" and raw_plan.get("show_y_ticks") is False
    axis = {"id": "axis:" + role, "scale_id": "scale:" + role, "side": side,
                 "label": label, "visible": True, "label_visible": True,
                 "ticks": [] if qualitative_y else ticks, "ticks_mode": "fixed" if qualitative_y else "automatic",
                 "style": {"minor_ticks_visible": False} if qualitative_y else {}}
    return scale, axis
