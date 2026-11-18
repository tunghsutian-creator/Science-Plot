"""Lower observed multi-metric replicate columns without inventing missing columns."""
from pathlib import Path
from typing import Any

from sciplot_core.plot_transforms import builtin_executor
from sciplot_core.plot_transforms.unit_relations import resolve_unit_relation
from sciplot_core.semantic_sources.models import RheologySweepSample
from sciplot_core.task_errors import TaskControlError


def prepare_measured_replicate(
    sample: RheologySweepSample, original: dict[str, Any], columns: list[dict[str, Any]],
    transforms: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    """Prepare one actual original block, including measurements not plotted as Y."""
    selection = original["table_selection"]
    if (sample.original_group_region != (selection["header_rows"][0], selection["data_start_row"],
            selection["data_end_row"]) or Path(original["path"]).resolve() != sample.source.resolve()):
        raise TaskControlError("frequency_managed_group_origin_unavailable", "The raw replicate region changed.")
    identifiers = {column["column_index"]: column for column in columns}
    measured = {"x": sample.x_conversion or {}, **(sample.metric_conversions or {})}
    selected = {}
    for quantity, evidence in measured.items():
        index = evidence.get("source_column")
        if index is None:
            continue  # A derived, not measured, metric is not an original column.
        column = identifiers.get(index)
        if column is None or column["header"] != evidence.get("source_header") or not column["unit"]:
            raise TaskControlError("frequency_managed_metric_origin_unavailable", "Match each measured metric to its original column and unit.")
        target = "rad/s" if quantity == "x" else sample.metric_units[quantity]
        relation = resolve_unit_relation(column["unit"], target)
        if relation["offset"] != 0 or relation["factor"] != evidence["factor"]:
            raise TaskControlError("frequency_managed_metric_unit_unavailable", "The Managed conversion does not reproduce this registered metric.")
        selected[quantity] = (column["column_id"], column["unit"], target)
    if "x" not in selected or len(selected) < 2 or len({entry[0] for entry in selected.values()}) != len(selected):
        raise TaskControlError("frequency_managed_metric_origin_unavailable", "The replicate requires frequency and at least one distinct measured metric.")
    raw_id = original["source_id"] + ":" + original["block_id"]
    source = {"source_id": raw_id, "path": original["path"], "sha256": original["sha256"], "table_selection": selection}

    def emit(kind: str, previous: str, parameters: dict[str, Any]) -> str:
        index = len(transforms)
        output = f"frequency-stage:{index}"
        transforms.append({"id": f"frequency-transform:{index}", "kind": kind, "inputs": [previous],
                           "output": output, "parameters": parameters,
                           "executor": builtin_executor(kind), "determinism": "deterministic"})
        return output

    current = emit("select", raw_id, {"columns": [item[0] for item in selected.values()]})
    current = emit("rename", current, {"columns": {identifier: {"id": quantity, "label": quantity}
        for quantity, (identifier, _, _) in selected.items()}})
    for quantity, (_, unit, target) in selected.items():
        if unit != target:
            current = emit("convert_unit", current, {"columns": [quantity], "from_unit": unit, "to_unit": target})
    return source, current


def prepare_measured_frequency_group(
    replicates: list[tuple[RheologySweepSample, dict[str, Any], list[dict[str, Any]]]], *, metric: str,
    transforms: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    """Retain every measured x contributor before selecting the plotted metric."""
    if not replicates or not any(
            (sample.metric_conversions or {}).get(metric, {}).get("source_column") is not None
            for sample, _, _ in replicates):
        raise TaskControlError("frequency_managed_metric_unavailable", "The selected group needs an available measured metric.")
    sources, inputs = [], []
    for sample, original, columns in replicates:
        source, dataset = prepare_measured_replicate(sample, original, columns, transforms)
        sources.append(source)
        inputs.append(dataset)
    if len(inputs) == 1:
        return sources, inputs[0]
    kind = "rheology_mean_exact_x"
    index = len(transforms)
    output = f"frequency-stage:{index}"
    transforms.append({"id": f"frequency-transform:{index}", "kind": kind, "inputs": inputs,
                       "output": output, "parameters": {"x_column": "x"},
                       "executor": builtin_executor(kind), "determinism": "deterministic"})
    return sources, output
