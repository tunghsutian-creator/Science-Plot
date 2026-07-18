from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core._utils import (
    decode_text,
    file_sha256,
    json_safe,
    safe_filename,
)
from sciplot_core.canvas.assistant_contract import (
    DataColumnMapping,
    DataMappingConfirmation,
    DataMappingProposal,
    DataSourceReference,
    DeclarativeTransformation,
    LegacyDataMappingConfirmation,
)
from sciplot_core.materials_rules import convert_value
from sciplot_core.publication import (
    build_transform_ledger,
    build_transform_step,
)
from sciplot_core.study_model import normalize_study_model

DATA_MAPPING_PREVIEW_KIND = "sciplot_data_mapping_preview"
DATA_MAPPING_PREVIEW_VERSION = 1
DATA_MAPPING_EXECUTION_KIND = "sciplot_data_mapping_execution"
DATA_MAPPING_EXECUTION_VERSION = 1
DATA_MAPPING_APPLICATION_KIND = "sciplot_data_mapping_application"
DATA_MAPPING_APPLICATION_VERSION = 1
DATA_MAPPING_PROPOSAL_FILENAME = "proposal.json"
DATA_MAPPING_CONFIRMATION_FILENAME = "confirmation.json"
DATA_MAPPING_PREVIEW_FILENAME = "preview.json"
DATA_MAPPING_EXECUTION_FILENAME = "execution.json"
DATA_MAPPING_REQUEST_FILENAME = "plot_request.json"
DATA_MAPPING_REQUEST_SEED_FILENAME = "request_seed.json"
DATA_MAPPING_BASE_REQUEST_FILENAME = "base_request.json"
DATA_MAPPING_BASE_LEDGER_FILENAME = "superseded_base_transform_ledger.json"

