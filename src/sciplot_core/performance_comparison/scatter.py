"""Build the performance scatter payload."""

from __future__ import annotations

from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.policy import (
    PERFORMANCE_ENVELOPE_FILL_TRANSPARENCY,
    PERFORMANCE_ENVELOPE_LINE_TRANSPARENCY,
    PERFORMANCE_REFERENCE_ENVELOPE_FILL_TRANSPARENCY,
    categorical_fill_color,
)

from sciplot_core.performance_comparison.models import (
    PERFORMANCE_SCATTER_TEMPLATE_ID,
    PerformanceComparisonError,
    PerformanceMaterial,
    PerformanceComparison,
)

from sciplot_core.performance_comparison.geometry import (
    _axis_bounds,
    _expanded_envelope,
)

from sciplot_core.performance_comparison.styles import (
    _sample_group_colors,
    _reference_group_colors,
    _material_styles,
)

from sciplot_core.performance_comparison.layout import (
    _legend_items,
    _layout_payload,
    _uses_compact_inside_legend,
    _deterministic_scatter_x_values,
)


def build_performance_scatter_payload(
    comparison: PerformanceComparison,
) -> dict[str, Any]:
    x_metric, y_metric = comparison.scatter_metrics
    missing = [
        material.material_id
        for material in comparison.materials
        if x_metric.metric_id not in material.values
        or y_metric.metric_id not in material.values
    ]
    if missing:
        raise PerformanceComparisonError(
            "performance_scatter_material_incomplete",
            "Every plotted material needs both scatter metrics; missing: "
            + ", ".join(missing),
        )
    plotted_x_values, visual_data_transforms = _deterministic_scatter_x_values(
        comparison,
        x_metric=x_metric,
    )
    x_values = [
        plotted_x_values[material.material_id] for material in comparison.materials
    ]
    y_values = [
        material.values[y_metric.metric_id] for material in comparison.materials
    ]
    x_bounds = _axis_bounds(x_values, metric=x_metric)
    y_bounds = _axis_bounds(y_values, metric=y_metric)
    styles = _material_styles(comparison, radar=False)
    identity_members: dict[str, list[PerformanceMaterial]] = {}
    for material in comparison.materials:
        identity_members.setdefault(material.legend_identity, []).append(material)
    series: list[dict[str, Any]] = []
    for legend_identity, members in identity_members.items():
        representative = members[0]
        roles = {material.role for material in members}
        colors = {styles[material.material_id]["color"] for material in members}
        markers = {styles[material.material_id]["marker"] for material in members}
        marker_fill_colors = {
            styles[material.material_id]["marker_fill_color"] for material in members
        }
        if (
            len(roles) != 1
            or len(colors) != 1
            or len(markers) != 1
            or len(marker_fill_colors) != 1
        ):
            raise PerformanceComparisonError(
                "performance_scatter_identity_style_conflict",
                f"Legend identity {legend_identity!r} cannot share one scatter "
                "series because its observations have conflicting roles or "
                "styles.",
            )
        series.append(
            {
                "label": representative.legend_label,
                "legend_identity": legend_identity,
                "source_materials": [material.material_id for material in members],
                "source_x_values": [
                    material.values[x_metric.metric_id] for material in members
                ],
                "x_values": [
                    plotted_x_values[material.material_id] for material in members
                ],
                "y_values": [
                    material.values[y_metric.metric_id] for material in members
                ],
                **styles[representative.material_id],
            }
        )
    envelopes: list[dict[str, Any]] = []
    envelope_samples = tuple(
        material for material in comparison.samples if material.envelope_include
    )
    for group, color in _sample_group_colors(envelope_samples).items():
        members = [material for material in envelope_samples if material.group == group]
        polygon = _expanded_envelope(
            [
                (
                    plotted_x_values[material.material_id],
                    material.values[y_metric.metric_id],
                )
                for material in members
            ],
            x_bounds=x_bounds,
            y_bounds=y_bounds,
            seed_key=f"{comparison.source_sha256}|{group}",
        )
        envelopes.append(
            {
                "group": group,
                "role": "observed_sample_extent",
                "members": [material.material_id for material in members],
                "x_values": [point[0] for point in polygon],
                "y_values": [point[1] for point in polygon],
                "line_color": color,
                "fill_color": categorical_fill_color(color),
                "line_transparency": PERFORMANCE_ENVELOPE_LINE_TRANSPARENCY,
                "fill_transparency": PERFORMANCE_ENVELOPE_FILL_TRANSPARENCY,
                "line_hide": True,
                "interpretation": (
                    "Observed sample extent with deterministic visual "
                    "padding; not a confidence region."
                ),
            }
        )
    envelope_references = tuple(
        material for material in comparison.references if material.envelope_include
    )
    for group, color in _reference_group_colors(envelope_references).items():
        members = [
            material
            for material in envelope_references
            if material.legend_group == group
        ]
        polygon = _expanded_envelope(
            [
                (
                    plotted_x_values[material.material_id],
                    material.values[y_metric.metric_id],
                )
                for material in members
            ],
            x_bounds=x_bounds,
            y_bounds=y_bounds,
            seed_key=f"{comparison.source_sha256}|reference|{group}",
        )
        envelopes.append(
            {
                "group": group,
                "role": "observed_reference_group_extent",
                "members": [material.material_id for material in members],
                "x_values": [point[0] for point in polygon],
                "y_values": [point[1] for point in polygon],
                "line_color": color,
                "fill_color": color,
                "line_transparency": (PERFORMANCE_ENVELOPE_LINE_TRANSPARENCY),
                "fill_transparency": (PERFORMANCE_REFERENCE_ENVELOPE_FILL_TRANSPARENCY),
                "line_hide": True,
                "interpretation": (
                    "Observed reader-facing reference-category extent with "
                    "deterministic visual padding; not a confidence region."
                ),
            }
        )
    legend_items = _legend_items(comparison, styles)
    legend_column_count = max(
        (int(item["legend_column"]) for item in legend_items),
        default=1,
    )
    use_legend_panel = not _uses_compact_inside_legend(legend_items)
    return {
        "kind": "sciplot_performance_comparison",
        "version": 2,
        "template": PERFORMANCE_SCATTER_TEMPLATE_ID,
        "source": str(comparison.source),
        "source_sha256": comparison.source_sha256,
        "source_row_count": comparison.source_row_count,
        "x_metric": json_safe(x_metric.__dict__),
        "y_metric": json_safe(y_metric.__dict__),
        "x_label": x_metric.axis_label,
        "y_label": y_metric.axis_label,
        "x_bounds": list(x_bounds),
        "y_bounds": list(y_bounds),
        "series": series,
        "envelopes": envelopes,
        "legend_items": legend_items,
        "layout": _layout_payload(
            use_legend_panel=use_legend_panel,
            legend_column_count=legend_column_count,
        ),
        "visual_data_transforms": visual_data_transforms,
        "material_count": len(comparison.materials),
        "series_count": len(series),
        "legend_item_count": len(legend_items),
        "sample_count": len(comparison.samples),
        "reference_count": len(comparison.references),
    }
