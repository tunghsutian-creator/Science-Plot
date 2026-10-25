"""One typed scientific derivation, with original units and row identity retained."""
from copy import deepcopy
from typing import Any

from sciplot_core.plot_document.errors import fail
from .rheology_metrics import derive_complex_viscosity, validate_complex_viscosity_units

from .time import canonical_unit_token


def run_rheology_builtin(node: dict[str, Any], source: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    result = deepcopy(source)
    parameters = node["parameters"]
    selected = {role: parameters[role + "_column"] for role in ("frequency", "storage", "loss")}
    if len(set(selected.values())) != 3 or any(name not in source["columns"] for name in selected.values()):
        fail("transform_rheology_inputs", "Bind three distinct original frequency and modulus columns.", "/parameters", "distinct_existing_columns")
    output = parameters["output_column"]
    if output in source["columns"]:
        fail("transform_column_collision", "A derived viscosity column cannot overwrite an original column.", "/parameters/output_column", "new_column")
    columns = {role: source["columns"][name] for role, name in selected.items()}
    try:
        validate_complex_viscosity_units(
            frequency_unit=canonical_unit_token(columns["frequency"]["unit"]),
            storage_unit=canonical_unit_token(columns["storage"]["unit"]),
            loss_unit=canonical_unit_token(columns["loss"]["unit"]), output_unit=parameters["output_unit"])
    except ValueError as exc:
        fail("transform_rheology_invalid", str(exc), "/parameters", "supported_original_units")
    values: list[float | None] = []
    for index, inputs in enumerate(zip(*(columns[role]["values"] for role in ("frequency", "storage", "loss")), strict=True)):
        if any(value is None for value in inputs):
            values.append(None)
            continue
        try:
            value = derive_complex_viscosity(*inputs,
                frequency_unit=canonical_unit_token(columns["frequency"]["unit"]),
                storage_unit=canonical_unit_token(columns["storage"]["unit"]),
                loss_unit=canonical_unit_token(columns["loss"]["unit"]), output_unit=parameters["output_unit"])
        except ValueError as exc:
            fail("transform_rheology_invalid", str(exc), "/parameters", "finite_positive_frequency_and_supported_units", row_index=index)
        values.append(value)
    result["columns"][output] = {"label": "Complex Viscosity Magnitude", "unit": parameters["output_unit"], "values": values}
    result["id"] = node["output"]
    return result, {"method": "derived_from_storage_and_loss_modulus", "formula": "hypot(storage_modulus, loss_modulus) / angular_frequency",
                    "input_columns": selected, "input_units": {role: column["unit"] for role, column in columns.items()},
                    "output_unit": parameters["output_unit"], "missing_values": "preserved", "row_order": "preserved",
                    "authority": "semantic_sources.rheology_frequency_metrics.derive_complex_viscosity"}
