"""Map proposal columns and transformations into previewable source frames."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.mapping_contract import (
    DataMappingProposal,
)

from sciplot_core.data_mapping.contracts import (
    DATA_MAPPING_PREVIEW_KIND,
    DATA_MAPPING_PREVIEW_VERSION,
    _PRIMARY_NUMERIC_COLUMN_ROLES,
    data_mapping_proposal_sha256,
    load_data_mapping_proposal,
    _resolve_source_root,
    verify_data_mapping_sources,
    _verify_request_binding,
)

from sciplot_core.data_mapping.raw_tables import (
    _RawTable,
    _read_raw_table,
    _column_mappings_for_source,
    _map_columns,
    _numeric_series,
)

from sciplot_core.data_mapping.transformations import (
    _apply_transformation,
)


def _apply_source_mapping(
    proposal: DataMappingProposal,
    raw: _RawTable,
) -> tuple[pd.DataFrame, dict[str, str], list[dict[str, Any]]]:
    mappings = _column_mappings_for_source(proposal, raw.source.source_id)
    frame = _map_columns(raw, mappings)
    primary_numeric_columns = {
        mapping.output_column
        for mapping in mappings
        if mapping.role in _PRIMARY_NUMERIC_COLUMN_ROLES
    }
    units = {
        column: unit
        for column, unit in proposal.unit_overrides.items()
        if column in frame.columns
    }
    events: list[dict[str, Any]] = []
    for transformation in proposal.transformations:
        if (
            transformation.source_ids
            and raw.source.source_id not in transformation.source_ids
        ):
            continue
        frame, units, event = _apply_transformation(frame, units, transformation)
        parameters = transformation.parameters
        operation = transformation.transformation_type
        if operation == "rename":
            renamed = parameters["columns"]
            primary_numeric_columns = {
                str(renamed.get(column, column)) for column in primary_numeric_columns
            }
        elif operation == "select":
            selected = {str(column) for column in parameters["columns"]}
            primary_numeric_columns &= selected
        elif operation == "exclude" and "columns" in parameters:
            primary_numeric_columns -= {str(column) for column in parameters["columns"]}
        elif operation == "unit_convert":
            source_column = str(parameters["column"])
            if source_column in primary_numeric_columns:
                primary_numeric_columns.add(
                    str(parameters.get("output_column") or source_column)
                )
        elif operation == "derive_ratio":
            if {
                str(parameters["numerator"]),
                str(parameters["denominator"]),
            } & primary_numeric_columns:
                primary_numeric_columns.add(str(parameters["output"]))
        elif operation == "normalize_baseline":
            if str(parameters["column"]) in primary_numeric_columns:
                primary_numeric_columns.add(str(parameters["output"]))
        elif operation == "aggregate_replicates":
            retained = {
                str(column)
                for column in (
                    *parameters["group_by"],
                    *parameters["value_columns"],
                )
            }
            primary_numeric_columns &= retained
        events.append(event)
    dangling_units = sorted(set(units) - set(frame.columns))
    if dangling_units:
        raise ValueError(
            "Unit metadata references columns removed by transformations: "
            + ", ".join(dangling_units)
        )
    if frame.empty:
        raise ValueError(
            f"Data mapping removed every row from {raw.source.source_id!r}."
        )
    primary_numeric_columns &= {str(column) for column in frame.columns}
    if not primary_numeric_columns:
        raise ValueError(
            "Data mapping removed every numeric x, y, z, or value column "
            f"from {raw.source.source_id!r}."
        )
    finite_value_found = False
    for column in sorted(primary_numeric_columns):
        numeric = _numeric_series(
            frame,
            column,
            operation="final data mapping validation",
        )
        infinite = numeric.notna() & ~numeric.map(math.isfinite)
        if infinite.any():
            rows = [int(index) for index in numeric.index[infinite].tolist()[:8]]
            raise ValueError(
                "Final data mapping validation found non-finite values "
                f"in {column!r} at rows {rows}."
            )
        finite_value_found = finite_value_found or bool(
            numeric.map(math.isfinite).any()
        )
    if not finite_value_found:
        raise ValueError(
            "Data mapping produced no finite numeric values for "
            f"{raw.source.source_id!r}."
        )
    return frame, units, events


def _prepare_mapping_frames(
    proposal: DataMappingProposal,
    *,
    source_root: Path,
) -> tuple[
    dict[str, Path],
    dict[str, pd.DataFrame],
    dict[str, dict[str, str]],
    dict[str, list[dict[str, Any]]],
    dict[str, tuple[str, ...]],
]:
    resolved_sources = verify_data_mapping_sources(proposal, source_root=source_root)
    frames: dict[str, pd.DataFrame] = {}
    units: dict[str, dict[str, str]] = {}
    events: dict[str, list[dict[str, Any]]] = {}
    headers: dict[str, tuple[str, ...]] = {}
    for reference in proposal.sources:
        raw = _read_raw_table(reference, resolved_sources[reference.source_id])
        mapped, mapped_units, mapped_events = _apply_source_mapping(proposal, raw)
        frames[reference.source_id] = mapped
        units[reference.source_id] = mapped_units
        events[reference.source_id] = mapped_events
        headers[reference.source_id] = raw.headers
    return resolved_sources, frames, units, events, headers


def preview_data_mapping_proposal(
    proposal: DataMappingProposal | str | Path | dict[str, Any],
    *,
    source_root: str | Path,
    request_path: str | Path,
) -> dict[str, Any]:
    resolved = load_data_mapping_proposal(proposal)
    root = _resolve_source_root(source_root)
    request = _verify_request_binding(resolved, request_path=request_path)
    sources, frames, units, events, headers = _prepare_mapping_frames(
        resolved, source_root=root
    )
    return {
        "kind": DATA_MAPPING_PREVIEW_KIND,
        "version": DATA_MAPPING_PREVIEW_VERSION,
        "status": "ready_for_confirmation",
        "proposal_id": resolved.proposal_id,
        "proposal_sha256": data_mapping_proposal_sha256(resolved),
        "provider": resolved.provider,
        "base_request": str(request),
        "base_request_sha256": resolved.base_request_sha256,
        "source_root": str(root),
        "sources": [
            {
                "source_id": reference.source_id,
                "relative_path": reference.relative_path,
                "sha256": reference.sha256,
                "source_size_bytes": sources[reference.source_id].stat().st_size,
                "detected_headers": list(headers[reference.source_id]),
                "mapped_columns": [
                    str(column) for column in frames[reference.source_id].columns
                ],
                "row_count": int(frames[reference.source_id].shape[0]),
                "column_count": int(frames[reference.source_id].shape[1]),
                "units": dict(units[reference.source_id]),
                "transformations": events[reference.source_id],
                "sample_label": resolved.sample_labels.get(reference.source_id),
            }
            for reference in resolved.sources
        ],
        "request_patch": json_safe(resolved.request_patch),
        "confidence": resolved.confidence,
        "rationale": resolved.rationale,
        "raw_values_in_preview": False,
        "writes_performed": False,
        "requires_confirmation_receipt": True,
    }
