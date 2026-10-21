"""Count and validate original wide Impact cells without summary statistics."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.text_values import clean_text, token
from sciplot_core.semantic_sources.impact_sources import _read_impact_source, _validated_impact_unit, _is_impact_metric
from sciplot_core.semantic_sources.table_candidate_sources import read_candidate_tables
from sciplot_core.semantic_sources.table_scanning import _float


def wide_replicate_evidence(source: Path) -> dict[str, Any]:
    """Keep source cell identities; existing scientific owner still validates units."""
    if not source.is_file():
        raise ValueError("Delivered valid n currently requires one original wide replicate file.")
    _read_impact_source(source)
    workbook = source.suffix.casefold() in {".xlsx", ".xls", ".xlsm"}
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for table_name, table in read_candidate_tables(source):
        if table.shape[0] < 4:
            continue
        condition = table_name.split(":", 1)[-1] if workbook else ""
        for column in range(table.shape[1]):
            metric = token(table.iat[0, column])
            if not _is_impact_metric(metric):
                continue
            sample = clean_text(table.iat[2, column])
            if not sample:
                raise ValueError("Delivered valid n requires each original wide column's sample identity.")
            unit = _validated_impact_unit([table.iat[1, column]])
            key = (condition, sample)
            group = groups.setdefault(key, {"sample": sample, "condition": condition,
                "metric": "Impact strength", "unit": unit, "valid_n": 0, "missing_count": 0,
                "source_table": table_name, "source_columns": [], "missing_cells": [],
                "data_start_row": int(table.index[3]), "data_end_row": int(table.index[-1]) + 1})
            physical_column = int(table.columns[column])
            group["source_columns"].append(physical_column)
            for row in range(3, table.shape[0]):
                cell = table.iat[row, column]
                value = _float(cell)
                if pd.isna(cell) or not clean_text(cell):
                    group["missing_count"] += 1
                    group["missing_cells"].append([int(table.index[row]), physical_column])
                elif value is None or not math.isfinite(value):
                    raise ValueError(f"Unresolved nonnumeric/nonfinite replicate at {table_name}, row {int(table.index[row])}, column {physical_column}; a missing-value exclusion cannot reinterpret it.")
                else:
                    group["valid_n"] += 1
    if not groups:
        raise ValueError("Delivered valid n requires the original wide metric/unit/sample rows; other Impact layouts retain their existing contract.")
    return {"version": 1, "original_source": str(source.expanduser().resolve()),
            "source_sha256": source_tree_sha256(source), "groups": list(groups.values())}


def validate_replicate_disclosure(source: Path, value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"version", "original_source", "source_sha256", "groups", "missing_values"}:
        raise ValueError("Replicate disclosure requires complete source-bound count evidence and missing policy.")
    evidence = wide_replicate_evidence(source)
    policy = value["missing_values"]
    expected_policy = "exclude" if any(group["missing_count"] for group in evidence["groups"]) else "none_present"
    declared_evidence = {key: item for key, item in value.items() if key != "missing_values"}
    if policy != expected_policy or canonical_json_sha256(declared_evidence, allow_nan=False) != canonical_json_sha256(evidence, allow_nan=False):
        raise ValueError("Replicate count disclosure does not match current original cells or the explicit missing policy.")
    if any(group["valid_n"] < 2 for group in evidence["groups"]):
        raise ValueError("Sample SD requires at least two valid numeric observations in every original group.")
    return {**evidence, "missing_values": policy}
