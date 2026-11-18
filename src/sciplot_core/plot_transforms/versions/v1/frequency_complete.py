"""Exact supported rheology acquisition row selection and metric completion."""
from copy import deepcopy
from math import hypot, isfinite
from typing import Any

from sciplot_core.plot_document.errors import fail

from .datasets import dataset_hash
from .hashing import canonical_json_sha256
from .lineage import row_origins
from .rheology_metrics import _viscosity_from_modulus
from .runtime import record_result


def complete(node: dict[str, Any], source: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    result = deepcopy(source)
    columns = result["columns"]
    derivations = node["parameters"]["derivations"]
    x = columns.get("x")
    measured = [column for name, column in columns.items() if name != "x"]
    if x is None or x["unit"] != "rad/s" or not measured:
        fail("transform_frequency_metric_invalid", "Frequency needs rad/s and actual measurements.", "/inputs", "frequency_coordinates")
    origins = row_origins(source)
    retained = [index for index, value in enumerate(x["values"])
                if value is not None and any(column["values"][index] is not None for column in measured)]
    if not retained:
        fail("transform_frequency_metric_invalid", "No row has both frequency and a measurement.", "/inputs", "paired_observations")
    for column in columns.values():
        column["values"] = [column["values"][index] for index in retained]

    def require_input(name: str) -> list[float | None]:
        column = columns.get(name)
        if column is None or column["unit"] != "Pa":
            fail("transform_frequency_metric_invalid", "The selected modulus input requires Pa.", "/inputs", "modulus_units", column=name)
        return column["values"]

    def derive(name: str, unit: str, values: list[float | None]) -> None:
        if name in columns or any(value is not None and not isfinite(value) for value in values):
            fail("transform_frequency_metric_invalid", "Do not overwrite a measured column or publish nonfinite values.",
                 "/parameters/derivations", "valid_new_metric", column=name)
        columns[name] = {"label": name, "unit": unit, "values": values}

    if "complex_modulus" in derivations:
        real, loss = require_input("storage_modulus"), require_input("loss_modulus")
        derive("complex_modulus", "Pa", [hypot(a, b) if a is not None and b is not None else None
                                         for a, b in zip(real, loss, strict=True)])
    if "complex_viscosity" in derivations:
        modulus = require_input("complex_modulus")
        try:
            if any(value is None for value in modulus):
                raise ValueError("Complex viscosity needs measured or derived modulus at every retained row.")
            eta = [_viscosity_from_modulus(w, m, output_unit="mPa·s")
                   for w, m in zip(x["values"], modulus, strict=True) if m is not None]
        except ValueError as exc:
            fail("transform_frequency_metric_invalid", str(exc), "/inputs", "viscosity_domain")
        derive("complex_viscosity", "mPa·s", eta)
    result["id"] = node["output"]
    return result, {"derivations": derivations, "row_order": "original",
                    "row_origins": [origins[index] for index in retained]}


def execute(node: dict[str, Any], sources: list[dict[str, Any]], operation: Any, *,
            multiple_inputs: bool) -> tuple[dict[str, Any], str]:
    assert not multiple_inputs
    hashes = [dataset_hash(sources[0])]
    key = canonical_json_sha256({"node": node, "inputs": hashes}, allow_nan=False)
    result, details = operation(node, sources[0])
    return record_result(node, result, details, hashes, key), key