_SUPPORTED_TABLE_SUFFIXES = frozenset(
    {".csv", ".tsv", ".txt", ".dat", ".tab", ".xlsx", ".xls"}
)
_MISSING_STRINGS = frozenset({"", "na", "n/a", "nan", "null", "none"})
_NUMERIC_COLUMN_ROLES = frozenset({"x", "y", "z", "value", "x_error", "y_error"})
_PRIMARY_NUMERIC_COLUMN_ROLES = frozenset({"x", "y", "z", "value"})
_DECIMAL_COMMA_NUMBER = re.compile(r"^[+-]?(?:\d+(?:,\d*)?|,\d+)(?:[eE][+-]?\d+)?$")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        json_safe(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def data_mapping_proposal_sha256(proposal: DataMappingProposal) -> str:
    return _canonical_sha256(proposal.to_dict())


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def load_data_mapping_proposal(
    value: DataMappingProposal | str | Path | dict[str, Any],
) -> DataMappingProposal:
    if isinstance(value, DataMappingProposal):
        return value
    if isinstance(value, dict):
        return DataMappingProposal.from_dict(value)
    return DataMappingProposal.from_dict(_read_json(Path(value).expanduser().resolve()))


def load_data_mapping_confirmation(
    value: (
        DataMappingConfirmation
        | LegacyDataMappingConfirmation
        | str
        | Path
        | dict[str, Any]
    ),
) -> DataMappingConfirmation | LegacyDataMappingConfirmation:
    if isinstance(value, (DataMappingConfirmation, LegacyDataMappingConfirmation)):
        return value
    payload = (
        value
        if isinstance(value, dict)
        else _read_json(Path(value).expanduser().resolve())
    )
    if payload.get("version") == 1:
        return LegacyDataMappingConfirmation.from_dict(payload)
    return DataMappingConfirmation.from_dict(payload)


def _resolve_source_root(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Data mapping source root not found: {root}")
    if not root.is_dir():
        raise ValueError(
            "DataMappingProposal source paths are relative to a source directory."
        )
    return root


def _resolve_request_path(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Data mapping request not found: {path}")
    return path


def _resolve_source_path(
    root: Path,
    reference: DataSourceReference,
) -> Path:
    candidate = (root / Path(reference.relative_path)).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(
            f"Data source escapes the declared root: {reference.relative_path}"
        )
    if not candidate.is_file():
        raise FileNotFoundError(
            f"Data mapping source not found: {reference.relative_path}"
        )
    if candidate.suffix.casefold() not in _SUPPORTED_TABLE_SUFFIXES:
        raise ValueError(
            f"Unsupported data mapping source format: {candidate.suffix or '<none>'}"
        )
    current_hash = file_sha256(candidate)
    if current_hash != reference.sha256:
        raise ValueError(f"Data mapping source hash changed: {reference.relative_path}")
    return candidate


def verify_data_mapping_sources(
    proposal: DataMappingProposal,
    *,
    source_root: str | Path,
) -> dict[str, Path]:
    root = _resolve_source_root(source_root)
    return {
        reference.source_id: _resolve_source_path(root, reference)
        for reference in proposal.sources
    }


def _verify_request_binding(
    proposal: DataMappingProposal,
    *,
    request_path: str | Path,
) -> Path:
    path = _resolve_request_path(request_path)
    if file_sha256(path) != proposal.base_request_sha256:
        raise ValueError(
            "DataMappingProposal is stale because plot_request.json changed."
        )
    return path


def create_data_mapping_confirmation(
    proposal: DataMappingProposal | str | Path | dict[str, Any],
    *,
    source_root: str | Path,
    request_path: str | Path,
    output_root: str | Path,
    confirmed_by: str,
) -> DataMappingConfirmation:
    resolved = load_data_mapping_proposal(proposal)
    resolved_source_root = _resolve_source_root(source_root)
    resolved_request_path = _verify_request_binding(resolved, request_path=request_path)
    verify_data_mapping_sources(resolved, source_root=resolved_source_root)
    resolved_output_root = Path(output_root).expanduser().resolve()
    return DataMappingConfirmation(
        proposal_id=resolved.proposal_id,
        proposal_sha256=data_mapping_proposal_sha256(resolved),
        base_request_sha256=resolved.base_request_sha256,
        source_hashes=resolved.source_hashes,
        source_root=str(resolved_source_root),
        request_path=str(resolved_request_path),
        output_root=str(resolved_output_root),
        confirmed_by=confirmed_by,
    )


def write_data_mapping_confirmation(
    path: str | Path,
    confirmation: DataMappingConfirmation,
) -> Path:
    destination = Path(path).expanduser().resolve()
    if destination.exists() and destination.is_dir():
        destination = destination / DATA_MAPPING_CONFIRMATION_FILENAME
    elif destination.suffix.casefold() != ".json":
        destination.mkdir(parents=True, exist_ok=True)
        destination = destination / DATA_MAPPING_CONFIRMATION_FILENAME
    _write_json(destination, confirmation.to_dict())
    return destination


def _validate_confirmation(
    proposal: DataMappingProposal,
    confirmation: DataMappingConfirmation | LegacyDataMappingConfirmation,
) -> None:
    if confirmation.proposal_id != proposal.proposal_id:
        raise ValueError("Data mapping confirmation targets another proposal.")
    if confirmation.proposal_sha256 != data_mapping_proposal_sha256(proposal):
        raise ValueError("Data mapping confirmation does not match proposal content.")
    if confirmation.base_request_sha256 != proposal.base_request_sha256:
        raise ValueError("Data mapping confirmation request binding is stale.")
    if confirmation.source_hashes != proposal.source_hashes:
        raise ValueError("Data mapping confirmation source binding is stale.")


def _validate_confirmation_paths(
    confirmation: DataMappingConfirmation,
    *,
    source_root: Path,
    request_path: Path,
    output_root: Path,
) -> None:
    if Path(confirmation.source_root) != source_root.resolve():
        raise ValueError("Data mapping confirmation source-root binding is stale.")
    if Path(confirmation.request_path) != request_path.resolve():
        raise ValueError("Data mapping confirmation request-path binding is stale.")
    if Path(confirmation.output_root) != output_root.resolve():
        raise ValueError("Data mapping confirmation output-root binding is stale.")


@dataclass
class _RawTable:
    source: DataSourceReference
    path: Path
    headers: tuple[str, ...]
    frame: pd.DataFrame


def _detect_delimiter(text: str, reference: DataSourceReference) -> str:
    if reference.delimiter != "auto":
        return reference.delimiter
    lines = [line for line in text.splitlines()[:40] if line.strip()]
    sample = "\n".join(lines)
    counts = {
        "\t": sample.count("\t"),
        ";": sample.count(";"),
        ",": sample.count(","),
        "|": sample.count("|"),
    }
    delimiter, count = max(counts.items(), key=lambda item: (item[1], item[0]))
    if count <= 0:
        raise ValueError(
            f"Could not determine a delimiter for {reference.relative_path}."
        )
    if reference.decimal == "," and counts[";"] > 0:
        return ";"
    return delimiter


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _normalize_missing(value: object) -> object:
    text = _cell_text(value)
    if text.casefold() in _MISSING_STRINGS:
        return pd.NA
    return value


def _normalize_decimal_comma(value: object) -> object:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if _DECIMAL_COMMA_NUMBER.fullmatch(text) is None:
        return value
    return text.replace(",", ".")


def _read_raw_table(
    reference: DataSourceReference,
    path: Path,
) -> _RawTable:
    suffix = path.suffix.casefold()
    if suffix in {".xlsx", ".xls"}:
        sheet = reference.sheet if reference.sheet is not None else 0
        raw = pd.read_excel(path, sheet_name=sheet, header=None, dtype=object)
    else:
        if reference.sheet is not None:
            raise ValueError(
                f"Text source {reference.relative_path} cannot select an Excel sheet."
            )
        text = decode_text(path)
        delimiter = _detect_delimiter(text, reference)
        raw = pd.read_csv(
            StringIO(text),
            sep=delimiter,
            header=None,
            dtype=object,
            keep_default_na=False,
            na_filter=False,
            engine="python",
        )
    if raw.empty:
        raise ValueError(f"Data mapping source is empty: {reference.relative_path}")
    raw = raw.dropna(axis=1, how="all")
    header_row = reference.header_row
    if header_row is None:
        headers = tuple(f"column_{index}" for index in range(raw.shape[1]))
        frame = raw.reset_index(drop=True)
    else:
        if header_row >= raw.shape[0]:
            raise ValueError(
                f"header_row is outside {reference.relative_path}: {header_row}"
            )
        headers = tuple(
            _cell_text(value) or f"column_{index}"
            for index, value in enumerate(raw.iloc[header_row].tolist())
        )
        frame = raw.iloc[header_row + 1 :].reset_index(drop=True)
    frame = frame.map(_normalize_missing)
    return _RawTable(
        source=reference,
        path=path,
        headers=headers,
        frame=frame,
    )


def _column_mappings_for_source(
    proposal: DataMappingProposal,
    source_id: str,
) -> tuple[DataColumnMapping, ...]:
    return tuple(
        mapping for mapping in proposal.columns if mapping.source_id == source_id
    )


def _map_columns(
    raw: _RawTable,
    mappings: tuple[DataColumnMapping, ...],
) -> pd.DataFrame:
    selected: dict[str, pd.Series] = {}
    for mapping in mappings:
        if mapping.source_column_index >= raw.frame.shape[1]:
            raise ValueError(
                f"{raw.source.source_id} column index "
                f"{mapping.source_column_index} is outside the source table."
            )
        actual_header = raw.headers[mapping.source_column_index]
        if (
            mapping.expected_header is not None
            and actual_header != mapping.expected_header
        ):
            raise ValueError(
                f"{raw.source.source_id} column {mapping.source_column_index} "
                f"header changed: expected {mapping.expected_header!r}, "
                f"found {actual_header!r}."
            )
        series = raw.frame.iloc[:, mapping.source_column_index].copy()
        if raw.source.decimal == "," and mapping.role in _NUMERIC_COLUMN_ROLES:
            series = series.map(_normalize_decimal_comma)
        if mapping.required and series.notna().sum() == 0:
            raise ValueError(
                f"Required mapped column {mapping.output_column!r} contains no values."
            )
        selected[mapping.output_column] = series
    return pd.DataFrame(selected)


def _require_columns(
    frame: pd.DataFrame,
    columns: list[str] | tuple[str, ...],
    *,
    operation: str,
) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(
            f"{operation} references unknown columns: {', '.join(missing)}"
        )


def _numeric_series(
    frame: pd.DataFrame,
    column: str,
    *,
    operation: str,
) -> pd.Series:
    _require_columns(frame, [column], operation=operation)
    source = frame[column]
    numeric = pd.to_numeric(source, errors="coerce")
    invalid = source.notna() & numeric.isna()
    if invalid.any():
        rows = [int(index) for index in source.index[invalid].tolist()[:8]]
        raise ValueError(
            f"{operation} found non-numeric values in {column!r} at rows {rows}."
        )
    return numeric.astype(float)


def _deterministic_sort_key(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    invalid = series.notna() & numeric.isna()
    return series if invalid.any() else numeric


def _condition_mask(frame: pd.DataFrame, condition: dict[str, Any]) -> pd.Series:
    column = str(condition["column"])
    _require_columns(frame, [column], operation="exclude where")
    operator = str(condition["operator"])
    series = frame[column]
    if operator == "is_missing":
        return series.isna()
    if operator == "not_missing":
        return series.notna()
    value = condition["value"]
    if operator == "eq":
        return series == value
    if operator == "ne":
        return series != value
    if operator == "in":
        return series.isin(value)
    if operator == "not_in":
        return ~series.isin(value)
    numeric = _numeric_series(frame, column, operation=f"exclude {operator}")
    scalar = float(value)
    if operator == "lt":
        return numeric < scalar
    if operator == "lte":
        return numeric <= scalar
    if operator == "gt":
        return numeric > scalar
    if operator == "gte":
        return numeric >= scalar
    raise ValueError(f"Unsupported exclusion operator: {operator}")


def _apply_transformation(
    frame: pd.DataFrame,
    units: dict[str, str],
    transformation: DeclarativeTransformation,
) -> tuple[pd.DataFrame, dict[str, str], dict[str, Any]]:
    operation = transformation.transformation_type
    parameters = transformation.parameters
    before_rows = int(frame.shape[0])
    before_columns = [str(column) for column in frame.columns]
    result = frame.copy()
    updated_units = dict(units)

    if operation == "rename":
        columns = {str(key): str(value) for key, value in parameters["columns"].items()}
        _require_columns(result, list(columns), operation=operation)
        targets = [columns.get(str(column), str(column)) for column in result.columns]
        if len(set(targets)) != len(targets):
            raise ValueError("rename would create duplicate output columns.")
        result = result.rename(columns=columns)
        updated_units = {
            columns.get(column, column): unit for column, unit in updated_units.items()
        }
    elif operation == "select":
        columns = [str(column) for column in parameters["columns"]]
        _require_columns(result, columns, operation=operation)
        result = result.loc[:, columns]
        updated_units = {
            column: unit for column, unit in updated_units.items() if column in columns
        }
    elif operation == "exclude":
        if "columns" in parameters:
            columns = [str(column) for column in parameters["columns"]]
            _require_columns(result, columns, operation=operation)
            result = result.drop(columns=columns)
            updated_units = {
                column: unit
                for column, unit in updated_units.items()
                if column not in columns
            }
        if "row_indices" in parameters:
            indexes = [int(index) for index in parameters["row_indices"]]
            outside = [index for index in indexes if index >= len(result)]
            if outside:
                raise ValueError(
                    f"exclude row_indices are outside the current table: {outside}"
                )
            result = result.drop(index=result.index[indexes])
        if "where" in parameters:
            masks = [
                _condition_mask(result, dict(condition))
                for condition in parameters["where"]
            ]
            combined = masks[0]
            for mask in masks[1:]:
                combined = (
                    combined | mask
                    if parameters.get("match", "all") == "any"
                    else combined & mask
                )
            result = result.loc[~combined]
        result = result.reset_index(drop=True)
    elif operation == "drop_missing":
        columns = [str(column) for column in parameters.get("columns", result.columns)]
        _require_columns(result, columns, operation=operation)
        result = result.dropna(
            axis=0,
            subset=columns,
            how=str(parameters.get("how") or "any"),
        ).reset_index(drop=True)
    elif operation == "sort":
        columns = [str(column) for column in parameters["by"]]
        _require_columns(result, columns, operation=operation)
        result = result.sort_values(
            by=columns,
            ascending=parameters.get("ascending", True),
            na_position=str(parameters.get("na_position") or "last"),
            kind="mergesort",
            key=_deterministic_sort_key,
        ).reset_index(drop=True)
    elif operation == "unit_convert":
        column = str(parameters["column"])
        output = str(parameters.get("output_column") or column)
        numeric = _numeric_series(result, column, operation=operation)
        converted = numeric.map(
            lambda value: (
                pd.NA
                if pd.isna(value)
                else convert_value(
                    float(value),
                    str(parameters["from_unit"]),
                    str(parameters["to_unit"]),
                )
            )
        )
        if output != column and output in result.columns:
            raise ValueError(f"unit_convert output column already exists: {output!r}")
        result[output] = converted
        updated_units[output] = str(parameters["to_unit"])
    elif operation == "derive_ratio":
        numerator = _numeric_series(
            result, str(parameters["numerator"]), operation=operation
        )
        denominator = _numeric_series(
            result, str(parameters["denominator"]), operation=operation
        )
        output = str(parameters["output"])
        if output in result.columns:
            raise ValueError(f"derive_ratio output column exists: {output!r}")
        zero = denominator == 0.0
        if zero.any() and parameters.get("zero_policy", "error") == "error":
            rows = [int(index) for index in denominator.index[zero].tolist()[:8]]
            raise ValueError(f"derive_ratio denominator is zero at rows {rows}.")
        denominator = denominator.mask(zero)
        result[output] = numerator / denominator * float(parameters.get("scale", 1.0))
    elif operation == "normalize_baseline":
        column = str(parameters["column"])
        output = str(parameters["output"])
        if output in result.columns:
            raise ValueError(f"normalize_baseline output column exists: {output!r}")
        numeric = _numeric_series(result, column, operation=operation)
        finite = numeric[numeric.map(math.isfinite)]
        if finite.empty:
            raise ValueError("normalize_baseline has no finite values.")
        method = str(parameters.get("method") or "first_finite")
        if method == "first_finite":
            baseline = float(finite.iloc[0])
        elif method == "last_finite":
            baseline = float(finite.iloc[-1])
        elif method == "max_abs":
            baseline = float(finite.abs().max())
        elif method == "mean_first_n":
            baseline = float(finite.iloc[: int(parameters["n"])].mean())
        else:
            baseline = float(parameters["value"])
        if not math.isfinite(baseline) or baseline == 0.0:
            raise ValueError(
                "normalize_baseline resolved a non-finite or zero baseline."
            )
        result[output] = numeric / baseline
        updated_units[output] = "1"
    elif operation == "aggregate_replicates":
        group_by = [str(column) for column in parameters["group_by"]]
        value_columns = [str(column) for column in parameters["value_columns"]]
        _require_columns(result, [*group_by, *value_columns], operation=operation)
        for column in value_columns:
            result[column] = _numeric_series(result, column, operation=operation)
        grouped = result.groupby(group_by, dropna=False, sort=False)
        method = str(parameters.get("method") or "mean")
        if method == "mean":
            result = grouped[value_columns].mean().reset_index()
        else:
            result = grouped[value_columns].median().reset_index()
        if parameters.get("include_count", True):
            count_column = str(parameters.get("count_column") or "replicate_count")
            if count_column in result.columns:
                raise ValueError(
                    f"aggregate count column already exists: {count_column!r}"
                )
            counts = grouped.size().reset_index(name=count_column)
            result = result.merge(
                counts,
                on=group_by,
                how="left",
                validate="one_to_one",
            )
        updated_units = {
            column: unit
            for column, unit in updated_units.items()
            if column in result.columns
        }
    else:
        raise ValueError(f"Unsupported declarative transformation: {operation}")

    return (
        result,
        updated_units,
        {
            "transformation_id": transformation.transformation_id,
            "transformation_type": operation,
            "source_ids": list(transformation.source_ids),
            "parameters": json_safe(parameters),
            "rows_before": before_rows,
            "rows_after": int(result.shape[0]),
            "columns_before": before_columns,
            "columns_after": [str(column) for column in result.columns],
        },
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


def _safe_output_name(
    reference: DataSourceReference,
    proposal: DataMappingProposal,
    *,
    used: set[str],
) -> str:
    label = (
        proposal.sample_labels.get(reference.source_id)
        or Path(reference.relative_path).stem
        or reference.source_id
    )
    candidate = safe_filename(f"{label}.csv")
    candidate_key = _filename_collision_key(candidate)
    if candidate_key not in used:
        used.add(candidate_key)
        return candidate
    stem = Path(candidate).stem
    fallback = safe_filename(f"{stem}__{reference.source_id}.csv")
    index = 2
    while _filename_collision_key(fallback) in used:
        fallback = safe_filename(f"{stem}__{reference.source_id}_{index}.csv")
        index += 1
    used.add(_filename_collision_key(fallback))
    return fallback


def _filename_collision_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _write_mapped_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(
        path,
        index=False,
        encoding="utf-8",
        lineterminator="\n",
        float_format="%.15g",
    )


def _mapped_csv_sha256(frame: pd.DataFrame) -> str:
    text = frame.to_csv(
        None,
        index=False,
        lineterminator="\n",
        float_format="%.15g",
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rebase_paths(value: Any, *, source: Path, target: Path) -> Any:
    if isinstance(value, dict):
        return {
            key: _rebase_paths(item, source=source, target=target)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rebase_paths(item, source=source, target=target) for item in value]
    if isinstance(value, str):
        prefix = str(source)
        if value == prefix:
            return str(target)
        if value.startswith(prefix + os.sep):
            return str(target) + value[len(prefix) :]
    return value


def _stable_id(prefix: str, value: str, used: set[str]) -> str:
    token = re.sub(r"[^0-9A-Za-z]+", "_", str(value).strip().casefold()).strip("_")
    base = f"{prefix}_{token or 'item'}"
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}_{index}"
        index += 1
    used.add(candidate)
    return candidate


def _rebind_study_model(
    request: dict[str, Any],
    proposal: DataMappingProposal,
    *,
    source_root: Path,
) -> dict[str, Any] | None:
    existing = request.get("study_model")
    if not isinstance(existing, dict):
        return None
    model = normalize_study_model(existing)
    replicate_by_hash: dict[str, tuple[str, dict[str, Any]]] = {}
    for sample in model.get("samples", []):
        if not isinstance(sample, dict):
            continue
        sample_id = str(sample.get("id") or "")
        for replicate in sample.get("replicates", []):
            if not isinstance(replicate, dict):
                continue
            source_file = (
                replicate.get("source_file")
                if isinstance(replicate.get("source_file"), dict)
                else {}
            )
            digest = str(source_file.get("sha256") or "")
            if digest:
                replicate_by_hash[digest] = (
                    sample_id,
                    deepcopy(replicate),
                )

    grouped: dict[str, list[tuple[str | None, dict[str, Any]]]] = {}
    group_order: list[str] = []
    for reference in proposal.sources:
        label = (
            proposal.sample_labels.get(reference.source_id)
            or Path(reference.relative_path).stem
            or reference.source_id
        )
        if label not in grouped:
            grouped[label] = []
            group_order.append(label)
        matched = replicate_by_hash.get(reference.sha256)
        if matched is not None:
            grouped[label].append(matched)
            continue
        source_path = source_root / reference.relative_path
        grouped[label].append(
            (
                None,
                {
                    "id": "",
                    "name": source_path.stem,
                    "order": 0,
                    "source_file": {
                        "original_name": source_path.name,
                        "raw_path": str(source_path),
                        "source_path": str(source_path),
                        "size_bytes": source_path.stat().st_size,
                        "sha256": reference.sha256,
                    },
                },
            )
        )

    used_sample_ids: set[str] = set()
    used_replicate_ids: set[str] = set()
    old_to_new_sample: dict[str, str] = {}
    samples: list[dict[str, Any]] = []
    for order, label in enumerate(group_order, start=1):
        members = grouped[label]
        old_ids = [old_id for old_id, _replicate in members if old_id]
        if len(set(old_ids)) == 1:
            candidate = old_ids[0]
            sample_id = (
                candidate
                if candidate and candidate not in used_sample_ids
                else _stable_id("sample", label, used_sample_ids)
            )
            used_sample_ids.add(sample_id)
        else:
            sample_id = _stable_id("sample", label, used_sample_ids)
        for old_id in old_ids:
            old_to_new_sample[old_id] = sample_id
        replicates: list[dict[str, Any]] = []
        for replicate_order, (_old_id, replicate) in enumerate(members, start=1):
            item = deepcopy(replicate)
            replicate_id = str(item.get("id") or "")
            if not replicate_id or replicate_id in used_replicate_ids:
                replicate_id = _stable_id(
                    f"{sample_id}_replicate",
                    str(item.get("name") or replicate_order),
                    used_replicate_ids,
                )
            else:
                used_replicate_ids.add(replicate_id)
            item["id"] = replicate_id
            item["order"] = replicate_order
            replicates.append(item)
        samples.append(
            {
                "id": sample_id,
                "name": label,
                "order": order,
                "replicate_mode": str(
                    proposal.request_patch.get("replicate_mode")
                    or model.get("replicate_policy", {}).get("mode")
                    or "mean"
                ),
                "replicates": replicates,
            }
        )

    rebound = deepcopy(model)
    rebound["samples"] = samples
    rebound["sample_order"] = [sample["name"] for sample in samples]
    if "replicate_mode" in proposal.request_patch:
        rebound.setdefault("replicate_policy", {})["mode"] = proposal.request_patch[
            "replicate_mode"
        ]
    valid_source_refs = {
        str(replicate.get("id"))
        for sample in samples
        for replicate in sample.get("replicates", [])
        if isinstance(replicate, dict) and replicate.get("id")
    }
    valid_sample_refs = {str(sample["id"]) for sample in samples}
    for figure in rebound.get("figure_queue", []):
        if not isinstance(figure, dict):
            continue
        evidence = (
            figure.get("evidence_contract")
            if isinstance(figure.get("evidence_contract"), dict)
            else {}
        )
        old_source_refs = [
            str(item) for item in evidence.get("source_refs", []) if str(item)
        ]
        old_sample_refs = [
            str(item) for item in evidence.get("sample_refs", []) if str(item)
        ]
        evidence["source_refs"] = [
            item for item in old_source_refs if item in valid_source_refs
        ]
        translated_samples = [
            old_to_new_sample.get(item, item) for item in old_sample_refs
        ]
        evidence["sample_refs"] = list(
            dict.fromkeys(
                item for item in translated_samples if item in valid_sample_refs
            )
        )
        evidence["confirmation_status"] = (
            "confirmed_mapping"
            if evidence["source_refs"] or evidence["sample_refs"]
            else "pending"
        )
        figure["evidence_contract"] = evidence
    rebound["data_mapping"] = {
        "proposal_id": proposal.proposal_id,
        "provider": proposal.provider,
        "source_hashes": proposal.source_hashes,
        "raw_sources_preserved": True,
    }
    return normalize_study_model(rebound)


def _candidate_request(
    base_request: dict[str, Any],
    proposal: DataMappingProposal,
    *,
    source_root: Path,
    execution_path: Path,
    output_root: Path,
    transform_ledger: dict[str, Any],
    output_labels: list[str],
    superseded_ledger_path: Path | None,
) -> dict[str, Any]:
    request = deepcopy(base_request)
    request.update(deepcopy(proposal.request_patch))
    request["data_mapping_execution"] = str(execution_path)
    request["data_mapping_proposal_id"] = proposal.proposal_id
    request["output"] = str(output_root / "run")
    request["transform_ledger"] = deepcopy(transform_ledger)
    if superseded_ledger_path is not None:
        request["data_mapping_superseded_transform_ledger"] = str(
            superseded_ledger_path
        )
    if output_labels and "series_order" not in proposal.request_patch:
        request["series_order"] = list(output_labels)
    series_order = request.get("series_order")
    if isinstance(series_order, list):
        render_options = (
            deepcopy(request.get("render_options"))
            if isinstance(request.get("render_options"), dict)
            else {}
        )
        if "series_order" in render_options:
            render_options["series_order"] = list(series_order)
        if "series_include" in render_options:
            render_options["series_include"] = list(series_order)
        if render_options:
            request["render_options"] = render_options
    rebound = _rebind_study_model(request, proposal, source_root=source_root)
    if rebound is not None:
        request["study_model"] = rebound
    notes = (
        list(request.get("review_notes"))
        if isinstance(request.get("review_notes"), list)
        else []
    )
    note = (
        f"Confirmed DataMappingProposal {proposal.proposal_id} "
        f"from {proposal.provider}; raw input remains immutable."
    )
    if note not in notes:
        notes.append(note)
    request["review_notes"] = notes
    return request


def _validate_existing_execution(
    execution_path: Path,
    *,
    proposal: DataMappingProposal,
    confirmation: DataMappingConfirmation,
    request_path: Path,
) -> dict[str, Any]:
    manifest = load_data_mapping_execution(execution_path)
    if manifest.get("proposal_sha256") != data_mapping_proposal_sha256(proposal):
        raise ValueError(
            "Existing data mapping output belongs to different proposal content."
        )
    if manifest.get("confirmation_id") != confirmation.confirmation_id:
        raise ValueError(
            "Existing data mapping output uses a different confirmation receipt."
        )
    if file_sha256(request_path) != proposal.base_request_sha256:
        raise ValueError(
            "Existing data mapping output cannot be reused after request changes."
        )
    manifest["idempotent_reuse"] = True
    return manifest


def _mapping_step_parameters(
    proposal: DataMappingProposal,
    confirmation: DataMappingConfirmation | LegacyDataMappingConfirmation,
) -> dict[str, Any]:
    return {
        "proposal_id": proposal.proposal_id,
        "proposal_sha256": data_mapping_proposal_sha256(proposal),
        "provider": proposal.provider,
        "confirmation_id": confirmation.confirmation_id,
        "confirmed_by": confirmation.confirmed_by,
        "source_hashes": proposal.source_hashes,
        "column_mappings": [mapping.to_dict() for mapping in proposal.columns],
        "transformations": [
            transformation.to_dict() for transformation in proposal.transformations
        ],
        "request_patch": proposal.request_patch,
        "raw_sources_preserved": True,
        "silent_omission_allowed": False,
    }


def execute_data_mapping_proposal(
    proposal: DataMappingProposal | str | Path | dict[str, Any],
    confirmation: (
        DataMappingConfirmation
        | LegacyDataMappingConfirmation
        | str
        | Path
        | dict[str, Any]
    ),
    *,
    source_root: str | Path,
    request_path: str | Path,
    output_root: str | Path,
) -> dict[str, Any]:
    resolved = load_data_mapping_proposal(proposal)
    receipt = load_data_mapping_confirmation(confirmation)
    _validate_confirmation(resolved, receipt)
    if isinstance(receipt, LegacyDataMappingConfirmation):
        raise ValueError(
            "DataMappingConfirmation v1 is inspectable only; explicitly "
            "reconfirm the normalized source, request, and output paths before execution."
        )
    root = _resolve_source_root(source_root)
    request_file = _verify_request_binding(resolved, request_path=request_path)
    mapping_root = Path(output_root).expanduser().resolve()
    _validate_confirmation_paths(
        receipt,
        source_root=root,
        request_path=request_file,
        output_root=mapping_root,
    )
    base_request = _read_json(request_file)
    preview = preview_data_mapping_proposal(
        resolved,
        source_root=root,
        request_path=request_file,
    )
    sources, frames, units, events, _headers = _prepare_mapping_frames(
        resolved, source_root=root
    )
    mapping_root.mkdir(parents=True, exist_ok=True)
    final_root = mapping_root / resolved.proposal_id
    final_execution = final_root / DATA_MAPPING_EXECUTION_FILENAME
    if final_root.exists():
        return _validate_existing_execution(
            final_execution,
            proposal=resolved,
            confirmation=receipt,
            request_path=request_file,
        )

    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{resolved.proposal_id}.tmp-",
            dir=mapping_root,
        )
    )
    raw_hashes_before = {
        source_id: file_sha256(path) for source_id, path in sources.items()
    }
    try:
        data_dir = temporary / "data"
        used_names: set[str] = set()
        outputs: list[dict[str, Any]] = []
        output_labels: list[str] = []
        output_paths: list[Path] = []
        for reference in resolved.sources:
            filename = _safe_output_name(reference, resolved, used=used_names)
            destination = data_dir / filename
            frame = frames[reference.source_id]
            _write_mapped_csv(destination, frame)
            output_paths.append(destination)
            output_labels.append(destination.stem)
            outputs.append(
                {
                    "source_id": reference.source_id,
                    "source_relative_path": reference.relative_path,
                    "source_sha256": reference.sha256,
                    "path": str(destination),
                    "sha256": file_sha256(destination),
                    "rows": int(frame.shape[0]),
                    "columns": [str(column) for column in frame.columns],
                    "units": dict(units[reference.source_id]),
                    "sample_label": resolved.sample_labels.get(reference.source_id),
                    "transformations": events[reference.source_id],
                }
            )

        if not output_paths:
            raise ValueError("Data mapping produced no output tables.")
        effective_input = output_paths[0] if len(output_paths) == 1 else data_dir
        proposal_hash = data_mapping_proposal_sha256(resolved)
        step = build_transform_step(
            step_id=f"data_mapping_{resolved.proposal_id}",
            operation="execute_confirmed_data_mapping_proposal",
            input_path=root,
            output_path=output_paths[0],
            additional_outputs=output_paths[1:],
            implementation_ref=(
                "sciplot_core.data_mapping.execute_data_mapping_proposal"
            ),
            parameters=_mapping_step_parameters(resolved, receipt),
        )
        final_step = _rebase_paths(step, source=temporary, target=final_root)
        study_model = (
            base_request.get("study_model")
            if isinstance(base_request.get("study_model"), dict)
            else {
                "kind": "sciplot_study_model",
                "version": 2,
                "samples": [],
                "figure_queue": [],
            }
        )
        base_transform_ledger = (
            deepcopy(base_request.get("transform_ledger"))
            if isinstance(base_request.get("transform_ledger"), dict)
            else None
        )
        ledger = build_transform_ledger(
            normalize_study_model(study_model),
            request=base_request,
            input_path=root,
            steps=[final_step],
            existing=None,
        )
        final_execution_path = final_root / DATA_MAPPING_EXECUTION_FILENAME
        superseded_ledger_path = (
            final_root / DATA_MAPPING_BASE_LEDGER_FILENAME
            if base_transform_ledger is not None
            else None
        )
        candidate = _candidate_request(
            base_request,
            resolved,
            source_root=root,
            execution_path=final_execution_path,
            output_root=final_root,
            transform_ledger=ledger,
            output_labels=output_labels,
            superseded_ledger_path=superseded_ledger_path,
        )
        proposal_path = temporary / DATA_MAPPING_PROPOSAL_FILENAME
        confirmation_path = temporary / DATA_MAPPING_CONFIRMATION_FILENAME
        preview_path = temporary / DATA_MAPPING_PREVIEW_FILENAME
        request_candidate_path = temporary / DATA_MAPPING_REQUEST_FILENAME
        request_seed_path = temporary / DATA_MAPPING_REQUEST_SEED_FILENAME
        base_request_path = temporary / DATA_MAPPING_BASE_REQUEST_FILENAME
        ledger_path = temporary / "transform_ledger.json"
        base_ledger_path = temporary / DATA_MAPPING_BASE_LEDGER_FILENAME
        base_request_path.write_bytes(request_file.read_bytes())
        if file_sha256(base_request_path) != resolved.base_request_sha256:
            raise RuntimeError(
                "The transaction base-request snapshot does not match "
                "the confirmed request hash."
            )
        _write_json(proposal_path, resolved.to_dict())
        _write_json(confirmation_path, receipt.to_dict())
        _write_json(preview_path, preview)
        _write_json(ledger_path, ledger)
        if base_transform_ledger is not None:
            _write_json(base_ledger_path, base_transform_ledger)
        _write_json(request_seed_path, candidate)
        _write_json(request_candidate_path, candidate)

        rebased_outputs = _rebase_paths(outputs, source=temporary, target=final_root)
        raw_hashes_after = {
            source_id: file_sha256(path) for source_id, path in sources.items()
        }
        if raw_hashes_after != raw_hashes_before:
            raise RuntimeError("Raw source hash changed during data mapping execution.")
        manifest = {
            "kind": DATA_MAPPING_EXECUTION_KIND,
            "version": DATA_MAPPING_EXECUTION_VERSION,
            "status": "passed",
            "state": "ready",
            "ready_to_use": True,
            "created_at": _now(),
            "proposal_id": resolved.proposal_id,
            "proposal_sha256": proposal_hash,
            "provider": resolved.provider,
            "confirmation_id": receipt.confirmation_id,
            "confirmed_by": receipt.confirmed_by,
            "confirmed_at": receipt.confirmed_at,
            "base_request": str(request_file),
            "base_request_sha256": resolved.base_request_sha256,
            "base_request_snapshot": str(
                final_root / DATA_MAPPING_BASE_REQUEST_FILENAME
            ),
            "base_request_snapshot_sha256": file_sha256(base_request_path),
            "source_root": str(root),
            "source_hashes": resolved.source_hashes,
            "raw_hashes_before": raw_hashes_before,
            "raw_hashes_after": raw_hashes_after,
            "raw_inputs_unchanged": True,
            "output_root": str(final_root),
            "data_dir": str(final_root / "data"),
            "effective_input": _rebase_paths(
                str(effective_input), source=temporary, target=final_root
            ),
            "outputs": rebased_outputs,
            "proposal": str(final_root / DATA_MAPPING_PROPOSAL_FILENAME),
            "confirmation": str(final_root / DATA_MAPPING_CONFIRMATION_FILENAME),
            "preview": str(final_root / DATA_MAPPING_PREVIEW_FILENAME),
            "request_candidate": str(final_root / DATA_MAPPING_REQUEST_FILENAME),
            "request_candidate_initial_sha256": file_sha256(request_candidate_path),
            "request_seed": str(final_root / DATA_MAPPING_REQUEST_SEED_FILENAME),
            "request_seed_sha256": file_sha256(request_seed_path),
            "transform_ledger": str(final_root / "transform_ledger.json"),
            "transform_ledger_sha256": file_sha256(ledger_path),
            "superseded_base_transform_ledger": (
                str(final_root / DATA_MAPPING_BASE_LEDGER_FILENAME)
                if base_transform_ledger is not None
                else None
            ),
            "superseded_base_transform_ledger_sha256": (
                file_sha256(base_ledger_path)
                if base_transform_ledger is not None
                else None
            ),
            "transform_steps": [final_step],
            "request_patch": json_safe(resolved.request_patch),
            "limitations": [
                "The mapped request is a candidate and does not overwrite the current project request or exact-current VSZ.",
                "Any prior transform ledger is archived as superseded because this candidate starts a new derivation from the proposal's explicit source hashes.",
                "Visual regeneration remains an explicit user action.",
            ],
        }
        _write_json(temporary / DATA_MAPPING_EXECUTION_FILENAME, manifest)
        os.replace(temporary, final_root)
        return load_data_mapping_execution(final_execution_path)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def load_data_mapping_execution(
    path_or_dir: str | Path,
    *,
    verify: bool = True,
) -> dict[str, Any]:
    path = Path(path_or_dir).expanduser().resolve()
    if path.is_dir():
        path = path / DATA_MAPPING_EXECUTION_FILENAME
    payload = _read_json(path)
    if payload.get("kind") != DATA_MAPPING_EXECUTION_KIND:
        raise ValueError("Not a SciPlot data mapping execution manifest.")
    execution_version = payload.get("version")
    if (
        type(execution_version) is not int
        or execution_version != DATA_MAPPING_EXECUTION_VERSION
    ):
        raise ValueError(
            f"Unsupported data mapping execution version: {execution_version!r}"
        )
    if payload.get("status") != "passed":
        raise ValueError("Data mapping execution is not in passed state.")
    if not verify:
        return payload
    execution_root = path.parent.resolve()
    proposal_path = Path(str(payload.get("proposal") or "")).expanduser()
    confirmation_path = Path(str(payload.get("confirmation") or "")).expanduser()
    expected_paths = {
        "proposal": execution_root / DATA_MAPPING_PROPOSAL_FILENAME,
        "confirmation": execution_root / DATA_MAPPING_CONFIRMATION_FILENAME,
        "preview": execution_root / DATA_MAPPING_PREVIEW_FILENAME,
        "request_candidate": execution_root / DATA_MAPPING_REQUEST_FILENAME,
        "request_seed": execution_root / DATA_MAPPING_REQUEST_SEED_FILENAME,
        "base_request_snapshot": (execution_root / DATA_MAPPING_BASE_REQUEST_FILENAME),
        "transform_ledger": execution_root / "transform_ledger.json",
    }
    for field, expected_path in expected_paths.items():
        recorded = Path(str(payload.get(field) or "")).expanduser().resolve()
        if recorded != expected_path.resolve():
            raise ValueError(f"Data mapping execution {field} path is not canonical.")
        if not expected_path.is_file():
            raise FileNotFoundError(
                f"Data mapping execution {field} is missing: {expected_path}"
            )
    if Path(str(payload.get("output_root") or "")).expanduser().resolve() != (
        execution_root
    ):
        raise ValueError("Data mapping execution output_root is inconsistent.")
    proposal = load_data_mapping_proposal(proposal_path)
    confirmation = load_data_mapping_confirmation(confirmation_path)
    _validate_confirmation(proposal, confirmation)
    legacy_confirmation = isinstance(confirmation, LegacyDataMappingConfirmation)
    manifest_source_root = (
        Path(str(payload.get("source_root") or "")).expanduser().resolve()
    )
    manifest_request_path = (
        Path(str(payload.get("base_request") or "")).expanduser().resolve()
    )
    if not legacy_confirmation:
        _validate_confirmation_paths(
            confirmation,
            source_root=manifest_source_root,
            request_path=manifest_request_path,
            output_root=execution_root.parent,
        )
        expected_execution_root = (
            Path(confirmation.output_root) / proposal.proposal_id
        ).resolve()
        if execution_root != expected_execution_root:
            raise ValueError(
                "Data mapping execution path does not match the confirmed output root."
            )
    if data_mapping_proposal_sha256(proposal) != payload.get("proposal_sha256"):
        raise ValueError("Data mapping execution proposal hash mismatch.")
    if confirmation.confirmation_id != payload.get("confirmation_id"):
        raise ValueError("Data mapping execution confirmation mismatch.")
    if payload.get("confirmed_by") != confirmation.confirmed_by:
        raise ValueError("Data mapping execution confirmation operator mismatch.")
    if payload.get("confirmed_at") != confirmation.confirmed_at:
        raise ValueError("Data mapping execution confirmation timestamp mismatch.")
    if payload.get("provider") != proposal.provider:
        raise ValueError("Data mapping execution provider mismatch.")
    if payload.get("base_request_sha256") != proposal.base_request_sha256:
        raise ValueError("Data mapping execution request binding mismatch.")
    base_request_snapshot = Path(
        str(payload.get("base_request_snapshot") or "")
    ).expanduser()
    if (
        file_sha256(base_request_snapshot) != proposal.base_request_sha256
        or payload.get("base_request_snapshot_sha256") != proposal.base_request_sha256
    ):
        raise ValueError("Data mapping execution base-request snapshot hash mismatch.")
    base_request_payload = _read_json(base_request_snapshot)
    if payload.get("source_hashes") != proposal.source_hashes:
        raise ValueError("Data mapping execution source binding mismatch.")
    if payload.get("request_patch") != json_safe(proposal.request_patch):
        raise ValueError("Data mapping execution request patch mismatch.")
    source_root = _resolve_source_root(str(payload.get("source_root") or ""))
    sources, frames, units, events, _headers = _prepare_mapping_frames(
        proposal,
        source_root=source_root,
    )
    expected_raw_hashes = {
        source_id: file_sha256(source_path)
        for source_id, source_path in sources.items()
    }
    if (
        payload.get("raw_hashes_before") != expected_raw_hashes
        or payload.get("raw_hashes_after") != expected_raw_hashes
    ):
        raise ValueError("Data mapping execution raw-source proof mismatch.")
    output_records = payload.get("outputs")
    if not isinstance(output_records, list) or len(output_records) != len(
        proposal.sources
    ):
        raise ValueError("Data mapping execution output inventory mismatch.")
    output_by_source: dict[str, dict[str, Any]] = {}
    for output in output_records:
        if not isinstance(output, dict):
            raise ValueError("Data mapping output record must be an object.")
        source_id = str(output.get("source_id") or "")
        if source_id in output_by_source:
            raise ValueError(f"Duplicate mapped output source ID: {source_id!r}")
        output_by_source[source_id] = output
    if set(output_by_source) != {source.source_id for source in proposal.sources}:
        raise ValueError("Data mapping output source IDs do not match proposal.")
    data_dir = execution_root / "data"
    if Path(str(payload.get("data_dir") or "")).expanduser().resolve() != (data_dir):
        raise ValueError("Data mapping execution data_dir is inconsistent.")
    used_names: set[str] = set()
    expected_output_paths: list[Path] = []
    for reference in proposal.sources:
        output = output_by_source[reference.source_id]
        expected_path = data_dir / _safe_output_name(
            reference,
            proposal,
            used=used_names,
        )
        output_path = Path(str(output.get("path") or "")).expanduser()
        if output_path.resolve() != expected_path.resolve():
            raise ValueError(f"Mapped output path changed for {reference.source_id!r}.")
        if not expected_path.is_file():
            raise FileNotFoundError(f"Mapped data output not found: {expected_path}")
        expected_frame = frames[reference.source_id]
        expected_hash = _mapped_csv_sha256(expected_frame)
        if (
            file_sha256(expected_path) != expected_hash
            or output.get("sha256") != expected_hash
        ):
            raise ValueError(f"Mapped data output does not reproduce: {expected_path}")
        expected_record = {
            "source_relative_path": reference.relative_path,
            "source_sha256": reference.sha256,
            "rows": int(expected_frame.shape[0]),
            "columns": [str(column) for column in expected_frame.columns],
            "units": dict(units[reference.source_id]),
            "sample_label": proposal.sample_labels.get(reference.source_id),
            "transformations": events[reference.source_id],
        }
        for field, expected_value in expected_record.items():
            if output.get(field) != expected_value:
                raise ValueError(
                    "Mapped output metadata mismatch for "
                    f"{reference.source_id!r}: {field}."
                )
        expected_output_paths.append(expected_path)
    expected_effective_input = (
        expected_output_paths[0] if len(expected_output_paths) == 1 else data_dir
    )
    if (
        Path(str(payload.get("effective_input") or "")).expanduser().resolve()
        != expected_effective_input.resolve()
    ):
        raise ValueError("Data mapping execution effective_input is inconsistent.")
    seed = Path(str(payload.get("request_seed") or "")).expanduser()
    if not seed.is_file() or file_sha256(seed) != payload.get("request_seed_sha256"):
        raise ValueError("Immutable mapped request seed hash mismatch.")
    seed_payload = _read_json(seed)
    if payload.get("request_candidate_initial_sha256") != payload.get(
        "request_seed_sha256"
    ):
        raise ValueError(
            "Initial mapped request hash no longer matches its immutable seed."
        )
    if seed_payload.get("data_mapping_execution") != str(path):
        raise ValueError("Immutable mapped request seed execution link mismatch.")
    if seed_payload.get("input") != base_request_payload.get("input"):
        raise ValueError("Immutable mapped request seed changed raw input authority.")
    if seed_payload.get("data_mapping_proposal_id") != proposal.proposal_id:
        raise ValueError("Immutable mapped request seed changed proposal identity.")
    if seed_payload.get("output") != str(execution_root / "run"):
        raise ValueError(
            "Immutable mapped request seed changed its isolated output root."
        )
    for key, expected_value in proposal.request_patch.items():
        if seed_payload.get(key) != expected_value:
            raise ValueError(
                f"Immutable mapped request seed changed confirmed field {key!r}."
            )
    ledger = Path(str(payload.get("transform_ledger") or "")).expanduser()
    if not ledger.is_file() or file_sha256(ledger) != payload.get(
        "transform_ledger_sha256"
    ):
        raise ValueError("Active data mapping transform ledger hash mismatch.")
    ledger_payload = _read_json(ledger)
    if (
        ledger_payload.get("steps") != payload.get("transform_steps")
        or seed_payload.get("transform_ledger") != ledger_payload
    ):
        raise ValueError("Active data mapping transform lineage mismatch.")
    transform_steps = payload.get("transform_steps")
    if (
        not isinstance(transform_steps, list)
        or len(transform_steps) != 1
        or not isinstance(transform_steps[0], dict)
    ):
        raise ValueError(
            "Data mapping execution must contain one confirmed mapping step."
        )
    mapping_step = transform_steps[0]
    if (
        mapping_step.get("id") != f"data_mapping_{proposal.proposal_id}"
        or mapping_step.get("operation") != "execute_confirmed_data_mapping_proposal"
        or mapping_step.get("implementation_ref")
        != "sciplot_core.data_mapping.execute_data_mapping_proposal"
        or mapping_step.get("parameters")
        != _mapping_step_parameters(proposal, confirmation)
    ):
        raise ValueError(
            "Active data mapping step no longer matches the confirmed proposal."
        )
    step_inputs = mapping_step.get("input_artifacts")
    if (
        not isinstance(step_inputs, list)
        or len(step_inputs) != 1
        or not isinstance(step_inputs[0], dict)
        or Path(str(step_inputs[0].get("path") or "")).expanduser().resolve()
        != source_root
    ):
        raise ValueError("Active data mapping step changed its confirmed source root.")
    step_outputs = mapping_step.get("output_artifacts")
    if not isinstance(step_outputs, list) or len(step_outputs) != len(
        expected_output_paths
    ):
        raise ValueError("Active data mapping step output inventory mismatch.")
    for artifact, expected_path in zip(
        step_outputs,
        expected_output_paths,
        strict=True,
    ):
        if (
            not isinstance(artifact, dict)
            or Path(str(artifact.get("path") or "")).expanduser().resolve()
            != expected_path
            or artifact.get("sha256") != file_sha256(expected_path)
        ):
            raise ValueError("Active data mapping step output evidence mismatch.")
    if payload.get("raw_inputs_unchanged") is not True:
        raise ValueError(
            "Data mapping execution does not prove raw-input immutability."
        )
    superseded_ledger_value = payload.get("superseded_base_transform_ledger")
    base_transform_ledger = (
        base_request_payload.get("transform_ledger")
        if isinstance(base_request_payload.get("transform_ledger"), dict)
        else None
    )
    if base_transform_ledger is not None:
        superseded_ledger = Path(str(superseded_ledger_value or "")).expanduser()
        expected_superseded = execution_root / DATA_MAPPING_BASE_LEDGER_FILENAME
        if (
            superseded_ledger.resolve() != expected_superseded.resolve()
            or not superseded_ledger.is_file()
            or file_sha256(superseded_ledger)
            != payload.get("superseded_base_transform_ledger_sha256")
            or _read_json(superseded_ledger) != base_transform_ledger
            or seed_payload.get("data_mapping_superseded_transform_ledger")
            != str(expected_superseded)
        ):
            raise ValueError("Superseded base transform ledger hash mismatch.")
    elif (
        superseded_ledger_value is not None
        or payload.get("superseded_base_transform_ledger_sha256") is not None
    ):
        raise ValueError("Data mapping execution invented superseded base lineage.")
    verified = deepcopy(payload)
    verified["confirmation_schema_version"] = 1 if legacy_confirmation else 2
    verified["confirmation_migration_required"] = legacy_confirmation
    verified["handoff_allowed"] = not legacy_confirmation
    if legacy_confirmation:
        verified["ready_to_use"] = False
    return verified


def resolve_data_mapping_request(
    request: dict[str, Any],
    *,
    base_dir: str | Path,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    execution_value = request.get("data_mapping_execution")
    if not isinstance(execution_value, str) or not execution_value.strip():
        return deepcopy(request), None
    execution_path = Path(execution_value).expanduser()
    if not execution_path.is_absolute():
        execution_path = (
            Path(base_dir).expanduser().resolve() / execution_path
        ).resolve()
    execution = load_data_mapping_execution(execution_path)
    if execution.get("handoff_allowed") is not True:
        raise ValueError(
            "Mapped execution uses a path-unbound v1 confirmation; explicit "
            "v2 reconfirmation is required before rendering or handoff."
        )
    seed_payload = _read_json(Path(str(execution["request_seed"])).expanduser())
    if request.get("input") != seed_payload.get("input"):
        raise ValueError(
            "Mapped project raw input no longer matches its immutable request seed."
        )
    if request.get("data_mapping_proposal_id") != execution.get("proposal_id"):
        raise ValueError(
            "Mapped project proposal ID no longer matches its verified execution."
        )
    effective_input = Path(str(execution.get("effective_input") or "")).expanduser()
    if not effective_input.exists():
        raise FileNotFoundError(f"Mapped effective input not found: {effective_input}")
    effective = deepcopy(request)
    effective.update(deepcopy(execution.get("request_patch") or {}))
    original_input = effective.get("input")
    effective["input"] = str(effective_input)
    mapped_outputs = [
        {
            "source_id": str(output.get("source_id") or ""),
            "path": str(output.get("path") or ""),
            "sha256": str(output.get("sha256") or ""),
            "rows": int(output.get("rows") or 0),
            "columns": [str(column) for column in output.get("columns", [])],
            "sample_label": (
                str(output["sample_label"])
                if output.get("sample_label") is not None
                else None
            ),
        }
        for output in execution.get("outputs", [])
        if isinstance(output, dict)
    ]
    expected_labels = list(
        dict.fromkeys(
            str(output.get("sample_label") or "").strip()
            or Path(str(output.get("path") or "")).stem
            for output in mapped_outputs
        )
    )
    application = {
        "kind": DATA_MAPPING_APPLICATION_KIND,
        "version": DATA_MAPPING_APPLICATION_VERSION,
        "status": "validated",
        "execution": str(execution_path),
        "proposal_id": execution["proposal_id"],
        "proposal_sha256": execution["proposal_sha256"],
        "provider": execution["provider"],
        "confirmation_id": execution["confirmation_id"],
        "confirmed_by": execution["confirmed_by"],
        "original_input": str(original_input or ""),
        "effective_input": str(effective_input),
        "source_root": execution["source_root"],
        "source_hashes": deepcopy(execution["source_hashes"]),
        "mapped_outputs": mapped_outputs,
        "expected_sample_labels": expected_labels,
        "expected_series_count_min": len(expected_labels),
        "transform_steps": deepcopy(execution.get("transform_steps") or []),
        "transform_ledger": _read_json(
            Path(str(execution["transform_ledger"])).expanduser()
        ),
        "raw_inputs_preserved": True,
        "outputs_verified": True,
    }
    effective["transform_ledger"] = deepcopy(application["transform_ledger"])
    effective["data_mapping_application"] = deepcopy(application)
    return effective, application


__all__ = [
    "DATA_MAPPING_APPLICATION_KIND",
    "DATA_MAPPING_APPLICATION_VERSION",
    "DATA_MAPPING_BASE_REQUEST_FILENAME",
    "DATA_MAPPING_BASE_LEDGER_FILENAME",
    "DATA_MAPPING_CONFIRMATION_FILENAME",
    "DATA_MAPPING_EXECUTION_FILENAME",
    "DATA_MAPPING_EXECUTION_KIND",
    "DATA_MAPPING_EXECUTION_VERSION",
    "DATA_MAPPING_PREVIEW_FILENAME",
    "DATA_MAPPING_PREVIEW_KIND",
    "DATA_MAPPING_PREVIEW_VERSION",
    "DATA_MAPPING_PROPOSAL_FILENAME",
    "DATA_MAPPING_REQUEST_FILENAME",
    "DATA_MAPPING_REQUEST_SEED_FILENAME",
    "create_data_mapping_confirmation",
    "data_mapping_proposal_sha256",
    "execute_data_mapping_proposal",
    "load_data_mapping_confirmation",
    "load_data_mapping_execution",
    "load_data_mapping_proposal",
    "preview_data_mapping_proposal",
    "resolve_data_mapping_request",
    "verify_data_mapping_sources",
    "write_data_mapping_confirmation",
]
