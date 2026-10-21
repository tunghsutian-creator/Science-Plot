"""Explicit ordinary axis transforms using the existing central domain policy."""
import math
from typing import Any, NoReturn

from sciplot_core.plot_grammar.domain_values import numeric_axis
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
