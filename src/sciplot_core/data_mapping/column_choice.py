"""Expose original paired-curve columns and bind one explicit selection."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core.data_mapping.raw_tables import _read_raw_table
from sciplot_core.data_mapping.output_files import _safe_output_name
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.mapping_contract import (
    DataColumnMapping,
    DataMappingProposal,
    DataSourceReference,
)
from sciplot_core.materials_rules import get_rule
from sciplot_core.materials_rules.models import SemanticRule
from sciplot_core.semantic_sources.paired_curve_table_metadata import (
    axis_match,
    explicit_header_unit,
    looks_like_unit,
)


def _original_text(value: object) -> str:
    return "" if value is None or pd.isna(value) else str(value)


def _finite_numeric_column(values: pd.Series) -> bool:
    numbers = pd.to_numeric(values, errors="coerce")
    return bool(
        len(numbers)
        and numbers.notna().all()
        and all(math.isfinite(float(value)) for value in numbers)
    )


def _columns_for_layout(
    frame: pd.DataFrame, source: Path, rule: SemanticRule, *, three_row: bool
) -> list[dict[str, Any]]:
    data_start = 3 if three_row else 1
    if len(frame) <= data_start:
        return []
    columns = []
    for index in range(frame.shape[1]):
        header = _original_text(frame.iat[0, index])
        unit = (
            _original_text(frame.iat[1, index]).strip()
            if three_row else explicit_header_unit(header)
        )
        sample = _original_text(frame.iat[2, index]) if three_row else source.stem
        numeric = _finite_numeric_column(frame.iloc[data_start:, index])
        eligible = bool(header.strip() and unit and looks_like_unit(unit) and sample.strip() and numeric)
        columns.append({
            "index": index,
            "header": header,
            "unit": unit,
            "sample": sample,
            "output_header": f"{header} ({unit})" if three_row and header.strip() and unit else header,
            "x_eligible": eligible and axis_match(header, (rule.x_axis.canonical_label, *rule.x_axis.aliases)),
            "y_eligible": eligible and axis_match(header, (rule.y_axis.canonical_label, *rule.y_axis.aliases)),
        })
    return columns


def column_choice_snapshot(source: Path, rule_id: str) -> dict[str, Any] | None:
    """Read two bounded text layouts without selecting, rewriting, or executing."""
    source = source.expanduser().resolve()
    if not source.is_file() or source.suffix.casefold() not in {".csv", ".tsv"}:
        return None
    try:
        rule = get_rule(rule_id)
    except ValueError:
        return None
    if rule.fixture_status != "ready" or rule.scientific_source_adapter != "registered_paired_curve":
        return None
    before = file_sha256(source)
    reference = DataSourceReference("source", source.name, before, header_row=None)
    try:
        raw = _read_raw_table(reference, source, preserve_cells=True)
    except (ValueError, OSError, UnicodeError):
        raw = None
    try:
        after = file_sha256(source)
    except OSError as exc:
        raise ValueError("Column-choice source changed while reading.") from exc
    if after != before:
        raise ValueError("Column-choice source changed while reading.")
    if raw is None or not 2 <= raw.frame.shape[1] <= 64:
        return None
    for three_row in (False, True):
        columns = _columns_for_layout(raw.frame, source, rule, three_row=three_row)
        has_pair = any(
            x["x_eligible"] and y["y_eligible"] and x["index"] != y["index"]
            and x["sample"] == y["sample"]
            for x in columns for y in columns
        )
        if has_pair:
            return {
                "kind": "sciplot_column_choice",
                "version": 1,
                "source": str(source),
                "file_sha256": before,
                "rule_id": rule_id,
                "layout": "three_row" if three_row else "single_header",
                "header_row": 2 if three_row else 0,
                "columns": columns,
                "rows": [
                    {"row_index": index, "cells": [_original_text(value) for value in row]}
                    for index, row in enumerate(raw.frame.iloc[:6].itertuples(index=False, name=None))
                ],
            }
    return None


def proposal_for_column_choice(
    snapshot: dict[str, Any], *, x_column: int, y_column: int,
    request_path: Path, proposal_id: str, created_at: str,
) -> DataMappingProposal:
    """Revalidate original evidence and propose exactly the two requested columns."""
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("kind") != "sciplot_column_choice"
        or type(snapshot.get("version")) is not int
        or snapshot["version"] != 1
        or not isinstance(snapshot.get("source"), str)
        or not isinstance(snapshot.get("rule_id"), str)
    ):
        raise ValueError("Invalid column-choice snapshot.")
    if type(x_column) is not int or type(y_column) is not int or x_column == y_column:
        raise ValueError("Column choices must be two distinct original integer indices.")
    source = Path(snapshot["source"])
    fresh = column_choice_snapshot(source, snapshot["rule_id"])
    if fresh is None or fresh != snapshot:
        raise ValueError("Column-choice source or original evidence changed.")
    columns = {column["index"]: column for column in fresh["columns"]}
    if x_column not in columns or y_column not in columns:
        raise ValueError("Column choice is outside the original source table.")
    x, y = columns[x_column], columns[y_column]
    if not x["x_eligible"] or not y["y_eligible"]:
        raise ValueError("Selected columns need explicit axis names, observed units, and finite numeric values.")
    if x["sample"] != y["sample"]:
        raise ValueError("Selected columns belong to different samples.")
    request_hash = file_sha256(request_path)
    proposal = DataMappingProposal(
        base_request_sha256=request_hash,
        sources=(DataSourceReference(
            "source", source.name, fresh["file_sha256"], header_row=fresh["header_row"],
        ),),
        columns=tuple(
            DataColumnMapping(
                source_id="source", source_column_index=column["index"],
                output_column=column["output_header"], role=role,
                expected_header=column["sample"] if fresh["layout"] == "three_row" else column["header"],
            )
            for role, column in (("x", x), ("y", y))
        ),
        provider="explicit_column_choice",
        sample_labels={"source": x["sample"]},
        unit_overrides={column["output_header"]: column["unit"] for column in (x, y)},
        rationale="Use the explicitly selected original columns; preserve their declared units and values.",
        proposal_id=proposal_id,
        created_at=created_at,
    )
    if Path(_safe_output_name(proposal.sources[0], proposal, used=set())).stem != x["sample"]:
        raise ValueError(
            "The selected sample label cannot be preserved exactly by the current "
            "mapped-table filename; choose another supported sample."
        )
    if file_sha256(source) != fresh["file_sha256"] or file_sha256(request_path) != request_hash:
        raise ValueError("Column-choice source or request changed while creating the proposal.")
    return proposal


__all__ = ["column_choice_snapshot", "proposal_for_column_choice"]
