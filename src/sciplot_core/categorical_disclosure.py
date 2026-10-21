"""Project original categorical cell identities into the existing n evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.studio_render.categorical_bindings import read_categorical_frame
from sciplot_core.studio_render.categorical_bound_series import bound_categorical_series


def categorical_replicate_evidence(source: Path, binding: dict[str, Any]) -> dict[str, Any]:
    frame = read_categorical_frame(source, binding)
    _, info = bound_categorical_series([frame], missing_values="exclude")
    if binding["mode"] == "given_values":
        raise ValueError("Given values do not declare replicate statistics or valid-n summaries.")
    selection = binding["table_selection"]
    value = frame.frame.attrs["categorical_value_facts"][0]
    conditions = info["condition_labels"] or [""]
    groups = []
    for sample in info["source_category_ids"]:
        for condition in conditions:
            valid = [cell for cell in info["categorical_source_rows"]
                     if cell["sample"] == sample and cell["condition"] == condition]
            missing = [cell for cell in info["categorical_missing_cells"]
                       if cell["sample"] == sample and cell["condition"] == condition]
            groups.append({"sample": sample, "condition": condition,
                "metric": value["header"], "unit": value["unit"],
                "valid_n": len(valid), "missing_count": len(missing),
                "source_table": selection["sheet"] or source.name,
                "source_columns": [value["index"]],
                "missing_cells": [[cell["row_index"], cell["column_index"]] for cell in missing],
                "data_start_row": selection["data_start_row"], "data_end_row": selection["data_end_row"]})
    return {"version": 1, "source_sha256": source_tree_sha256(source),
            "original_source": str(source.resolve()), "groups": groups}


def categorical_disclosure(source: Path, binding: dict[str, Any], *, policy: str | None) -> dict[str, Any]:
    evidence = categorical_replicate_evidence(source, binding)
    expected = "exclude" if any(group["missing_count"] for group in evidence["groups"]) else "none_present"
    if expected == "exclude" and policy != "exclude":
        raise ValueError("Categorical missing replicates require an explicit exclusion policy.")
    return {**evidence, "missing_values": expected}
