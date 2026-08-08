"""Apply request render options, palette choices, and replicate styling to series."""

from __future__ import annotations

from collections import Counter
from typing import Any
from sciplot_core.policy import (
    DEFAULT_CURVE_LINE_STYLE_SEQUENCE,
    UNIFIED_LINE_WIDTH_PT,
    UNIFIED_MARKER_SIZE_PT,
    categorical_component_fill_color,
    resolve_palette_authority,
)

from sciplot_core.studio_render.models import (
    IMPACT_POINT_LINE_KINDS,
    POINT_LINE_MARKERS,
    SeriesEncodingProvenance,
    StudioPreparationBlocked,
    StudioSeries,
)

from sciplot_core.studio_render.categorical_groups import (
    _factor_pair_identity,
    _grouped_bar_identity,
    _factorized_curve_grid,
)

from sciplot_core.studio_render.series_option_context import (
    is_inferred_source_group_order,
    replicate_group_style_indexes,
    request_option_authority,
)

from sciplot_core.studio_render.template_resolution import (
    _request_template,
)

from sciplot_core.studio_render.value_parsing import (
    _string_list,
)


def resolve_series_encodings(
    series: list[StudioSeries],
    *,
    render_options: dict[str, Any],
    request: dict[str, Any],
) -> list[StudioSeries]:
    """Select, order, and bind every ordinary series visual encoding once."""

    include = _string_list(render_options.get("series_include"))
    order = _string_list(render_options.get("series_order")) or _string_list(
        request.get("series_order")
    )
    styles = (
        render_options.get("series_styles")
        if isinstance(render_options.get("series_styles"), list)
        else []
    )
    template_id = _request_template(request)
    palette_resolution = resolve_palette_authority(
        request,
        template_id=template_id,
    )
    palette = palette_resolution.colors
    marker_sequence = _string_list(render_options.get("marker_sequence"))
    if not marker_sequence:
        marker_sequence = list(POINT_LINE_MARKERS)
    line_style_sequence = _string_list(render_options.get("line_style_sequence"))
    if not line_style_sequence:
        line_style_sequence = list(DEFAULT_CURVE_LINE_STYLE_SEQUENCE)
    marker_sequence_source, marker_sequence_bound = request_option_authority(
        request,
        "marker_sequence",
    )
    line_sequence_source, line_sequence_bound = request_option_authority(
        request,
        "line_style_sequence",
    )
    series_styles_source, series_styles_bound = request_option_authority(
        request,
        "series_styles",
    )
    marker_fill_source, marker_fill_bound = request_option_authority(
        request,
        "marker_fill_mode",
    )
    duplicate_labels = sorted(
        label
        for label, count in Counter(item.label for item in series).items()
        if count > 1
    )
    if duplicate_labels:
        raise StudioPreparationBlocked(
            "duplicate_series_labels",
            "Series labels must be unique before label-based selection: "
            + ", ".join(duplicate_labels),
        )
    duplicate_order = sorted(
        label for label, count in Counter(order).items() if count > 1
    )
    if duplicate_order:
        raise StudioPreparationBlocked(
            "duplicate_series_order",
            "series_order contains duplicate labels: " + ", ".join(duplicate_order),
        )
    duplicate_include = sorted(
        label for label, count in Counter(include).items() if count > 1
    )
    if duplicate_include:
        raise StudioPreparationBlocked(
            "duplicate_series_include",
            "series_include contains duplicate labels: " + ", ".join(duplicate_include),
        )
    by_label = {item.label: item for item in series}
    unknown_order = [label for label in order if label not in by_label]
    if unknown_order:
        if is_inferred_source_group_order(order, request=request):
            order = [label for label in order if label in by_label]
        else:
            raise StudioPreparationBlocked(
                "unknown_series_order",
                "series_order contains unknown series labels: "
                + ", ".join(unknown_order),
            )
    ordered = [by_label[label] for label in order if label in by_label]
    ordered.extend(
        item for item in series if item.label not in {entry.label for entry in ordered}
    )
    if include:
        unknown_include = [label for label in include if label not in by_label]
        if unknown_include:
            raise StudioPreparationBlocked(
                "unknown_series_include",
                "series_include contains unknown series labels: "
                + ", ".join(unknown_include),
            )
        include_set = set(include)
        ordered = [item for item in ordered if item.label in include_set]
    style_by_label: dict[str, dict[str, Any]] = {}
    for style in styles:
        if isinstance(style, dict):
            label = (
                style.get("label")
                or style.get("sample")
                or style.get("name")
                or style.get("series_id")
            )
            if isinstance(label, str):
                style_by_label[label] = style
    styled: list[StudioSeries] = []
    factorized_curve = _factorized_curve_grid(
        ordered,
        template_id=template_id,
    )
    grouped_replicate_styles = (
        replicate_group_style_indexes([item.label for item in ordered])
        if str(request.get("rule_id") or "").strip() == "swelling_curve"
        else {}
    )
    grouped_bar_samples: list[str] = []
    for item in ordered:
        if item.presentation_kind != "categorical_grouped_replicates":
            continue
        sample, _condition = _grouped_bar_identity(item.label)
        if sample not in grouped_bar_samples:
            grouped_bar_samples.append(sample)
    for index, item in enumerate(ordered):
        style = style_by_label.get(item.label, {})
        if style.get("visible") is False or style.get("enabled") is False:
            continue
        impact_point_line_item = item.presentation_kind in IMPACT_POINT_LINE_KINDS
        condition_index, replicate_index = grouped_replicate_styles.get(
            item.label,
            (index, index),
        )
        factor_color: str | None = None
        factor_line_style: str | None = None
        if factorized_curve is not None:
            formula, condition = _factor_pair_identity(item.label)
            formula_index = factorized_curve["formula_order"].index(formula)
            factor_condition_index = factorized_curve["condition_order"].index(
                condition
            )
            condition_index = formula_index
            replicate_index = formula_index
            root_color = palette[formula_index % len(palette)]
            factor_color = categorical_component_fill_color(
                root_color,
                component_index=(
                    len(factorized_curve["condition_order"])
                    - 1
                    - factor_condition_index
                ),
                component_count=len(factorized_curve["condition_order"]),
            )
            # Factorized curves are continuous line charts: formula owns the
            # categorical colour root, condition owns the opaque light/dark
            # tone, and every measured trace remains solid with no markers.
            factor_line_style = "solid"
        if item.presentation_kind == "categorical_grouped_replicates":
            sample, _condition = _grouped_bar_identity(item.label)
            condition_index = grouped_bar_samples.index(sample)
        default_marker = (
            marker_sequence[replicate_index % len(marker_sequence)]
            if (
                template_id == "point_line"
                or item.presentation_kind == "categorical_replicates"
            )
            else "none"
        )
        if factor_line_style is not None:
            default_line_style = factor_line_style
            default_line_source = "semantic_factor_contract"
            default_line_bound = False
        elif line_sequence_bound:
            # An explicit sequence maps directly to final series order.  The
            # old marker-cycle heuristic silently ignored a two-entry line
            # sequence when two marker shapes were also available.
            default_line_style = line_style_sequence[index % len(line_style_sequence)]
            default_line_source = line_sequence_source
            default_line_bound = True
        elif item.label in grouped_replicate_styles:
            default_line_style = line_style_sequence[
                replicate_index % len(line_style_sequence)
            ]
            default_line_source = "semantic_replicate_contract"
            default_line_bound = False
        elif template_id == "point_line" and len(ordered) > len(marker_sequence):
            default_line_style = line_style_sequence[
                (index // len(marker_sequence)) % len(line_style_sequence)
            ]
            default_line_source = "template_marker_cycle"
            default_line_bound = False
        elif template_id != "point_line" and len(ordered) > 1:
            default_line_style = line_style_sequence[index % len(line_style_sequence)]
            default_line_source = "template_series_sequence"
            default_line_bound = False
        else:
            default_line_style = "solid"
            default_line_source = "template_default"
            default_line_bound = False

        style_color = style.get("color")
        if style_color:
            resolved_color = str(style_color)
            color_source = series_styles_source
            color_bound = series_styles_bound
        elif factor_color is not None:
            resolved_color = str(factor_color)
            color_source = "semantic_factor_contract"
            color_bound = False
        elif impact_point_line_item:
            resolved_color = str(item.color)
            color_source = "semantic_series_contract"
            color_bound = False
        else:
            resolved_color = str(palette[condition_index % len(palette)])
            color_source = f"palette_{palette_resolution.source}"
            color_bound = palette_resolution.explicit

        style_marker = style.get("marker")
        if style_marker not in (None, ""):
            resolved_marker = style_marker
            resolved_marker_source = series_styles_source
            marker_bound = series_styles_bound
        elif impact_point_line_item and item.marker not in (None, ""):
            resolved_marker = item.marker
            resolved_marker_source = "semantic_series_contract"
            marker_bound = False
        else:
            resolved_marker = item.marker or default_marker
            if template_id == "point_line" or item.presentation_kind == (
                "categorical_replicates"
            ):
                resolved_marker_source = marker_sequence_source
                marker_bound = marker_sequence_bound
            else:
                resolved_marker_source = "template_default"
                marker_bound = False

        style_line = style.get("line_style") or style.get("linestyle")
        if style_line:
            resolved_line_style = str(style_line)
            resolved_line_source = series_styles_source
            line_bound = series_styles_bound
        elif impact_point_line_item and item.line_style:
            resolved_line_style = str(item.line_style)
            resolved_line_source = "semantic_series_contract"
            line_bound = False
        else:
            resolved_line_style = str(default_line_style)
            resolved_line_source = default_line_source
            line_bound = default_line_bound

        marker_fill_mode = str(
            render_options.get("marker_fill_mode") or "filled"
        ).casefold()
        if item.presentation_kind == "categorical_replicates":
            resolved_marker_fill = resolved_color
            resolved_marker_fill_source = color_source
            resolved_marker_fill_bound = color_bound
        elif marker_fill_mode == "open":
            resolved_marker_fill = "white"
            resolved_marker_fill_source = marker_fill_source
            resolved_marker_fill_bound = marker_fill_bound
        else:
            resolved_marker_fill = resolved_color
            resolved_marker_fill_source = (
                marker_fill_source if marker_fill_bound else color_source
            )
            resolved_marker_fill_bound = marker_fill_bound or color_bound

        if item.marker_line_color:
            resolved_marker_line = item.marker_line_color
            resolved_marker_line_source = "semantic_series_contract"
            resolved_marker_line_bound = False
        else:
            resolved_marker_line = resolved_color
            resolved_marker_line_source = color_source
            resolved_marker_line_bound = color_bound

        marker_is_drawn = resolved_marker is not False and (
            str(resolved_marker or "none").strip().casefold() != "none"
        )
        request_bound_fields: list[str] = []
        if color_bound:
            request_bound_fields.append("line.color")
        if line_bound:
            request_bound_fields.append("line.style")
        if marker_bound:
            request_bound_fields.append("marker.shape")
        if marker_is_drawn and resolved_marker_fill_bound:
            request_bound_fields.append("marker.fill_color")
        if marker_is_drawn and resolved_marker_line_bound:
            request_bound_fields.append("marker.line_color")
        styled.append(
            StudioSeries(
                label=item.label,
                x_name=item.x_name,
                y_name=item.y_name,
                x_values=item.x_values,
                y_values=item.y_values,
                error_values=item.error_values,
                color=resolved_color,
                line_width=UNIFIED_LINE_WIDTH_PT,
                marker=resolved_marker,
                marker_size=(
                    item.marker_size
                    if impact_point_line_item and item.marker_size is not None
                    else UNIFIED_MARKER_SIZE_PT
                ),
                marker_alpha=item.marker_alpha,
                marker_fill_color=resolved_marker_fill,
                marker_line_color=resolved_marker_line,
                marker_line_width=item.marker_line_width,
                line_style=resolved_line_style,
                presentation_kind=item.presentation_kind,
                category_position=item.category_position,
                component_labels=item.component_labels,
                source_artifacts=item.source_artifacts,
                encoding_provenance=SeriesEncodingProvenance(
                    color_source=color_source,
                    line_style_source=resolved_line_source,
                    marker_source=resolved_marker_source,
                    marker_fill_source=resolved_marker_fill_source,
                    marker_line_source=resolved_marker_line_source,
                    request_bound_fields=tuple(request_bound_fields),
                ),
            )
        )
    if not styled:
        raise StudioPreparationBlocked(
            "no_visible_series",
            "The confirmed series selection leaves no visible series.",
        )
    return styled


def _apply_series_options(
    series: list[StudioSeries],
    *,
    render_options: dict[str, Any],
    request: dict[str, Any],
) -> list[StudioSeries]:
    """Compatibility alias for the single series-encoding resolver."""

    return resolve_series_encodings(
        series,
        render_options=render_options,
        request=request,
    )
