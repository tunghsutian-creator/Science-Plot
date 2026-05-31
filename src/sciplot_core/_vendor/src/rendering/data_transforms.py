from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from src.rendering.expression_engine import ExpressionError, evaluate_expression, evaluate_variables


class DataTransformError(ValueError):
    """Raised for user-facing typed data transform errors."""


DataTransformPayload = Mapping[str, Any]

_ALLOWED_FUNCTIONS = {
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "exp": np.exp,
    "log": np.log,
    "sqrt": np.sqrt,
    "pow": np.power,
    "abs": np.abs,
    "min": np.minimum,
    "max": np.maximum,
}
_ALLOWED_OPERATORS = {"eq", "ne", "lt", "lte", "gt", "gte", "between"}
_SUPPORTED_KINDS = {
    "derived_column",
    "row_filter",
    "mask_filter",
    "pivot_matrix",
    "sort_rows",
    "select_columns",
    "type_cast",
    "bin_column",
    "aggregate_summary",
    "rolling_window",
}


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _looks_numeric(value: object) -> bool:
    text = _cell_text(value)
    if not text:
        return False
    try:
        numeric = float(text)
    except ValueError:
        return False
    return math.isfinite(numeric)


def _row_numeric_count(frame: pd.DataFrame, row_index: int) -> int:
    if row_index < 0 or row_index >= frame.shape[0]:
        return 0
    return sum(1 for value in frame.iloc[row_index].tolist() if _looks_numeric(value))


