"""Read one explicit original categorical table without rewriting its cells."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.data_mapping.original_tables import read_original_table, source_table_snapshot
from sciplot_core.data_mapping.table_choice import select_table
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.semantic_sources.registered_paired_curve_transform import _comparable_unit
from sciplot_core.studio_render.models import StudioPreparationBlocked, StudioSourceFrame
from sciplot_core.mapping_contract.categorical import validate_categorical_binding


def categorical_table_facts(source: Path, binding: dict[str, Any]) -> dict[str, Any]:
    """Return source evidence and metadata conflicts before allocating a project."""
    validate_categorical_binding(binding)
    snapshot = source_table_snapshot(source, sheets=[binding["table_selection"]["sheet"]] if "table_selection" in binding else None)
    if snapshot is None:
        raise StudioPreparationBlocked("categorical_source_unsupported", "Select one original CSV/TSV or Excel file.")
    if binding.get("source_sha256", snapshot["file_sha256"]) != snapshot["file_sha256"]:
        raise StudioPreparationBlocked("categorical_source_changed", "The categorical source SHA is stale; inspect its current original table.")
    if "table_selection" not in binding:
        return snapshot
    return select_table(snapshot, binding["table_selection"], binding.get("metadata_confirmations", []))


def read_categorical_frame(source: Path, binding: dict[str, Any], *,
                           legacy_numeric_parser: bool = False,
                           source_artifact_origin: dict[str, str] | None = None) -> StudioSourceFrame:
    validate_categorical_binding(binding, complete=True)
    if binding.get("source_identity_version") == 1:
        original = Path(source_artifact_origin["path"]).resolve() if source_artifact_origin else source.resolve()
        if binding.get("source_namespace") != str(original):
            raise ValueError("The categorical namespace differs from its proved physical original source.")
        if source_artifact_origin and source_artifact_origin["sha256"] != binding["source_sha256"]:
            raise ValueError("The captured categorical source version differs from its binding.")
    facts = categorical_table_facts(source, binding)
    columns = {item["index"]: item for item in facts["columns"]}
    roles = [binding["sample_column"], *[item["column_index"] for item in binding["value_columns"]]]
    condition = binding.get("condition_column")
    if condition is not None:
        roles.append(condition)
    if len(set(roles)) != len(roles) or any(index not in columns for index in roles):
        raise StudioPreparationBlocked("invalid_categorical_columns", "Sample, condition and value roles need distinct original column indices inside the selected table.")
    labels = [item.get("label", columns[item["column_index"]]["header"]) for item in binding["value_columns"]]
    if any(not label.strip() or (" || " in label and "source_identity_version" not in binding)
           for label in labels) or len(set(labels)) != len(labels):
        raise StudioPreparationBlocked("invalid_categorical_series_labels", "Value-series display labels must be nonempty and unique, without the reserved factor separator.")
    units: list[str] = []
    value_facts = []
    for value in binding["value_columns"]:
        column = columns[value["column_index"]]
        if column["metadata_conflicts"]:
            raise StudioPreparationBlocked("categorical_metadata_conflict", f"Original value column {column['index']} has conflicting metadata: {column['metadata_conflicts']}.")
        if not column["unit"] or not column["header"]:
            raise StudioPreparationBlocked("categorical_metadata_required", f"Confirm the measured quantity and unit of original value column {column['index']} with source-bound metadata_confirmations; no unit is inferred.")
        units.append(_comparable_unit(column["unit"]))
        value_facts.append(column)
    if len(set(units)) != 1:
        raise StudioPreparationBlocked("categorical_units_incompatible", "One categorical value axis requires the same stated unit for all selected value columns; create separate figures for different units.")
    if binding["mode"] != "given_values" and len(value_facts) != 1:
        raise StudioPreparationBlocked("categorical_summary_value_ambiguous", "Long-form replicate statistics require exactly one selected measurement column; other numeric columns remain unselected.")
    selection = binding["table_selection"]
    raw = read_original_table(source, selection["sheet"], binding["source_sha256"])
    frame = raw.iloc[selection["data_start_row"]:selection["data_end_row"]].copy()
    frame.attrs["categorical_binding"] = binding
    frame.attrs["categorical_value_facts"] = value_facts
    if legacy_numeric_parser:
        frame.attrs["sciplot_legacy_numeric_parser"] = True
    if file_sha256(source) != binding["source_sha256"]:
        raise StudioPreparationBlocked("source_changed_during_read", "The categorical source changed during its original-table read.")
    return StudioSourceFrame(source.stem, source.resolve(), binding["source_sha256"], frame)
