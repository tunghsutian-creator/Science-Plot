"""Construct ordered Studio series from normalized source-frame records."""

from __future__ import annotations

from typing import Any

from sciplot_core.studio_render.models import (
    DEFAULT_PALETTE,
    CATEGORICAL_TEMPLATE_IDS,
    SCALAR_FIELD_TEMPLATE_IDS,
    StudioPreparationBlocked,
    StudioSeries,
    StudioSourceFrame,
)

from sciplot_core.studio_render.scalar_series import (
    _scalar_field_from_frames,
)

from sciplot_core.studio_render.series_domain import (
    _resolved_domain_render_options,
    _validate_log_domain_series,
)

from sciplot_core.studio_render.categorical_values import (
    _veusz_axis_label,
    _category_axis_label,
)

from sciplot_core.studio_render.categorical_series import (
    _categorical_series_from_frames,
    _reindex_categorical_series,
)

from sciplot_core.studio_render.table_io import (
    _coerced_numeric_frame,
    _series_metadata_order,
)

from sciplot_core.studio_render.metric_columns import (
    _xy_pairs_for_request,
    _axis_label_from_column,
    _series_label_from_column,
)

from sciplot_core.studio_render.series_options import (
    _apply_series_options,
    _effective_render_options,
)

from sciplot_core.studio_render.series_transforms import (
    _apply_template_series_transforms,
)

from sciplot_core.studio_render.template_resolution import (
    _request_template,
)


def _series_from_frame_records(
    request: dict[str, Any],
    *,
    frames: list[StudioSourceFrame],
) -> tuple[list[StudioSeries], dict[str, Any]]:
    """Derive rendered numeric units from already-resolved terminal tables."""

    render_options = _effective_render_options(request)
    raw_series: list[StudioSeries] = []
    axis_info: dict[str, Any] = {"x_label": "x", "y_label": "y"}
    if _request_template(request) in SCALAR_FIELD_TEMPLATE_IDS:
        raw_series, axis_info = _scalar_field_from_frames(
            frames,
            render_options=render_options,
        )
    elif _request_template(request) in CATEGORICAL_TEMPLATE_IDS:
        raw_series, axis_info = _categorical_series_from_frames(
            frames,
            render_options=render_options,
        )
    else:
        for frame_index, source_frame in enumerate(frames):
            source_label = source_frame.label
            frame = source_frame.frame
            numeric = _coerced_numeric_frame(frame)
            if numeric.shape[1] < 2:
                continue
            metadata_order = _series_metadata_order(frame)
            pairs = _xy_pairs_for_request(numeric, request=request)
            first_x, first_y = pairs[0]
            if axis_info["x_label"] == "x":
                axis_info["x_label"] = _axis_label_from_column(frame, first_x)
            if axis_info["y_label"] == "y":
                axis_info["y_label"] = _axis_label_from_column(frame, first_y)
            for column_index, (x_column, y_column) in enumerate(pairs, start=1):
                pair_frame = numeric[[x_column, y_column]].dropna()
                if pair_frame.empty:
                    continue
                x_values = tuple(
                    float(value) for value in pair_frame[x_column].tolist()
                )
                y_values = tuple(
                    float(value) for value in pair_frame[y_column].tolist()
                )
                fallback = source_label if len(pairs) == 1 else str(y_column)
                label = _series_label_from_column(
                    frame[y_column],
                    fallback=fallback,
                    metadata_order=metadata_order,
                )
                raw_series.append(
                    StudioSeries(
                        label=label,
                        x_name=f"x_{frame_index + 1}_{column_index}",
                        y_name=f"y_{frame_index + 1}_{column_index}",
                        x_values=x_values,
                        y_values=y_values,
                        color=DEFAULT_PALETTE[(len(raw_series)) % len(DEFAULT_PALETTE)],
                        source_artifacts=(
                            (str(source_frame.path), source_frame.sha256),
                        ),
                    )
                )

    if not raw_series:
        raise StudioPreparationBlocked(
            "no_plottable_numeric_series",
            "Studio found no plottable numeric x/y series in the terminal "
            "tables; no placeholder data were generated.",
        )

    axis_info["series_count"] = len(raw_series)
    render_options = _resolved_domain_render_options(
        request,
        axis_info=axis_info,
        series=raw_series,
    )
    _validate_log_domain_series(raw_series, render_options=render_options)
    styled = _apply_series_options(
        raw_series, render_options=render_options, request=request
    )
    axis_info["series_count"] = len(styled)
    render_options = _resolved_domain_render_options(
        request,
        axis_info=axis_info,
        series=styled,
    )
    if axis_info.get("presentation_kind") == "categorical_replicates":
        styled = _reindex_categorical_series(styled, render_options=render_options)
        axis_info["category_labels"] = [
            _category_axis_label(item.label) for item in styled
        ]
        axis_info["category_positions"] = [
            float(index) for index in range(1, len(styled) + 1)
        ]
        axis_info["raw_replicate_count"] = sum(len(item.y_values) for item in styled)
    styled = _apply_template_series_transforms(
        styled, request=request, render_options=render_options
    )
    _validate_log_domain_series(styled, render_options=render_options)
    axis_info["x_label"] = _veusz_axis_label(
        render_options.get("x_label_override") or axis_info["x_label"]
    )
    axis_info["y_label"] = _veusz_axis_label(
        render_options.get("y_label_override") or axis_info["y_label"]
    )
    return styled, axis_info