def _infer_data_start(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    if (
        frame.shape[0] >= 4
        and _row_numeric_count(frame, 3) >= 2
        and (_row_numeric_count(frame, 1) < 2 or _row_numeric_count(frame, 2) < 2)
    ):
        first_rows = frame.iloc[:3]
        non_numeric_headers = sum(
            1
            for value in first_rows.to_numpy().ravel().tolist()
            if _cell_text(value) and not _looks_numeric(value)
        )
        if non_numeric_headers >= 2:
            return 3
    return 1 if frame.shape[0] > 1 else 0


def _headers_for(frame: pd.DataFrame) -> list[str]:
    if frame.empty:
        return []
    headers: list[str] = []
    seen: dict[str, int] = {}
    for index, value in enumerate(frame.iloc[0].tolist()):
        label = _cell_text(value) or f"Column {index + 1}"
        if label in seen:
            seen[label] += 1
            label = f"Column {index + 1}"
        else:
            seen[label] = 1
        headers.append(label)
    return headers


def _series_by_column(frame: pd.DataFrame, *, headers: Sequence[str], data_start: int) -> dict[str, pd.Series]:
    data = frame.iloc[data_start:].reset_index(drop=True)
    columns: dict[str, pd.Series] = {}
    for index, header in enumerate(headers):
        if index >= data.shape[1]:
            continue
        series = data.iloc[:, index]
        columns[header] = series
        columns[f"Column {index + 1}"] = series
    return columns


def _data_frame_for_expression(frame: pd.DataFrame, *, headers: Sequence[str], data_start: int) -> pd.DataFrame:
    data = frame.iloc[data_start:].reset_index(drop=True)
    output = pd.DataFrame()
    for index, header in enumerate(headers):
        if index < data.shape[1]:
            output[header] = data.iloc[:, index].reset_index(drop=True)
    return output


def _rebuild_raw_from_data(
    *,
    header: pd.DataFrame,
    data: pd.DataFrame,
    headers: Sequence[str],
) -> pd.DataFrame:
    rows: list[list[object]] = [list(headers)]
    if header.shape[0] > 1:
        for row_index in range(1, header.shape[0]):
            existing = header.iloc[row_index].tolist()
            rows.append([existing[index] if index < len(existing) else "" for index in range(len(headers))])
    data_rows = data.loc[:, list(headers)].reset_index(drop=True)
    data_rows.columns = range(len(headers))
    return pd.concat([pd.DataFrame(rows), data_rows.reset_index(drop=True)], ignore_index=True)


def _data_view(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    data_start = _infer_data_start(frame)
    headers = _headers_for(frame)
    header = frame.iloc[:data_start].reset_index(drop=True)
    data = _data_frame_for_expression(frame, headers=headers, data_start=data_start)
    return header, data, headers


def _column_series(
    frame: pd.DataFrame,
    *,
    headers: Sequence[str],
    data_start: int,
    column: object,
    transform_label: str,
) -> pd.Series:
    name = str(column or "").strip()
    if not name:
        raise DataTransformError(f"{transform_label}: column must not be empty.")
    columns = _series_by_column(frame, headers=headers, data_start=data_start)
    if name not in columns:
        raise DataTransformError(f"{transform_label}: unknown column `{name}`.")
    return columns[name].reset_index(drop=True)


def _safe_expression_result(
    expression: object,
    *,
    columns: Mapping[str, pd.Series],
    row_count: int,
    transform_label: str,
    variables: Mapping[str, float] | None = None,
) -> pd.Series:
    frame = pd.DataFrame(
        {key: value.reset_index(drop=True) for key, value in columns.items() if not key.startswith("Column ")}
    )
    try:
        result = evaluate_expression(
            str(expression or ""),
            frame=frame,
            variables=variables,
            expect="numeric",
            label=transform_label,
        )
    except ExpressionError as exc:
        message = str(exc).replace("unknown column or variable", "unknown column")
        raise DataTransformError(message) from exc
    if len(result) != row_count:
        raise DataTransformError(f"{transform_label}: expression result length does not match the table.")
    return result.reset_index(drop=True)


def _target_column_index(headers: Sequence[str], target_column: str) -> int | None:
    try:
        return list(headers).index(target_column)
    except ValueError:
        return None


def _apply_derived_column(
    frame: pd.DataFrame,
    transform: DataTransformPayload,
    *,
    index: int,
    variables: Mapping[str, float] | None,
) -> pd.DataFrame:
    label = _transform_label(transform, index)
    target = str(transform.get("target_column") or "").strip()
    if not target:
        raise DataTransformError(f"{label}: target_column must not be empty.")
    data_start = _infer_data_start(frame)
    headers = _headers_for(frame)
    columns = _series_by_column(frame, headers=headers, data_start=data_start)
    row_count = max(0, frame.shape[0] - data_start)
    result = _safe_expression_result(
        transform.get("expression"),
        columns=columns,
        row_count=row_count,
        transform_label=label,
        variables=variables,
    )
    output = frame.copy(deep=True).astype(object)
    existing_index = _target_column_index(headers, target)
    if existing_index is not None:
        output.iloc[data_start:, existing_index] = result.tolist()
        return output
    next_col = output.shape[1]
    output[next_col] = pd.Series([""] * output.shape[0], dtype=object)
    output.iat[0, next_col] = target
    if data_start >= 3 and output.shape[0] > 2:
        output.iat[2, next_col] = target
    output.iloc[data_start:, next_col] = result.tolist()
    return output


def _compare_filter(series: pd.Series, transform: DataTransformPayload, *, label: str) -> pd.Series:
    operator = str(transform.get("operator") or "").strip().lower()
    if operator not in _ALLOWED_OPERATORS:
        allowed = ", ".join(sorted(_ALLOWED_OPERATORS))
        raise DataTransformError(f"{label}: row_filter.operator must be one of {allowed}.")
    if operator in {"eq", "ne"}:
        value = transform.get("value")
        numeric = pd.to_numeric(series, errors="coerce")
        try:
            compare_value = float(str(value))
            if numeric.notna().any():
                mask = numeric == compare_value
            else:
                mask = series.map(_cell_text) == _cell_text(value)
        except ValueError:
            mask = series.map(_cell_text) == _cell_text(value)
        return ~mask if operator == "ne" else mask
    numeric_series = pd.to_numeric(series, errors="coerce")
    if numeric_series.isna().any():
        raise DataTransformError(f"{label}: row_filter column must be numeric for operator `{operator}`.")
    if operator == "between":
        lower = transform.get("lower")
        upper = transform.get("upper")
        if lower is None or upper is None:
            raise DataTransformError(f"{label}: between row_filter requires lower and upper.")
        return (numeric_series >= float(lower)) & (numeric_series <= float(upper))
    value = transform.get("value")
    if value is None:
        raise DataTransformError(f"{label}: row_filter requires value for operator `{operator}`.")
    numeric_value = float(value)
    if operator == "lt":
        return numeric_series < numeric_value
    if operator == "lte":
        return numeric_series <= numeric_value
    if operator == "gt":
        return numeric_series > numeric_value
    return numeric_series >= numeric_value


def _apply_row_filter(frame: pd.DataFrame, transform: DataTransformPayload, *, index: int) -> pd.DataFrame:
    label = _transform_label(transform, index)
    data_start = _infer_data_start(frame)
    headers = _headers_for(frame)
    series = _column_series(
        frame,
        headers=headers,
        data_start=data_start,
        column=transform.get("column"),
        transform_label=label,
    )
    mask = _compare_filter(series, transform, label=label).reset_index(drop=True)
    data = frame.iloc[data_start:].reset_index(drop=True)
    filtered = data.loc[mask.tolist()].reset_index(drop=True)
    if filtered.empty:
        raise DataTransformError(f"{label}: row_filter removed every data row.")
    header = frame.iloc[:data_start].reset_index(drop=True)
    return pd.concat([header, filtered], ignore_index=True)


def _apply_mask_filter(
    frame: pd.DataFrame,
    transform: DataTransformPayload,
    *,
    index: int,
    variables: Mapping[str, float] | None,
) -> pd.DataFrame:
    label = _transform_label(transform, index)
    header, data, _headers = _data_view(frame)
    try:
        mask = evaluate_expression(
            str(transform.get("expression") or ""),
            frame=data,
            variables=variables,
            expect="boolean",
            label=label,
        )
    except ExpressionError as exc:
        raise DataTransformError(str(exc)) from exc
    filtered = data.loc[mask.tolist()].reset_index(drop=True)
    if filtered.empty:
        raise DataTransformError(f"{label}: mask_filter removed every data row.")
    return _rebuild_raw_from_data(header=header, data=filtered, headers=list(data.columns))


def _apply_pivot_matrix(frame: pd.DataFrame, transform: DataTransformPayload, *, index: int) -> pd.DataFrame:
    label = _transform_label(transform, index)
    output_mode = str(transform.get("output_mode") or "xyz_long").strip().lower()
    if output_mode not in {"xyz_long", "matrix"}:
        raise DataTransformError(f"{label}: pivot_matrix.output_mode currently supports `xyz_long` or `matrix`.")
    data_start = _infer_data_start(frame)
    headers = _headers_for(frame)
    x_series = _column_series(
        frame,
        headers=headers,
        data_start=data_start,
        column=transform.get("x_column"),
        transform_label=label,
    )
    y_series = _column_series(
        frame,
        headers=headers,
        data_start=data_start,
        column=transform.get("y_column"),
        transform_label=label,
    )
    z_series = _column_series(
        frame,
        headers=headers,
        data_start=data_start,
        column=transform.get("z_column"),
        transform_label=label,
    )
    data = pd.DataFrame(
        {
            "x": pd.to_numeric(x_series, errors="coerce"),
            "y": pd.to_numeric(y_series, errors="coerce"),
            "z": pd.to_numeric(z_series, errors="coerce"),
        }
    ).dropna(subset=["x", "y", "z"])
    if data.empty:
        raise DataTransformError(f"{label}: invalid pivot roles; X, Y and Z must contain numeric values.")
    duplicate_pairs = data.duplicated(subset=["x", "y"], keep=False)
    if duplicate_pairs.any():
        raise DataTransformError(f"{label}: invalid pivot roles; duplicate X/Y cells are not supported in v1.")
    if output_mode == "matrix":
        matrix = data.pivot(index="y", columns="x", values="z").sort_index(axis=0).sort_index(axis=1)
        rows = [["y/x", *matrix.columns.tolist()]]
        for y_value, row in matrix.iterrows():
            rows.append([y_value, *row.tolist()])
        return pd.DataFrame(rows)
    header_rows = pd.DataFrame(
        [
            ["x", "y", "z"],
            [
                str(transform.get("x_column") or "X"),
                str(transform.get("y_column") or "Y"),
                str(transform.get("z_column") or "Z"),
            ],
            ["", "", ""],
        ]
    )
    data_rows = data.reset_index(drop=True)
    data_rows.columns = [0, 1, 2]
    return pd.concat([header_rows, data_rows], ignore_index=True)


def _list_field(value: object, *, label: str, field: str) -> list[str]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, Sequence):
        items = [str(item) for item in value]
    else:
        raise DataTransformError(f"{label}: {field} must be a list.")
    cleaned = [item.strip() for item in items if item.strip()]
    if not cleaned:
        raise DataTransformError(f"{label}: {field} must not be empty.")
    return cleaned


def _require_columns(data: pd.DataFrame, columns: Sequence[str], *, label: str) -> None:
    missing = [column for column in columns if column not in data.columns]
    if missing:
        raise DataTransformError(f"{label}: unknown column `{missing[0]}`.")


def _apply_type_cast(frame: pd.DataFrame, transform: DataTransformPayload, *, index: int) -> pd.DataFrame:
    label = _transform_label(transform, index)
    header, data, headers = _data_view(frame)
    columns = _list_field(transform.get("columns") or transform.get("column"), label=label, field="columns")
    _require_columns(data, columns, label=label)
    target_type = str(transform.get("target_type") or "number").strip().lower()
    for column in columns:
        if target_type == "number":
            converted = pd.to_numeric(data[column], errors="coerce")
            if converted.isna().any():
                raise DataTransformError(f"{label}: type_cast column `{column}` contains nonnumeric values.")
            data[column] = converted
        elif target_type == "string":
            data[column] = data[column].map(_cell_text)
        else:
            raise DataTransformError(f"{label}: type_cast.target_type must be number or string.")
    return _rebuild_raw_from_data(header=header, data=data, headers=headers)


def _apply_sort_rows(frame: pd.DataFrame, transform: DataTransformPayload, *, index: int) -> pd.DataFrame:
    label = _transform_label(transform, index)
    header, data, headers = _data_view(frame)
    columns = _list_field(transform.get("columns") or transform.get("column"), label=label, field="columns")
    _require_columns(data, columns, label=label)
    ascending = bool(transform.get("ascending", True))
    sorted_data = data.sort_values(by=columns, ascending=ascending, kind="mergesort").reset_index(drop=True)
    return _rebuild_raw_from_data(header=header, data=sorted_data, headers=headers)


def _apply_select_columns(frame: pd.DataFrame, transform: DataTransformPayload, *, index: int) -> pd.DataFrame:
    label = _transform_label(transform, index)
    header, data, _headers = _data_view(frame)
    columns = _list_field(transform.get("columns"), label=label, field="columns")
    _require_columns(data, columns, label=label)
    return _rebuild_raw_from_data(header=header, data=data.loc[:, columns].copy(), headers=columns)


def _apply_bin_column(frame: pd.DataFrame, transform: DataTransformPayload, *, index: int) -> pd.DataFrame:
    label = _transform_label(transform, index)
    header, data, headers = _data_view(frame)
    column = str(transform.get("column") or "").strip()
    target = str(transform.get("target_column") or f"{column}_bin").strip()
    _require_columns(data, [column], label=label)
    try:
        bins = int(transform.get("bins") or 10)
    except (TypeError, ValueError) as exc:
        raise DataTransformError(f"{label}: bins must be an integer.") from exc
    if bins < 1:
        raise DataTransformError(f"{label}: bins must be at least 1.")
    numeric = pd.to_numeric(data[column], errors="coerce")
    if numeric.isna().any():
        raise DataTransformError(f"{label}: bin_column requires numeric column `{column}`.")
    if math.isclose(float(numeric.min()), float(numeric.max())):
        raise DataTransformError(f"{label}: bin_column requires a column with non-zero range.")
    edges = np.linspace(float(numeric.min()), float(numeric.max()), bins + 1)
    labels = [f"{edges[i]:g}-{edges[i + 1]:g}" for i in range(len(edges) - 1)]
    data[target] = pd.cut(numeric, bins=edges, labels=labels, include_lowest=True).astype(str)
    if target not in headers:
        headers = [*headers, target]
    return _rebuild_raw_from_data(header=header, data=data, headers=headers)


def _apply_rolling_window(frame: pd.DataFrame, transform: DataTransformPayload, *, index: int) -> pd.DataFrame:
    label = _transform_label(transform, index)
    header, data, headers = _data_view(frame)
    column = str(transform.get("column") or "").strip()
    target = str(transform.get("target_column") or f"{column}_rolling").strip()
    _require_columns(data, [column], label=label)
    try:
        window = int(transform.get("window") or 3)
    except (TypeError, ValueError) as exc:
        raise DataTransformError(f"{label}: rolling window must be an integer.") from exc
    if window < 1:
        raise DataTransformError(f"{label}: rolling window must be at least 1.")
    method = str(transform.get("method") or "mean").strip().lower()
    numeric = pd.to_numeric(data[column], errors="coerce")
    if numeric.isna().any():
        raise DataTransformError(f"{label}: rolling_window requires numeric column `{column}`.")
    rolling = numeric.rolling(window=window, min_periods=1)
    if method == "mean":
        data[target] = rolling.mean()
    elif method == "median":
        data[target] = rolling.median()
    else:
        raise DataTransformError(f"{label}: rolling_window.method must be mean or median.")
    if target not in headers:
        headers = [*headers, target]
    return _rebuild_raw_from_data(header=header, data=data, headers=headers)


def _apply_aggregate_summary(frame: pd.DataFrame, transform: DataTransformPayload, *, index: int) -> pd.DataFrame:
    label = _transform_label(transform, index)
    _header, data, _headers = _data_view(frame)
    group_by = _list_field(transform.get("group_by"), label=label, field="group_by")
    value_columns = _list_field(transform.get("value_columns"), label=label, field="value_columns")
    _require_columns(data, [*group_by, *value_columns], label=label)
    stats = _list_field(transform.get("statistics") or ["mean"], label=label, field="statistics")
    allowed = {"mean", "sd", "sem", "min", "max", "count"}
    for stat in stats:
        if stat not in allowed:
            raise DataTransformError(f"{label}: aggregate statistic `{stat}` is not supported.")
    rows: list[dict[str, object]] = []
    grouped = data.groupby(group_by, dropna=False, sort=True)
    group_key_names = group_by
    for group_key, group_frame in grouped:
        if not isinstance(group_key, tuple):
            group_key = (group_key,)
        row: dict[str, object] = {name: value for name, value in zip(group_key_names, group_key, strict=True)}
        for value_column in value_columns:
            numeric = pd.to_numeric(group_frame[value_column], errors="coerce")
            if numeric.isna().any():
                raise DataTransformError(f"{label}: aggregate column `{value_column}` must be numeric.")
            if "mean" in stats:
                row[f"{value_column}_mean"] = float(numeric.mean())
            if "sd" in stats:
                row[f"{value_column}_sd"] = float(numeric.std(ddof=1)) if len(numeric) > 1 else 0.0
            if "sem" in stats:
                row[f"{value_column}_sem"] = float(numeric.sem(ddof=1)) if len(numeric) > 1 else 0.0
            if "min" in stats:
                row[f"{value_column}_min"] = float(numeric.min())
            if "max" in stats:
                row[f"{value_column}_max"] = float(numeric.max())
            if "count" in stats:
                row[f"{value_column}_count"] = int(numeric.count())
        rows.append(row)
    output = pd.DataFrame(rows)
    output_rows = [output.columns.tolist(), *output.values.tolist()]
    return pd.DataFrame(output_rows)


def _transform_label(transform: DataTransformPayload, index: int) -> str:
    label = str(transform.get("label") or transform.get("id") or f"transform {index + 1}").strip()
    return f"data_transforms[{index}] {label}"


def normalize_data_transforms_payload(value: object) -> tuple[dict[str, Any], ...] | None:
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise DataTransformError("`data_transforms` must be a list of mappings.")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise DataTransformError(f"`data_transforms[{index}]` must be a mapping.")
        transform = dict(item)
        transform_id = str(transform.get("id") or "").strip()
        if not transform_id:
            raise DataTransformError(f"`data_transforms[{index}].id` must not be empty.")
        if transform_id in seen:
            raise DataTransformError("`data_transforms` ids must be unique.")
        seen.add(transform_id)
        kind = str(transform.get("kind") or "").strip().lower()
        if kind not in _SUPPORTED_KINDS:
            raise DataTransformError(
                f"`data_transforms[{index}].kind` must be one of {', '.join(sorted(_SUPPORTED_KINDS))}."
            )
        transform["id"] = transform_id
        transform["kind"] = kind
        transform["enabled"] = bool(transform.get("enabled", True))
        transform["label"] = str(transform.get("label") or "").strip() or None
        normalized.append(transform)
    return tuple(normalized) if normalized else None


def apply_data_transforms_to_frame(
    frame: pd.DataFrame,
    transforms: object,
    variables: object = None,
) -> pd.DataFrame:
    normalized = normalize_data_transforms_payload(transforms)
    if normalized is None:
        return frame.copy(deep=True)
    try:
        resolved_variables = evaluate_variables(variables, frame=_data_frame_for_expression(
            frame,
            headers=_headers_for(frame),
            data_start=_infer_data_start(frame),
        ))
    except ExpressionError as exc:
        raise DataTransformError(str(exc)) from exc
    output = frame.copy(deep=True).astype(object)
    for index, transform in enumerate(normalized):
        if not transform.get("enabled", True):
            continue
        kind = transform["kind"]
        if kind == "derived_column":
            output = _apply_derived_column(output, transform, index=index, variables=resolved_variables)
        elif kind == "row_filter":
            output = _apply_row_filter(output, transform, index=index)
        elif kind == "mask_filter":
            output = _apply_mask_filter(output, transform, index=index, variables=resolved_variables)
        elif kind == "pivot_matrix":
            output = _apply_pivot_matrix(output, transform, index=index)
        elif kind == "type_cast":
            output = _apply_type_cast(output, transform, index=index)
        elif kind == "sort_rows":
            output = _apply_sort_rows(output, transform, index=index)
        elif kind == "select_columns":
            output = _apply_select_columns(output, transform, index=index)
        elif kind == "bin_column":
            output = _apply_bin_column(output, transform, index=index)
        elif kind == "rolling_window":
            output = _apply_rolling_window(output, transform, index=index)
        elif kind == "aggregate_summary":
            output = _apply_aggregate_summary(output, transform, index=index)
        else:  # pragma: no cover - normalized above
            raise DataTransformError(f"{_transform_label(transform, index)}: unsupported transform kind `{kind}`.")
    return output


__all__ = [
    "DataTransformError",
    "DataTransformPayload",
    "apply_data_transforms_to_frame",
    "normalize_data_transforms_payload",
]
