"""Resolve scalar-field roles and construct scalar-field series from source frames."""

from __future__ import annotations

import math
from typing import Any
import pandas as pd

from sciplot_core.studio_render.models import (
    DEFAULT_PALETTE,
    StudioPreparationBlocked,
    StudioSeries,
    StudioSourceFrame,
)

from sciplot_core.studio_render.categorical_values import (
    _veusz_axis_label,
)

from sciplot_core.studio_render.table_io import (
    _coerced_numeric_frame,
)


def _scalar_field_role_columns(
    frame: pd.DataFrame,
    *,
    render_options: dict[str, Any],
) -> tuple[object, object, object]:
    numeric = _coerced_numeric_frame(frame)
    numeric_columns = [
        column for column in numeric.columns if numeric[column].notna().any()
    ]
    if len(numeric_columns) < 3:
        raise StudioPreparationBlocked(
            "scalar_field_needs_xyz_columns",
            "Scalar-field rendering needs three numeric X/Y/Z columns.",
        )
    requested = render_options.get("data_variables")
    requested = requested if isinstance(requested, dict) else {}
    resolved: list[object] = []
    available_by_text = {
        str(column).strip().casefold(): column for column in frame.columns
    }
    for role in ("x", "y", "z"):
        value = requested.get(role)
        if isinstance(value, str) and value.strip():
            column = available_by_text.get(value.strip().casefold())
            if column is None:
                raise StudioPreparationBlocked(
                    "scalar_field_role_column_missing",
                    f"Scalar-field role `{role}` refers to missing column `{value}`.",
                )
            resolved.append(column)
            continue
        alias = next(
            (
                column
                for column in numeric_columns
                if str(column).strip().casefold() in {role, role.upper().casefold()}
            ),
            None,
        )
        if alias is not None and alias not in resolved:
            resolved.append(alias)
            continue
        fallback = next(
            (column for column in numeric_columns if column not in resolved), None
        )
        if fallback is None:
            raise StudioPreparationBlocked(
                "scalar_field_role_column_missing",
                f"Scalar-field role `{role}` could not be resolved.",
            )
        resolved.append(fallback)
    return resolved[0], resolved[1], resolved[2]


def _scalar_field_from_frames(
    frames: list[StudioSourceFrame | tuple[str, pd.DataFrame]],
    *,
    render_options: dict[str, Any],
) -> tuple[list[StudioSeries], dict[str, Any]]:
    if len(frames) != 1:
        raise StudioPreparationBlocked(
            "scalar_field_needs_one_table",
            "Scalar-field rendering currently accepts one plot-ready X/Y/Z table per figure.",
        )
    source_frame = frames[0]
    if isinstance(source_frame, StudioSourceFrame):
        frame = source_frame.frame
        source_artifacts = [
            {
                "path": str(source_frame.path),
                "sha256": source_frame.sha256,
            }
        ]
        series_source_artifacts = ((str(source_frame.path), source_frame.sha256),)
    else:
        _label, frame = source_frame
        source_artifacts = []
        series_source_artifacts = ()
    x_column, y_column, z_column = _scalar_field_role_columns(
        frame, render_options=render_options
    )
    numeric = _coerced_numeric_frame(frame)
    field = numeric[[x_column, y_column, z_column]].dropna().copy()
    if field.empty:
        raise StudioPreparationBlocked(
            "scalar_field_has_no_finite_rows",
            "Scalar-field X/Y/Z columns contain no complete numeric rows.",
        )
    if field.duplicated([x_column, y_column]).any():
        raise StudioPreparationBlocked(
            "scalar_field_duplicate_xy",
            "Scalar-field X/Y pairs must be unique; aggregate duplicates explicitly before rendering.",
        )
    x_values = sorted(float(value) for value in field[x_column].unique())
    y_values = sorted(float(value) for value in field[y_column].unique())
    if len(x_values) < 2 or len(y_values) < 2:
        raise StudioPreparationBlocked(
            "scalar_field_grid_too_small",
            "Scalar-field rendering needs at least two unique X and two unique Y coordinates.",
        )
    expected_rows = len(x_values) * len(y_values)
    if len(field) != expected_rows:
        raise StudioPreparationBlocked(
            "scalar_field_incomplete_grid",
            f"Scalar-field grid is incomplete: expected {expected_rows} unique X/Y cells, found {len(field)}.",
        )
    pivot = field.pivot(index=y_column, columns=x_column, values=z_column).reindex(
        index=y_values,
        columns=x_values,
    )
    if pivot.isna().any().any():
        raise StudioPreparationBlocked(
            "scalar_field_incomplete_grid",
            "Scalar-field grid contains missing cells after X/Y pivoting.",
        )
    z_values = [[float(value) for value in row] for row in pivot.to_numpy(dtype=float)]
    if not all(math.isfinite(value) for row in z_values for value in row):
        raise StudioPreparationBlocked(
            "scalar_field_non_finite_z",
            "Scalar-field Z values must all be finite.",
        )
    zscale = str(render_options.get("zscale") or "linear").strip().casefold()
    if zscale not in {"linear", "sqrt", "log", "squared"}:
        raise ValueError("Scalar-field zscale must be linear, sqrt, log, or squared.")
    if zscale == "log" and any(value <= 0.0 for row in z_values for value in row):
        raise StudioPreparationBlocked(
            "scalar_field_log_requires_positive_z",
            "Scalar-field logarithmic color scaling requires strictly positive Z values.",
        )
    x_label = _veusz_axis_label(render_options.get("x_label_override") or str(x_column))
    y_label = _veusz_axis_label(render_options.get("y_label_override") or str(y_column))
    z_label = _veusz_axis_label(render_options.get("z_label_override") or str(z_column))
    scalar_field = {
        "data_name": "scalar_field_z",
        "x_column": str(x_column),
        "y_column": str(y_column),
        "z_column": str(z_column),
        "x_values": x_values,
        "y_values": y_values,
        "z_values": z_values,
        "z_label": z_label,
        "z_data_min": min(value for row in z_values for value in row),
        "z_data_max": max(value for row in z_values for value in row),
        "grid_shape": [len(y_values), len(x_values)],
        "source_artifacts": source_artifacts,
    }
    surrogate = StudioSeries(
        label=z_label,
        x_name="scalar_field_extent_x",
        y_name="scalar_field_extent_y",
        x_values=(x_values[0], x_values[-1]),
        y_values=(y_values[0], y_values[-1]),
        color=DEFAULT_PALETTE[0],
        marker="none",
        presentation_kind="scalar_field",
        source_artifacts=series_source_artifacts,
    )
    return [surrogate], {
        "x_label": x_label,
        "y_label": y_label,
        "scalar_field": scalar_field,
    }
