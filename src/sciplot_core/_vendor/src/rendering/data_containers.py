from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from src.rendering.source_table_preview import SourceTablePreview

_CONTAINER_ROLE_ORDER = ("x", "y", "z", "group", "sample", "value", "metric", "label", "series")
_COLUMN_LIFECYCLE_EVENTS = ("data_about_to_change", "data_changed", "mode_changed", "role_changed")


def _serialize(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(cast(Any, value))
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _numeric_values(rows: list[list[Any]] | tuple[tuple[Any, ...], ...], column_index: int) -> list[float]:
    values: list[float] = []
    for row in rows:
        if column_index >= len(row):
            continue
        numeric = _finite_float(row[column_index])
        if numeric is not None:
            values.append(numeric)
    return values


def _role_hints_for_column(column_name: str, role_payload: dict[str, Any]) -> list[str]:
    return [
        role
        for role in _CONTAINER_ROLE_ORDER
        if column_name in {str(value) for value in role_payload.get(role, [])}
    ]


def _unit_from_profile(profile: dict[str, Any] | None) -> str | None:
    if not profile:
        return None
    header_preview = profile.get("header_preview")
    if not isinstance(header_preview, (list, tuple)) or len(header_preview) < 2:
        return None
    unit = header_preview[1]
    return unit.strip() if isinstance(unit, str) and unit.strip() else None


def _statistics_for_rows(headers: list[str], rows: list[list[Any]] | tuple[tuple[Any, ...], ...]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for index, header in enumerate(headers):
        values = _numeric_values(rows, index)
        if not values:
            continue
        array = np.asarray(values, dtype=float)
        output[str(header)] = {
            "count": int(array.size),
            "mean": float(np.mean(array)),
            "std": float(np.std(array, ddof=1)) if array.size > 1 else 0.0,
            "min": float(np.min(array)),
            "max": float(np.max(array)),
        }
    return output


def _column_mode_for_rows(rows: list[list[Any]] | tuple[tuple[Any, ...], ...], column_index: int) -> str:
    observed = [row[column_index] for row in rows if column_index < len(row) and _cell_text(row[column_index])]
    if not observed:
        return "empty"
    numeric_count = sum(1 for value in observed if _finite_float(value) is not None)
    if numeric_count == len(observed):
        return "numeric"
    if numeric_count >= max(2, int(len(observed) * 0.6)):
        return "numeric"
    if numeric_count:
        return "mixed"
    return "text"


def _columns_from_headers(
    headers: list[str],
    *,
    role_payload: dict[str, Any] | None = None,
    profile_payloads: list[dict[str, Any]] | None = None,
    rows: list[list[Any]] | tuple[tuple[Any, ...], ...] = (),
    source_container_id: str = "container",
) -> list[dict[str, Any]]:
    roles = role_payload or {}
    profiles = profile_payloads or []
    columns: list[dict[str, Any]] = []
    for index, name in enumerate(headers):
        profile = profiles[index] if index < len(profiles) else None
        columns.append(
            {
                "id": f"col-{index}",
                "name": str(name),
                "index": index,
                "role_hints": _role_hints_for_column(str(name), roles),
                "mode": _column_mode_for_rows(rows, index),
                "unit": _unit_from_profile(profile),
                "comment": None,
                "format": None,
                "dictionary": [],
                "category": None,
                "missing_policy": "preserve",
                "lineage": {
                    "source_container_id": source_container_id,
                    "source_column_name": str(name),
                    "source_column_index": index,
                },
                "computed_expression": None,
                "readonly": True,
                "lifecycle_events": list(_COLUMN_LIFECYCLE_EVENTS),
                "profile": profile,
            }
        )
    return columns


def source_table_data_containers(
    preview: SourceTablePreview,
    *,
    transform_count: int = 0,
    variable_count: int = 0,
) -> list[dict[str, Any]]:
    role_payload = _serialize(preview.candidate_roles)
    roles = role_payload if isinstance(role_payload, dict) else {}
    profile_payloads = [
        profile
        for profile in (_serialize(item) for item in preview.column_profiles)
        if isinstance(profile, dict)
    ]
    headers = [str(item) for item in preview.column_headers]
    source_container_id = f"source-table:{preview.sheet}"
    rows = [list(row) for row in preview.rows]
    columns = _columns_from_headers(
        headers,
        role_payload=roles,
        profile_payloads=profile_payloads,
        rows=rows,
        source_container_id=source_container_id,
    )
    source = {
        "input_path": str(preview.input_path),
        "sheet": preview.sheet,
        "selected_segment_id": preview.selected_segment_id,
        "encoding": preview.encoding,
        "delimiter": preview.delimiter,
        "offset": int(preview.offset),
        "limit": int(preview.limit),
        "transform_count": transform_count,
        "variable_count": variable_count,
    }
    statistics = _statistics_for_rows(headers, rows)
    containers: list[dict[str, Any]] = [
        {
            "id": source_container_id,
            "kind": "table",
            "label": f"{preview.sheet} table",
            "status": "enabled",
            "readonly": True,
            "row_count": int(preview.total_rows),
            "column_count": int(preview.total_cols),
            "columns": columns,
            "column_ids": [column["id"] for column in columns],
            "source": source,
            "statistics": statistics,
            "data_revision": 1,
            "help": "Readonly table container generated by source preview.",
        }
    ]
    if transform_count:
        containers.append(
            {
                "id": f"transformed-view:{preview.sheet}",
                "kind": "transformed_view",
                "label": f"{preview.sheet} transformed view",
                "status": "enabled",
                "readonly": True,
                "row_count": int(preview.total_rows),
                "column_count": int(preview.total_cols),
                "columns": columns,
                "column_ids": [column["id"] for column in columns],
                "source": source,
                "statistics": statistics,
                "diagnostics": [
                    {
                        "status_code": "transforms_applied",
                        "message": f"Applied {transform_count} typed data transform(s).",
                    }
                ],
                "help": "Readonly transformed view generated by the typed data engine.",
            }
        )
    if roles.get("x") and roles.get("y") and roles.get("z") and preview.total_cols >= 3:
        x_values = sorted(set(_numeric_values(rows, 0)))
        y_values = sorted(set(_numeric_values(rows, 1)))
        grid_slots = max(1, len(x_values) * len(y_values))
        observed_slots = len({(row[0], row[1]) for row in rows if len(row) >= 3})
        containers.append(
            {
                "id": f"matrix:{preview.sheet}",
                "kind": "matrix",
                "label": f"{preview.sheet} scalar field",
                "status": "enabled",
                "readonly": True,
                "row_count": int(preview.total_rows),
                "column_count": int(preview.total_cols),
                "columns": columns,
                "column_ids": [column["id"] for column in columns],
                "source": source,
                "dimensions": {"rows": len(y_values), "columns": len(x_values)},
                "coordinate_vectors": {"x": x_values, "y": y_values},
                "missing_value_policy": "preserve",
                "statistics": statistics,
                "diagnostics": [
                    {
                        "status_code": "matrix_detected",
                        "message": "XYZ scalar-field preview has a contour-ready matrix container.",
                    },
                    {
                        "status_code": "matrix_density",
                        "observed_slots": observed_slots,
                        "expected_slots": grid_slots,
                        "density": observed_slots / grid_slots,
                    },
                ],
                "result_tables": [{"id": f"matrix-points:{preview.sheet}", "columns": headers, "rows": rows}],
                "help": "Matrix container generated from XYZ scalar-field roles.",
            }
        )
    if statistics:
        containers.append(
            {
                "id": f"statistics:{preview.sheet}",
                "kind": "statistics_summary",
                "label": f"{preview.sheet} statistics",
                "status": "enabled",
                "readonly": True,
                "row_count": len(statistics),
                "column_count": 5,
                "columns": [],
                "column_ids": [],
                "source": source,
                "statistics": statistics,
                "result_tables": [{"id": f"statistics-table:{preview.sheet}", "rows": statistics}],
                "help": "Statistics summary generated by the sidecar.",
            }
        )
    return containers


def table_container_from_frame(
    frame: pd.DataFrame,
    *,
    input_path: str | Path,
    sheet: str | int = "Sheet1",
    container_id: str = "table:preview",
    label: str = "Preview Table",
    status: str = "enabled",
    kind: str = "table",
    help_text: str = "Readonly table container.",
) -> dict[str, Any]:
    headers = [str(column) for column in frame.columns]
    rows = frame.replace({np.nan: None}).values.tolist()
    columns = _columns_from_headers(headers, rows=rows, source_container_id=container_id)
    return {
        "id": container_id,
        "kind": kind,
        "label": label,
        "status": status,
        "readonly": True,
        "row_count": int(frame.shape[0]),
        "column_count": int(frame.shape[1]),
        "columns": columns,
        "column_ids": [column["id"] for column in columns],
        "source": {"input_path": str(input_path), "sheet": sheet, "offset": 0, "limit": min(200, len(rows))},
        "statistics": _statistics_for_rows(headers, rows),
        "result_tables": [{"id": f"{container_id}:rows", "columns": headers, "rows": rows[:200]}],
        "data_revision": 1,
        "help": help_text,
    }


def matrix_container_from_array(
    values: np.ndarray,
    *,
    input_path: str | Path,
    sheet: str | int = "raw",
    container_id: str = "matrix:preview",
    label: str = "Matrix Preview",
    status: str = "enabled",
) -> dict[str, Any]:
    array = np.asarray(values)
    if array.ndim != 2:
        raise ValueError("Matrix container requires a 2D array.")
    rows, columns = array.shape
    frame = pd.DataFrame(array)
    container = table_container_from_frame(
        frame,
        input_path=input_path,
        sheet=sheet,
        container_id=container_id,
        label=label,
        status=status,
        kind="matrix",
        help_text="Matrix container generated by import preview.",
    )
    container["dimensions"] = {"rows": int(rows), "columns": int(columns)}
    container["coordinate_vectors"] = {"x": list(range(columns)), "y": list(range(rows))}
    container["missing_value_policy"] = "preserve"
    return container


def fit_result_container(
    *,
    input_path: str | Path,
    sheet: str | int,
    series_id: str,
    series_label: str,
    x_label: str | None,
    y_label: str | None,
    row_count: int,
    offset: int,
    limit: int,
    r_squared: float,
    rmse: float,
    point_count: int,
    transform_count: int = 0,
    variable_count: int = 0,
) -> dict[str, Any]:
    return {
        "id": f"fit-result:{series_id}",
        "kind": "fit_result",
        "label": f"{series_label} fit result",
        "status": "enabled",
        "readonly": True,
        "row_count": row_count,
        "column_count": 4,
        "columns": [
            {"id": "fit-x", "name": x_label or "x", "index": 0, "role_hints": ["x"]},
            {"id": "fit-y", "name": y_label or "y", "index": 1, "role_hints": ["y"]},
            {"id": "fit-y-fit", "name": "y_fit", "index": 2, "role_hints": ["fit"]},
            {"id": "fit-residual", "name": "residual", "index": 3, "role_hints": ["residual"]},
        ],
        "source": {
            "input_path": str(input_path),
            "sheet": sheet,
            "offset": offset,
            "limit": limit,
            "transform_count": transform_count,
            "variable_count": variable_count,
        },
        "statistics": {"r_squared": r_squared, "rmse": rmse, "point_count": point_count},
        "help": "Readonly fit result container generated by /fit-analysis.",
    }


__all__ = [
    "fit_result_container",
    "matrix_container_from_array",
    "source_table_data_containers",
    "table_container_from_frame",
]
