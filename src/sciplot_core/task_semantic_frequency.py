"""Registered frequency policy; physical source observation never selects it."""
from typing import Any


def validate_frequency_intent(intent: dict[str, Any]) -> None:
    """Preserve the selected scientific adapter's existing input contract."""
    if intent["x"]["quantity"] != "angular_frequency" or intent.get("secondary_y") or intent.get("stages"):
        from sciplot_core.task_errors import TaskControlError

        error = TaskControlError("semantic_frequency_intent_unsupported", "The selected registered frequency experiment uses angular_frequency and one response, without cumulative time stages or a secondary axis.")
        error.repair = {"action": "revise_intent", "message": "Correct this same draft's explicit experiment/coordinates; source layout does not select or replace an experiment."}
        raise error


def frequency_condition(block: dict[str, Any]) -> dict[str, Any]:
    """Project registered condition labels from literal metadata, never values."""
    if not block.get("result"):
        return {}
    from copy import deepcopy
    from sciplot_core.semantic_sources.rheology_sweep_sources import frequency_result_condition

    sample = block.get("sample")
    condition = frequency_result_condition(block.get("result", ""))
    if not sample or condition is None:
        return {}
    nominal_text, nominal = condition
    interval = {**deepcopy(block.get("source_interval") or {}), "sample": sample, "result": block["result"],
                "nominal_temperature": nominal, "nominal_temperature_unit": "°C", "basis": "literal original Result metadata; measured temperatures retained"}
    return {"label": f"{sample} · {nominal_text} °C", "source_interval": interval}


def frequency_coordinate(role: str, coordinate: dict[str, Any], unit: str) -> dict[str, Any]:
    """Resolve registered frequency defaults once, respecting explicit axes."""
    from sciplot_core.materials_rules.unit_formatting import format_unit_label
    from sciplot_core.policy.axis_defaults import RHEOLOGY_FREQUENCY_X_LABEL
    from sciplot_core.source_tables.text_normalization import normalize_label

    quantity = coordinate["quantity"]
    if role == "x" and quantity == "angular_frequency":
        label = RHEOLOGY_FREQUENCY_X_LABEL if unit == "rad/s" else "f (Hz)" if unit == "Hz" else f"Angular Frequency ({format_unit_label(unit)})"
    else:
        label = normalize_label(quantity.replace("_", " "))
        if unit and unit != "1":
            label += " (" + format_unit_label(unit) + ")"
    return {**coordinate, "scale": coordinate.get("scale", "linear" if quantity in {"loss_factor", "temperature"} else "log"),
            "direction": coordinate.get("direction", "ascending"), "label": label}


def frequency_derivation(columns: list[dict[str, Any]], coordinate: dict[str, Any]) -> dict[str, Any] | None:
    """Expose the existing typed derivation only under registered authorization."""
    if coordinate["quantity"] != "complex_viscosity":
        return None
    inputs = {quantity: [column for column in columns if column["quantity"] == quantity]
              for quantity in ("angular_frequency", "storage_modulus", "loss_modulus")}
    if any(len(values) != 1 for values in inputs.values()):
        return None
    return {"quantity": "complex_viscosity", "unit": "Pa s", "method": "derived_from_storage_and_loss_modulus",
            "formula": "hypot(storage_modulus, loss_modulus) / angular_frequency",
            "inputs": {quantity: values[0] for quantity, values in inputs.items()}}


def frequency_axis(role: str, coordinate: dict[str, Any], unit: str, values: list[float]) -> tuple[list[float], list[float], str, str]:
    """Retain the public policy helper through the common axis implementation."""
    from sciplot_core.task_errors import TaskControlError
    from sciplot_core.task_semantic_axes import ordinary_axis

    resolved = frequency_coordinate(role, coordinate, unit)
    try:
        return ordinary_axis(role, resolved, unit, values)
    except TaskControlError as exc:
        if exc.reason_code == "semantic_log_domain":
            exc.reason_code = "semantic_frequency_log_domain"
        raise
