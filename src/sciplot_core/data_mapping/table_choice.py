"""Original worksheet/range evidence and explicit multi-series curve selections."""

from __future__ import annotations

from pathlib import Path
import math
from typing import Any

import pandas as pd

from sciplot_core.data_mapping.column_choice import _original_text
from sciplot_core.data_mapping.table_metadata import resolve_column_metadata
from sciplot_core.data_mapping.output_files import _safe_output_name
from sciplot_core.data_mapping.raw_tables import _read_raw_table
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.mapping_contract import DataColumnMapping, DataMappingProposal, DataSourceReference
from sciplot_core.materials_rules import get_rule
from sciplot_core.semantic_sources.paired_curve_table_metadata import explicit_header_unit


def _read(source: Path, sheet: str | None, digest: str) -> pd.DataFrame:
    return _read_raw_table(DataSourceReference(
        "source", source.name, digest, sheet=sheet, header_row=None,
    ), source, preserve_cells=True).frame


def _rows(frame: pd.DataFrame, indices: list[int]) -> list[dict[str, Any]]:
    return [{"row_index": row, "cells": [_original_text(value) for value in frame.iloc[row]]}
            for row in sorted(set(indices)) if 0 <= row < len(frame)]


def table_choice_snapshot(source: Path, rule_id: str) -> dict[str, Any] | None:
    source = source.expanduser().resolve()
    if not source.is_file() or source.suffix.casefold() not in {".csv", ".tsv", ".xlsx", ".xls", ".xlsm"}:
        return None
    rule = get_rule(rule_id)
    if rule.fixture_status != "ready" or rule.scientific_source_adapter != "registered_paired_curve":
        return None
    before = file_sha256(source)
    sheets: list[str | None] = [None]
    if source.suffix.casefold() in {".xlsx", ".xls", ".xlsm"}:
        with pd.ExcelFile(source) as workbook:
            sheets = list(workbook.sheet_names)
    tables = []
    for sheet in sheets:
        try:
            frame = _read(source, sheet, before)
        except ValueError as exc:
            if "empty" not in str(exc):
                raise
            tables.append({"sheet": sheet, "row_count": 0, "column_count": 0, "rows": []})
            continue
        tables.append({"sheet": sheet, "row_count": len(frame), "column_count": frame.shape[1],
                       "rows": _rows(frame.iloc[:, :64], list(range(min(32, len(frame))))),
                       "preview_truncated": len(frame) > 32 or frame.shape[1] > 64})
    if file_sha256(source) != before:
        raise ValueError("Table-choice source changed while reading.")
    return {"kind": "sciplot_table_choice", "version": 1, "source": str(source),
            "file_sha256": before, "rule_id": rule_id, "tables": tables,
            "indices": "zero_based; data_end_row is exclusive"}


