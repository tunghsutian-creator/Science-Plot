"""Original worksheet/range evidence and explicit multi-series curve selections."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

from sciplot_core.data_mapping.raw_tables import (
    MAPPING_NUMERIC_V3, MappingNumericContract, MappingNumericRejected, _coerce_mapping_numeric, _original_text,
)
from sciplot_core.data_mapping.curve_support import supports_replicate_mapping, supports_table_mapping
from sciplot_core.data_mapping.table_metadata import resolve_column_metadata
from sciplot_core.data_mapping.output_files import _safe_output_name
from sciplot_core.data_mapping.pair_choice import pair_proposal_contents
from sciplot_core.data_mapping.original_tables import (
    original_rows as _rows,
    read_original_table as read_original_table,
    source_table_snapshot as source_table_snapshot,
)
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_locations import resolve_source_path
from sciplot_core.foundation.source_errors import SourceVersionMismatch
from sciplot_core.mapping_contract import DataColumnMapping, DataMappingProposal, DataSourceReference
from sciplot_core.mapping_contract.source_identity import source_view_id
from sciplot_core.materials_rules import get_rule
from sciplot_core.semantic_sources.paired_curve_table_metadata import explicit_header_unit
from sciplot_core.source_tables.read_session import read_table_once
from sciplot_core.semantic_sources.impact_sources import _is_impact_metric, _validated_impact_unit


# Retained first-party compatibility name; new consumers use the original-table port.
_read = read_original_table


def table_choice_snapshot(source: Path, rule_id: str, *, sheets: list[str | None] | None = None,
                          expected_sha256: str | None = None) -> dict[str, Any] | None:
    source = source.expanduser().resolve()
    rule = get_rule(rule_id)
    if not supports_table_mapping(rule):
        return None
    return (source_table_snapshot(source, rule_id=rule_id, sheets=sheets) if expected_sha256 is None else
            source_table_snapshot(source, rule_id=rule_id, sheets=sheets, expected_sha256=expected_sha256))


def _numeric_summary(source: Path, sheet: str | None, digest: str,
                     frame: pd.DataFrame, start: int, end: int, *,
                     numeric_contract: MappingNumericContract = MAPPING_NUMERIC_V3) -> pd.DataFrame:
    """Reuse byte-bound numeric facts, never scientific eligibility or declarations."""
    def scan() -> pd.DataFrame:
        summaries = []
        for column in range(frame.shape[1]):
            numbers = _coerce_mapping_numeric(frame.iloc[start:end, column], numeric_contract=numeric_contract,
                                              legacy_pandas=True).to_numpy(dtype=float)
            invalid = np.flatnonzero(~np.isfinite(numbers))
            rows = (invalid[:16] + start).tolist()
            summaries.append([len(invalid), *rows, *([-1] * (16 - len(rows)))])
        return pd.DataFrame(summaries)

    return read_table_once(source, ("mapping_numeric_facts", sheet, start, end, numeric_contract), scan,
                           expected_sha256=digest, content_only=True)


def select_table(snapshot: dict[str, Any], selection: dict[str, Any],
                 metadata_confirmations: list[dict[str, Any]] | None = None, *,
                 numeric_contract: MappingNumericContract = MAPPING_NUMERIC_V3) -> dict[str, Any]:
    """Bind explicit metadata/data rows without filling blanks or guessing samples."""
    source = Path(snapshot["source"])
    # Selection validates original evidence. Discovery/proposal callers retain
    # their rule-adapter eligibility gate in table_choice_snapshot itself.
    try:
        fresh = source_table_snapshot(source, rule_id=snapshot["rule_id"], sheets=snapshot.get("observed_sheets"),
                                      expected_sha256=snapshot["file_sha256"])
    except SourceVersionMismatch as exc:
        raise ValueError("Table-choice original evidence changed.") from exc
    if fresh != snapshot:
        raise ValueError("Table-choice original evidence changed.")
    required = {"sheet", "header_rows", "data_start_row", "data_end_row"}
    optional = {"unit_row", "sample_row", "expand_merged_metadata"}
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
    if "expand_merged_metadata" in selection and type(selection["expand_merged_metadata"]) is not bool:
        raise ValueError("expand_merged_metadata must be an explicit boolean.")
    for key in ("unit_row", "sample_row"):
        if key in selection and selection[key] is not None:
            value = selection[key]
            if type(value) is not int or value < 0:
                raise ValueError(f"{key} must be an original row index or null.")
            metadata.append(value)
    frame = _read(source, selection["sheet"], snapshot["file_sha256"])
    if end > len(frame) or any(row >= start for row in metadata) or frame.shape[1] > 256:
        raise ValueError("Metadata must precede the selected data region; bounds must fit the table (up to 256 columns).")
    # A Managed original-value binding can carry ordinary XY context without
    # declaring a registered experiment or inheriting its axis/analysis rules.
    rule = None if snapshot["rule_id"] in {None, "ordinary_xy"} else get_rule(snapshot["rule_id"])
    expanded: dict[tuple[int, int], str] = {}
    anchors: dict[int, dict[str, str]] = {}
    associations: list[dict[str, Any]] = []
    if selection.get("expand_merged_metadata"):
        from sciplot_core.data_mapping.merged_metadata import merged_metadata_ranges, selected_metadata_cells

        expanded, anchors, associations = selected_metadata_cells(
            frame, metadata, ranges=merged_metadata_ranges(source, selection["sheet"],
                expected_sha256=snapshot["file_sha256"]), data_start=start)
    numeric_summary = _numeric_summary(source, selection["sheet"], snapshot["file_sha256"], frame, start, end,
                                       numeric_contract=numeric_contract)
    columns = []
    for column in range(frame.shape[1]):
        evidence = {f"{row},{column}": _original_text(frame.iat[row, column]) for row in metadata}
        def cell(row: int, column: int = column) -> str:
            return expanded.get((row, column), _original_text(frame.iat[row, column]))

        header = " ".join(cell(row).strip() for row in headers).strip()
        unit_row, sample_row = selection.get("unit_row"), selection.get("sample_row")
        unit = (cell(unit_row).strip() if unit_row is not None else explicit_header_unit(header))
        sample = cell(sample_row) if sample_row is not None else ""
        evidence.update(anchors.get(column, {}))
        counts = numeric_summary.iloc[column]
        invalid_count = int(counts.iloc[0])
        invalid_rows = [int(value) for value in counts.iloc[1:] if value >= 0]
        columns.append({"index": column, "header": header, "unit": unit, "sample": sample,
                        "cell_evidence": evidence,
                        "numeric": {"valid": invalid_count == 0, "point_count": end - start,
                                    "invalid_count": invalid_count, "invalid_row_indices": invalid_rows}})
        if selection.get("expand_merged_metadata"):
            original_header = " ".join(_original_text(frame.iat[row, column]).strip() for row in headers).strip()
            columns[-1]["raw_metadata"] = {
                "header": original_header,
                "unit": _original_text(frame.iat[unit_row, column]).strip() if unit_row is not None else explicit_header_unit(original_header),
                "sample": _original_text(frame.iat[sample_row, column]) if sample_row is not None else "",
            }
    confirmations = metadata_confirmations if metadata_confirmations is not None else []
    resolve_column_metadata(columns, confirmations, source_sha256=snapshot["file_sha256"],
                            sheet=selection["sheet"], frame=frame, rule=rule, source=source)
    if file_sha256(resolve_source_path(source, expected_sha256=snapshot["file_sha256"])) != snapshot["file_sha256"]:
        raise ValueError("Table-choice source changed while reading.")
    return {"kind": "sciplot_table_columns", "version": 1, "source": str(source),
            "file_sha256": snapshot["file_sha256"], "rule_id": snapshot["rule_id"],
            "table_snapshot": snapshot, "table_selection": selection, "columns": columns,
            "metadata_confirmations": confirmations,
            **({"merged_metadata": associations} if selection.get("expand_merged_metadata") else {}),
            "rows": _rows(frame, [*metadata, *range(start, min(start + 4, end)), end - 1])}


def proposal_for_table_columns(
    snapshot: dict[str, Any], *, request_path: Path, proposal_id: str, created_at: str,
    pairs: list[dict[str, Any]] | None = None, replicates: list[dict[str, Any]] | None = None,
    structured_identity: bool = True,
) -> DataMappingProposal:
    if select_table(snapshot["table_snapshot"], snapshot["table_selection"], snapshot.get("metadata_confirmations")) != snapshot:
        raise ValueError("Selected table or original evidence changed.")
    if (pairs is None) == (replicates is None):
        raise ValueError("Choose independent replicates or XY pairs, never both.")
    if replicates is not None:
        contents = replicate_proposal_contents(snapshot, replicates, structured_identity=structured_identity)
    else:
        assert pairs is not None
        contents = _proposal_contents(snapshot, pairs, structured_identity=structured_identity)
    return DataMappingProposal(
        base_request_sha256=file_sha256(request_path), **contents,
        provider="explicit_table_choice", proposal_id=proposal_id, created_at=created_at,
        table_confirmation={"rule_id": snapshot["rule_id"], "selection": snapshot["table_selection"],
                            "metadata_confirmations": snapshot.get("metadata_confirmations", []),
                            **({"replicates": replicates} if replicates is not None else {"pairs": pairs}),
                            **({"sample_row_encoding": "explicit_json_v1"} if replicates is None and any(
                                _numeric_label(label) for label in contents["sample_labels"].values()) else {})},
        rationale=("Explicit original worksheet, metadata evidence, complete data rows and independent replicate columns; no raw cells rewritten."
                   if replicates is not None else "Explicit original worksheet, metadata evidence, data rows and x/y pairs; no raw cells rewritten."),
    )


def _numeric_label(label: str) -> bool:
    try:
        float(label)
    except ValueError:
        return False
    return True


def _pair_columns(snapshot: dict[str, Any], pair: dict[str, Any], *,
                  numeric_contract: MappingNumericContract = MAPPING_NUMERIC_V3) -> dict[str, Any]:
    required = {"x_column", "y_column"}
    if (not isinstance(pair, dict) or not required <= set(pair)
            or set(pair) - required - {"table_selection", "metadata_confirmations", "label"}
            or any(type(pair[key]) is not int or pair[key] < 0 for key in required)):
        raise ValueError("Each pair needs original integer x_column/y_column indices and optional table_selection/metadata_confirmations.")
    selection = pair.get("table_selection", snapshot["table_selection"])
    if "label" in pair and (not isinstance(pair["label"], str) or not pair["label"].strip() or len(pair["label"]) > 160):
        raise ValueError("A display label must be nonempty text, up to 160 characters.")
    if not isinstance(selection, dict):
        raise ValueError("A pair's table_selection must be a complete original table region.")
    # Declarations for one worksheet never migrate implicitly to another.
    inherited = snapshot.get("metadata_confirmations", []) if selection.get("sheet") == snapshot["table_selection"]["sheet"] else []
    confirmations = pair.get("metadata_confirmations", inherited)
    if confirmations is None:
        raise ValueError("metadata_confirmations must be a complete list; use [] to withdraw.")
    if selection == snapshot["table_selection"] and confirmations == snapshot.get("metadata_confirmations", []):
        selected = snapshot
    else:
        selected = select_table(snapshot["table_snapshot"], selection, confirmations, numeric_contract=numeric_contract)
    if numeric_contract != MAPPING_NUMERIC_V3:
        columns = {column["index"]: column for column in selected["columns"]}
        if any(not columns[pair[axis]]["numeric"]["valid"] for axis in ("x_column", "y_column") if pair[axis] in columns):
            raise MappingNumericRejected("Confirmed XY cells are not finite under this historical mapping pipeline.")
    return selected


def replicate_proposal_contents(snapshot: dict[str, Any], replicates: list[dict[str, Any]], *,
                                structured_identity: bool = False,
                                numeric_contract: MappingNumericContract = MAPPING_NUMERIC_V3) -> dict[str, Any]:
    """Bind complete physical domains, retaining null positions and metadata."""
    if not supports_replicate_mapping(get_rule(snapshot["rule_id"])):
        raise ValueError("This source adapter does not consume independent replicate columns.")
    if not isinstance(replicates, list) or not 1 <= len(replicates) <= 32:
        raise ValueError("Select 1–32 original replicate columns.")
    source = Path(snapshot["source"])
    references, mappings = [], []
    labels: dict[str, str] = {}
    display_labels: dict[str, str] = {}
    occupied: dict[tuple[str | None, int], list[tuple[int, int]]] = {}
    for index, choice in enumerate(replicates):
        if (not isinstance(choice, dict) or "column_index" not in choice
                or set(choice) - {"column_index", "table_selection", "metadata_confirmations", "label"}
                or type(choice["column_index"]) is not int or choice["column_index"] < 0):
            raise ValueError("Each replicate needs an original integer column_index and optional region, metadata and label.")
        selection = choice.get("table_selection", snapshot["table_selection"])
        if not isinstance(selection, dict):
            raise ValueError("A replicate region must be a complete original table_selection.")
        inherited = snapshot.get("metadata_confirmations", []) if selection.get("sheet") == snapshot["table_selection"]["sheet"] else []
        confirmations = choice.get("metadata_confirmations", inherited)
        facts = select_table(snapshot["table_snapshot"], selection, confirmations, numeric_contract=numeric_contract)
        column = next((item for item in facts["columns"] if item["index"] == choice["column_index"]), None)
        if column is None or not column["sample"] or column["metadata_conflicts"]:
            raise ValueError("A replicate column needs its exact original sample and unconflicted metadata.")
        # Reuse the existing wide-source metric and unit contract, not XY eligibility.
        metric = re.sub(r"\.\d+$", "", column["header"].strip().casefold())
        if not _is_impact_metric(metric):
            raise ValueError("The selected column must identify the existing replicate metric in original metadata.")
        _validated_impact_unit([column["unit"]])
        bounds = selection["data_start_row"], selection["data_end_row"]
        key = selection["sheet"], column["index"]
        if any(max(bounds[0], start) < min(bounds[1], end) for start, end in occupied.get(key, [])):
            raise ValueError("Overlapping original replicate cells cannot become two groups.")
        occupied.setdefault(key, []).append(bounds)
        frame = read_original_table(source, selection["sheet"], snapshot["file_sha256"])
        present = 0
        for row in range(*bounds):
            value = frame.iat[row, column["index"]]
            if pd.isna(value) or not str(value).strip():
                continue  # Original null position stays in the bound domain.
            try:
                number = float(str(value))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Nonnumeric original replicate at row {row}, column {column['index']}.") from exc
            if not math.isfinite(number):
                raise ValueError(f"Nonfinite original replicate at row {row}, column {column['index']}.")
            present += 1
        if not present:
            raise ValueError("Each selected replicate group needs an original finite observation.")
        label = choice.get("label", column["sample"])
        if not isinstance(label, str) or not label.strip() or len(label) > 160 or label in display_labels.values():
            raise ValueError("Group display labels must be nonempty and distinct; original identities remain in cell evidence.")
        source_id = (source_view_id(str(source.resolve()), selection, [column["index"]])
                     if structured_identity else f"series_{index:03}")
        labels[source_id] = column["sample"] if structured_identity else label
        display_labels[source_id] = label
        references.append(DataSourceReference(source_id, source.name, snapshot["file_sha256"],
            sheet=selection["sheet"], header_row=None, data_start_row=bounds[0], data_end_row=bounds[1],
            cell_evidence=column["cell_evidence"],
            identity=({"version": 1, "source_namespace": str(source.resolve()), "category": column["sample"],
                       "condition": None} if structured_identity else {})))
        mappings.append(DataColumnMapping(source_id, column["index"], "Impact strength", "value",
                                          expected_header=f"column_{column['index']}"))
    if file_sha256(resolve_source_path(source, expected_sha256=snapshot["file_sha256"])) != snapshot["file_sha256"]:
        raise ValueError("Original replicate source changed while binding its columns.")
    contents: dict[str, Any] = {"sources": tuple(references), "columns": tuple(mappings),
                               "sample_labels": labels, "unit_overrides": {"Impact strength": "kJ/m2"}}
    if structured_identity:
        contents["display_labels"] = display_labels

    if not structured_identity:
        proposal = DataMappingProposal(base_request_sha256="0" * 64, **contents, provider="explicit_table_choice")
        used: set[str] = set()
        if any(Path(_safe_output_name(reference, proposal, used=used)).stem != labels[reference.source_id]
               for reference in references):
            raise ValueError("The selected sample label cannot be preserved exactly in the mapped output filename.")
    return contents


def _proposal_contents(snapshot: dict[str, Any], pairs: list[dict[str, Any]], *,
                       structured_identity: bool = False,
                       numeric_contract: MappingNumericContract = MAPPING_NUMERIC_V3) -> dict[str, Any]:
    return pair_proposal_contents(snapshot, pairs,
                                  select_pair=lambda table, pair: _pair_columns(table, pair, numeric_contract=numeric_contract),
                                  structured_identity=structured_identity)


def verify_table_confirmation(proposal: DataMappingProposal, source: Path, *,
                               numeric_contract: MappingNumericContract = MAPPING_NUMERIC_V3) -> None:
    """Rebuild mapping meaning from source and frozen evidence at preview/execution/export."""
    binding = proposal.table_confirmation
    if not binding:
        return  # Historical proposals retain their original signed contract.
    sheets = [binding["selection"]["sheet"],
              *[item.get("table_selection", binding["selection"])["sheet"]
                for item in binding.get("replicates", binding.get("pairs", []))]]
    versions = {item.sha256 for item in proposal.sources}
    if len(versions) != 1:
        raise ValueError("A confirmed original table requires one exact raw byte version.")
    version = next(iter(versions))
    try:
        snapshot = (source_table_snapshot(source, rule_id=binding["rule_id"], sheets=sheets, expected_sha256=version)
                    if "replicates" in binding else
                    table_choice_snapshot(source, binding["rule_id"], sheets=sheets, expected_sha256=version))
    except SourceVersionMismatch as exc:
        raise ValueError("Confirmed table metadata does not reproduce the proposed mapping.") from exc
    if snapshot is None:
        raise ValueError("Confirmed table source is no longer supported.")
    columns = select_table(snapshot, binding["selection"], binding["metadata_confirmations"], numeric_contract=numeric_contract)
    if "replicates" in binding:
        expected = replicate_proposal_contents(columns, binding["replicates"],
                                               structured_identity=bool(proposal.sources[0].identity), numeric_contract=numeric_contract)
    else:
        expected = _proposal_contents(columns, binding["pairs"], structured_identity=bool(proposal.sources[0].identity), numeric_contract=numeric_contract)
    if any(getattr(proposal, key) != value for key, value in expected.items()) or proposal.transformations or proposal.request_patch:
        raise ValueError("Confirmed table metadata does not reproduce the proposed mapping.")
