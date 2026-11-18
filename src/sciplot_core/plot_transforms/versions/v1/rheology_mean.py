"""Version 1 exact-x rheology replicate averaging and its execution record."""
from copy import deepcopy
import math
from typing import Any

from sciplot_core.plot_document.errors import fail

from .datasets import dataset_hash
from .hashing import canonical_json_sha256
from .lineage import merge_provenance, row_origins
from .runtime import record_result


def mean_at_exact_x(node: dict[str, Any], sources: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    x_name = node["parameters"]["x_column"]
    columns = deepcopy(sources[0]["columns"])
    metrics = [name for name in columns if name != x_name]
    if x_name not in columns or not metrics:
        fail("transform_sweep_columns_invalid", "A replicate group needs one measured x and at least one metric.",
             "/parameters/x_column", "measured_x_and_metrics")
    rows: dict[float, dict[str, list[float]]] = {}
    origins: dict[float, list[dict[str, Any]]] = {}
    for source in sources:
        observed = source["columns"]
        if set(observed) != set(columns) or any(observed[name]["unit"] != columns[name]["unit"] for name in columns):
            fail("transform_sweep_columns_invalid", "Bind the same quantities and output units across the replicate group.",
                 "/inputs", "same_columns_and_units", dataset_id=source["id"])
        for index, (x_value, origin) in enumerate(zip(observed[x_name]["values"], row_origins(source), strict=True)):
            if x_value is None:
                continue
            values = {name: observed[name]["values"][index] for name in metrics}
            if not any(value is not None for value in values.values()):
                continue
            bucket = rows.setdefault(x_value, {})
            for name, value in values.items():
                if value is not None:
                    bucket.setdefault(name, []).append(value)
            origins.setdefault(x_value, []).extend(origin)

    axis = sorted(rows)
    columns[x_name]["values"] = axis
    counts: dict[str, list[int]] = {}
    for name in metrics:
        samples = [rows[x_value].get(name, []) for x_value in axis]
        values = [sum(group) / len(group) if group else None for group in samples]
        if any(value is not None and not math.isfinite(value) for value in values):
            fail("transform_nonfinite_result", "Replicate mean overflows the finite numeric domain.",
                 "/parameters", "finite_result", column_id=name)
        columns[name]["values"] = values
        counts[name] = [len(group) for group in samples]
    result = {"id": node["output"], "columns": columns, "provenance": merge_provenance(sources)}
    return result, {"x_column": x_name, "input_order": [source["id"] for source in sources],
                    "row_order": "ascending_exact_x", "point_policy": "average_each_available_metric",
                    "contributor_counts": counts, "row_origins": [origins[x_value] for x_value in axis]}


def execute(node: dict[str, Any], sources: list[dict[str, Any]], operation: Any, *,
            multiple_inputs: bool) -> tuple[dict[str, Any], str]:
    assert multiple_inputs
    input_hashes = [dataset_hash(value) for value in sources]
    key = canonical_json_sha256({"node": node, "inputs": input_hashes}, allow_nan=False)
    result, details = operation(node, sources)
    return record_result(node, result, details, input_hashes, key), key
