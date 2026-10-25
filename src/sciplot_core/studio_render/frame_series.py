"""Construct ordered Studio series from normalized source-frame records."""

from __future__ import annotations

from sciplot_core.studio_render.source_artifacts import literal_source_artifact

from typing import Any

from sciplot_core.studio_render.models import (
    CATEGORICAL_POINT_LINE_KIND,
    DEFAULT_PALETTE,
    CATEGORICAL_TEMPLATE_IDS,
    SCALAR_FIELD_TEMPLATE_IDS,
    StudioPreparationBlocked,
    StudioSeries,
    StudioSourceFrame,
)

from sciplot_core.studio_render.categorical_point_line import (
    categorical_point_line_axis_from_frame,
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

from sciplot_core.studio_render.series_option_context import (
    effective_render_options,
)

from sciplot_core.studio_render.series_options import (
    resolve_series_encodings,
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
    strict_metric_binding: bool = False,
) -> tuple[list[StudioSeries], dict[str, Any]]:
    """Derive rendered numeric units from already-resolved terminal tables."""

    render_options = effective_render_options(request)
    template_id = _request_template(request)
    raw_series: list[StudioSeries] = []
    axis_info: dict[str, Any] = {"x_label": "x", "y_label": "y"}
    if frames and frames[0].frame.attrs.get("sciplot_source_group"):
        from sciplot_core.studio_render.source_group_series import source_group_series

        raw_series, axis_info = source_group_series(frames)
    elif "categorical_binding" in request:
        from sciplot_core.studio_render.categorical_bound_series import bound_categorical_series, categorical_style_request

        binding = request["categorical_binding"]
        expected_template = "point_line" if binding["mode"] == "given_values" else "bar"
        if template_id != expected_template or request.get("rule_id"):
            raise StudioPreparationBlocked("categorical_template_mismatch", "Ordinary categorical bindings use their declared point_line or mean/sample-SD bar template without a registered experimental identity.")
        raw_series, axis_info = bound_categorical_series(frames, missing_values=request.get("missing_values"))
        request = categorical_style_request(request, series=raw_series, axis_info=axis_info)
    elif template_id in SCALAR_FIELD_TEMPLATE_IDS:
        raw_series, axis_info = _scalar_field_from_frames(
            frames,
            render_options=render_options,
        )
    elif template_id in CATEGORICAL_TEMPLATE_IDS:
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
            pairs = _xy_pairs_for_request(
                numeric,
                request=request,
                strict_metric_binding=strict_metric_binding,
            )
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
                categorical_axis = (
                    categorical_point_line_axis_from_frame(
                        frame,
                        row_indices=pair_frame.index,
                        x_column=x_column,
                    )
                    if template_id == "point_line"
                    else None
                )
                component_labels: tuple[str, ...] = ()
                presentation_kind = "curve"
                if categorical_axis is not None:
                    component_labels, category_positions = categorical_axis
                    if category_positions != x_values:
                        raise StudioPreparationBlocked(
                            "point_line_category_position_mismatch",
                            "Categorical point-line labels do not align with the "
                            "rendered numeric positions.",
                        )
                    previous_labels = tuple(axis_info.get("category_labels") or ())
                    previous_positions = tuple(
                        float(value)
                        for value in axis_info.get("category_positions") or ()
                    )
                    if previous_labels and (
                        previous_labels != component_labels
                        or previous_positions != category_positions
                    ):
                        raise StudioPreparationBlocked(
                            "mixed_point_line_category_axes",
                            "All categorical point-line series must use one ordered "
                            "Sample axis.",
                        )
                    axis_info.update(
                        {
                            "presentation_kind": CATEGORICAL_POINT_LINE_KIND,
                            "category_labels": list(component_labels),
                            "category_positions": list(category_positions),
                        }
                    )
                    presentation_kind = CATEGORICAL_POINT_LINE_KIND
                raw_series.append(
                    StudioSeries(
                        label=label,
                        x_name=f"x_{frame_index + 1}_{column_index}",
                        y_name=f"y_{frame_index + 1}_{column_index}",
                        x_values=x_values,
                        y_values=y_values,
                        color=DEFAULT_PALETTE[(len(raw_series)) % len(DEFAULT_PALETTE)],
                        presentation_kind=presentation_kind,
                        component_labels=component_labels,
                        source_artifacts=(
                            literal_source_artifact(source_frame.path, source_frame.sha256),
                        ),
                    )
                )

    if not raw_series:
        raise StudioPreparationBlocked(
            "no_plottable_numeric_series",
            "Studio found no plottable numeric x/y series in the terminal "
            "tables; no placeholder data were generated.",
        )

    from sciplot_core.studio_render.paired_source_identity import bind_prepared_pairs

    raw_series, pair_bindings = bind_prepared_pairs(raw_series, request)
    if pair_bindings:
        axis_info["source_bindings"] = pair_bindings
    axis_info["series_count"] = len(raw_series)
    render_options = _resolved_domain_render_options(
        request,
        axis_info=axis_info,
        series=raw_series,
    )
    _validate_log_domain_series(raw_series, render_options=render_options)
    styled = resolve_series_encodings(
        raw_series, render_options=render_options, request=request,
        source_bindings=axis_info.get("source_bindings"),
    )
    axis_info["series_count"] = len(styled)
    render_options = _resolved_domain_render_options(
        request,
        axis_info=axis_info,
        series=styled,
    )
    if axis_info.get("source_bindings") and axis_info.get("presentation_kind") == "categorical_replicates":
        styled = _reindex_categorical_series(styled, source_bindings=axis_info["source_bindings"], render_options=render_options)
        categories = list(dict.fromkeys(axis_info["source_bindings"][item.x_name]["category"] for item in styled))
        aliases = (request.get("categorical_binding") or {}).get("category_aliases", {})
        axis_info["category_labels"] = [_category_axis_label(aliases.get(category, category)) for category in categories]
        axis_info["category_positions"] = [float(index + 1) for index in range(len(categories))]
        axis_info["raw_replicate_count"] = sum(len(item.y_values) for item in styled)
    elif axis_info.get("presentation_kind") == "categorical_replicates":
        styled = _reindex_categorical_series(styled, render_options=render_options)
        axis_info["category_labels"] = [
            _category_axis_label(item.label) for item in styled
        ]
        axis_info["category_positions"] = [
            float(index) for index in range(1, len(styled) + 1)
        ]
        axis_info["raw_replicate_count"] = sum(len(item.y_values) for item in styled)
        if "categorical_binding" in request:
            aliases = request["categorical_binding"].get("category_aliases", {})
            axis_info["category_labels"] = [aliases.get(item.label, item.label) for item in styled]
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
