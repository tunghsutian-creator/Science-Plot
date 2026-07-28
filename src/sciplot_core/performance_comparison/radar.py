"""Build normalized performance radar payloads."""

from __future__ import annotations

from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.policy import (
    PERFORMANCE_RADAR_BOTTOM_MARGIN_MM,
    PERFORMANCE_RADAR_LEFT_MARGIN_MM,
    PERFORMANCE_RADAR_RIGHT_MARGIN_MM,
    PERFORMANCE_RADAR_TOP_MARGIN_MM,
    PERFORMANCE_SAMPLE_FILL_TRANSPARENCY,
)

from sciplot_core.performance_comparison.models import (
    PERFORMANCE_RADAR_TEMPLATE_ID,
    PerformanceComparisonError,
    PerformanceMetric,
    PerformanceComparison,
)

from sciplot_core.performance_comparison.styles import (
    _material_styles,
)

from sciplot_core.performance_comparison.layout import (
    _legend_items,
    _layout_payload,
)


def _normalized_radar_value(value: float, metric: PerformanceMetric) -> float:
    if (
        metric.scale_min is None
        or metric.scale_max is None
        or metric.direction not in {"higher", "lower"}
    ):
        raise PerformanceComparisonError(
            "performance_radar_scale_incomplete",
            f"Metric {metric.metric_id!r} has no complete radar scale.",
        )
    if value < metric.scale_min - 1e-12 or value > metric.scale_max + 1e-12:
        raise PerformanceComparisonError(
            "performance_radar_value_outside_scale",
            f"Metric {metric.metric_id!r} value {value:g} is outside the declared "
            f"[{metric.scale_min:g}, {metric.scale_max:g}] scale.",
        )
    fraction = (value - metric.scale_min) / (metric.scale_max - metric.scale_min)
    return fraction if metric.direction == "higher" else 1.0 - fraction


def build_performance_radar_payload(
    comparison: PerformanceComparison,
) -> dict[str, Any]:
    metrics = comparison.radar_metrics
    axis_labels = [item.radar_label for item in metrics]
    incomplete_samples = [
        material.material_id
        for material in comparison.samples
        if any(metric.metric_id not in material.values for metric in metrics)
    ]
    if incomplete_samples:
        raise PerformanceComparisonError(
            "performance_radar_sample_incomplete",
            "Every Role=sample material needs every radar metric so its filled "
            "polygon is complete; missing: " + ", ".join(incomplete_samples),
        )
    styles = _material_styles(comparison, radar=True)
    angles = [
        (90.0 + 360.0 * index / len(metrics)) % 360.0 for index in range(len(metrics))
    ]
    series: list[dict[str, Any]] = []
    for material in comparison.materials:
        material_angles: list[float] = []
        radii: list[float] = []
        raw_values: list[float] = []
        metric_ids: list[str] = []
        for angle, metric in zip(angles, metrics, strict=True):
            if metric.metric_id not in material.values:
                continue
            raw_value = material.values[metric.metric_id]
            material_angles.append(angle)
            radii.append(_normalized_radar_value(raw_value, metric))
            raw_values.append(raw_value)
            metric_ids.append(metric.metric_id)
        if not radii:
            raise PerformanceComparisonError(
                "performance_radar_reference_empty",
                f"Reference material {material.material_id!r} has no radar values.",
            )
        filled = material.role == "sample"
        if filled:
            material_angles.append(material_angles[0])
            radii.append(radii[0])
            raw_values.append(raw_values[0])
            metric_ids.append(metric_ids[0])
        series.append(
            {
                "label": material.legend_label,
                "angles_degrees": material_angles,
                "radii": radii,
                "raw_values": raw_values,
                "metric_ids": metric_ids,
                "filled_polygon": filled,
                "fill_transparency": PERFORMANCE_SAMPLE_FILL_TRANSPARENCY,
                **styles[material.material_id],
            }
        )
    use_legend_panel = bool(
        comparison.references
        or len(comparison.samples) > 3
        or any(item.citation for item in comparison.materials)
    )
    legend_items = _legend_items(comparison, styles)
    legend_column_count = max(
        (int(item["legend_column"]) for item in legend_items),
        default=1,
    )
    return {
        "kind": "sciplot_performance_comparison",
        "version": 2,
        "template": PERFORMANCE_RADAR_TEMPLATE_ID,
        "source": str(comparison.source),
        "source_sha256": comparison.source_sha256,
        "source_row_count": comparison.source_row_count,
        "metrics": [json_safe(item.__dict__) for item in metrics],
        "axis_labels": axis_labels,
        "axis_endpoint_labels": [
            f"{float(metric.scale_max if metric.direction == 'higher' else metric.scale_min):g}"
            for metric in metrics
        ],
        "angles_degrees": angles,
        "normalization": {
            "kind": "declared_bounded_directional_score",
            "range": [0.0, 1.0],
            "outer_is_better": True,
            "higher_formula": "(value - scale_min) / (scale_max - scale_min)",
            "lower_formula": "(scale_max - value) / (scale_max - scale_min)",
            "values_outside_declared_bounds": "fail_closed",
        },
        "series": series,
        "legend_items": legend_items,
        "layout": _layout_payload(
            use_legend_panel=use_legend_panel,
            legend_column_count=legend_column_count,
            left_margin_mm=PERFORMANCE_RADAR_LEFT_MARGIN_MM,
            right_margin_mm=PERFORMANCE_RADAR_RIGHT_MARGIN_MM,
            bottom_margin_mm=PERFORMANCE_RADAR_BOTTOM_MARGIN_MM,
            top_margin_mm=PERFORMANCE_RADAR_TOP_MARGIN_MM,
        ),
        "material_count": len(comparison.materials),
        "sample_count": len(comparison.samples),
        "reference_count": len(comparison.references),
    }