def select_table(snapshot: dict[str, Any], selection: dict[str, Any],
                 metadata_confirmations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Bind explicit metadata/data rows without filling blanks or guessing samples."""
    source = Path(snapshot["source"])
    fresh = table_choice_snapshot(source, snapshot["rule_id"])
    if fresh != snapshot:
        raise ValueError("Table-choice original evidence changed.")
    required = {"sheet", "header_rows", "data_start_row", "data_end_row"}
    optional = {"unit_row", "sample_row"}
    if not isinstance(selection, dict) or not required <= set(selection) or set(selection) - required - optional:
        raise ValueError("Select sheet, header_rows, data_start_row and data_end_row; optional unit_row/sample_row.")
    if selection["sheet"] not in [table["sheet"] for table in snapshot["tables"]]:
        raise ValueError("Select an exact original worksheet name (null for CSV/TSV).")
    headers = selection["header_rows"]
    if not isinstance(headers, list) or not 1 <= len(headers) <= 8 or any(type(row) is not int or row < 0 for row in headers) or len(set(headers)) != len(headers):
        raise ValueError("header_rows needs 1–8 distinct original row indices.")
    start, end = selection["data_start_row"], selection["data_end_row"]
    if type(start) is not int or type(end) is not int or not 0 <= start < end:
        raise ValueError("Data rows need increasing non-negative integer bounds (end exclusive).")
    metadata = [*headers]
    for key in optional:
        if key in selection and selection[key] is not None:
            value = selection[key]
            if type(value) is not int or value < 0:
                raise ValueError(f"{key} must be an original row index or null.")
            metadata.append(value)
    frame = _read(source, selection["sheet"], snapshot["file_sha256"])
    if end > len(frame) or any(row >= start for row in metadata) or frame.shape[1] > 256:
        raise ValueError("Metadata must precede the selected data region; bounds must fit the table (up to 256 columns).")
    rule = get_rule(snapshot["rule_id"])
    columns = []
    for column in range(frame.shape[1]):
        evidence = {f"{row},{column}": _original_text(frame.iat[row, column]) for row in metadata}
        header = " ".join(_original_text(frame.iat[row, column]).strip() for row in headers).strip()
        unit_row, sample_row = selection.get("unit_row"), selection.get("sample_row")
        unit = (_original_text(frame.iat[unit_row, column]).strip() if unit_row is not None else explicit_header_unit(header))
        sample = _original_text(frame.iat[sample_row, column]) if sample_row is not None else ""
        numbers = pd.to_numeric(frame.iloc[start:end, column], errors="coerce")
        invalid = [start + offset for offset, value in enumerate(numbers) if not math.isfinite(float(value))]
        columns.append({"index": column, "header": header, "unit": unit, "sample": sample,
                        "cell_evidence": evidence,
                        "numeric": {"valid": not invalid, "point_count": end - start,
                                    "invalid_count": len(invalid), "invalid_row_indices": invalid[:16]}})
    confirmations = metadata_confirmations if metadata_confirmations is not None else []
    resolve_column_metadata(columns, confirmations, source_sha256=snapshot["file_sha256"],
                            sheet=selection["sheet"], frame=frame, rule=rule)
    if file_sha256(source) != snapshot["file_sha256"]:
        raise ValueError("Table-choice source changed while reading.")
    return {"kind": "sciplot_table_columns", "version": 1, "source": str(source),
            "file_sha256": snapshot["file_sha256"], "rule_id": snapshot["rule_id"],
            "table_snapshot": snapshot, "table_selection": selection, "columns": columns,
            "metadata_confirmations": confirmations,
            "rows": _rows(frame, [*metadata, *range(start, min(start + 4, end)), end - 1])}


def proposal_for_table_columns(
    snapshot: dict[str, Any], *, pairs: list[dict[str, int]], request_path: Path,
    proposal_id: str, created_at: str,
) -> DataMappingProposal:
    if select_table(snapshot["table_snapshot"], snapshot["table_selection"], snapshot.get("metadata_confirmations")) != snapshot:
        raise ValueError("Selected table or original evidence changed.")
    contents = _proposal_contents(snapshot, pairs)
    return DataMappingProposal(
        base_request_sha256=file_sha256(request_path), **contents,
        provider="explicit_table_choice", proposal_id=proposal_id, created_at=created_at,
        table_confirmation={"rule_id": snapshot["rule_id"], "selection": snapshot["table_selection"],
                            "metadata_confirmations": snapshot.get("metadata_confirmations", []), "pairs": pairs},
        rationale="Explicit original worksheet, metadata evidence, data rows and x/y pairs; no raw cells rewritten.",
    )


def _proposal_contents(snapshot: dict[str, Any], pairs: list[dict[str, int]]) -> dict[str, Any]:
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= 32:
        raise ValueError("Select 1–32 explicit x/y pairs.")
    selection, source = snapshot["table_selection"], Path(snapshot["source"])
    columns = {column["index"]: column for column in snapshot["columns"]}
    references, mappings, labels, units = [], [], {}, {}
    selected_y: set[int] = set()
    for index, pair in enumerate(pairs):
        if not isinstance(pair, dict) or set(pair) != {"x_column", "y_column"} or any(type(value) is not int or value not in columns for value in pair.values()):
            raise ValueError("Each pair needs original integer x_column/y_column indices.")
        x, y = columns[pair["x_column"]], columns[pair["y_column"]]
        if x["index"] == y["index"] or not x["x_eligible"] or not y["y_eligible"]:
            raise ValueError("Selected columns need explicit axis names, observed units, and finite numeric values.")
        if y["index"] in selected_y:
            raise ValueError("A response column cannot be assigned to multiple samples.")
        selected_y.add(y["index"])
        sample = y["sample"] or x["sample"] or (source.stem if len(pairs) == 1 and selection.get("sample_row") is None else "")
        if not sample or (x["sample"] and x["sample"] != sample):
            raise ValueError("Selected columns belong to different samples or lack an original sample label; shared X requires an empty sample cell.")
        if sample in labels.values():
            raise ValueError("Duplicate sample labels require an explicit source correction; samples cannot be merged silently.")
        source_id = f"series_{index:03}"
        labels[source_id] = sample
        references.append(DataSourceReference(
            source_id, source.name, snapshot["file_sha256"], sheet=selection["sheet"], header_row=None,
            data_start_row=selection["data_start_row"], data_end_row=selection["data_end_row"],
            cell_evidence={**x["cell_evidence"], **y["cell_evidence"]},
        ))
        for role, column in (("x", x), ("y", y)):
            mappings.append(DataColumnMapping(source_id, column["index"], column["output_header"], role,
                                              expected_header=f"column_{column['index']}"))
            if column["output_header"] in units and units[column["output_header"]] != column["unit"]:
                raise ValueError("Selected output headers have conflicting units.")
            units[column["output_header"]] = column["unit"]
    contents = dict(sources=tuple(references), columns=tuple(mappings), sample_labels=labels, unit_overrides=units)
    proposal = DataMappingProposal(
        base_request_sha256="0" * 64, **contents,
        provider="explicit_table_choice",
    )
    used: set[str] = set()
    for reference in references:
        if Path(_safe_output_name(reference, proposal, used=used)).stem != labels[reference.source_id]:
            raise ValueError("The selected sample label cannot be preserved exactly in the mapped output filename.")
    if file_sha256(source) != snapshot["file_sha256"]:
        raise ValueError("Table-choice source changed while creating the proposal.")
    return contents


def verify_table_confirmation(proposal: DataMappingProposal, source: Path) -> None:
    """Rebuild mapping meaning from source and frozen evidence at preview/execution/export."""
    binding = proposal.table_confirmation
    if not binding:
        return  # Historical proposals retain their original signed contract.
    snapshot = table_choice_snapshot(source, binding["rule_id"])
    if snapshot is None:
        raise ValueError("Confirmed table source is no longer supported.")
    columns = select_table(snapshot, binding["selection"], binding["metadata_confirmations"])
    expected = _proposal_contents(columns, binding["pairs"])
    if any(getattr(proposal, key) != value for key, value in expected.items()) or proposal.transformations or proposal.request_patch:
        raise ValueError("Confirmed table metadata does not reproduce the proposed mapping.")
