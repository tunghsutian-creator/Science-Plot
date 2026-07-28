"""Build physical panel and legend layout contracts."""

from __future__ import annotations

import hashlib
import math
from typing import Any
from sciplot_core.policy import (
    DEFAULT_LAYOUT_POLICY,
    PERFORMANCE_PANEL_HEIGHT_MM,
    PERFORMANCE_PANEL_WIDTH_MM,
    PERFORMANCE_REFERENCE_PANEL_WIDTH_MM,
    PERFORMANCE_SCATTER_JITTER_HALFSPAN_FRACTION,
    UNIFIED_BOTTOM_MARGIN_MM,
    UNIFIED_LEFT_MARGIN_MM,
    UNIFIED_RIGHT_MARGIN_MM,
    UNIFIED_TOP_MARGIN_MM,
)

from sciplot_core.performance_comparison.models import (
    PerformanceComparisonError,
    PerformanceMetric,
    PerformanceMaterial,
    PerformanceComparison,
)


def _legend_items(
    comparison: PerformanceComparison,
    styles: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_identities: set[str] = set()
    for material in comparison.materials:
        if material.legend_identity in seen_identities:
            continue
        members = [
            item
            for item in comparison.materials
            if item.legend_identity == material.legend_identity
        ]
        for field in (
            "role",
            "legend_label",
            "legend_label_explicit",
            "legend_group",
            "legend_column",
            "legend_items_per_row",
            "marker_line_color",
            "marker_fill_color",
        ):
            values = list(dict.fromkeys(getattr(item, field) for item in members))
            if len(values) > 1:
                raise PerformanceComparisonError(
                    "performance_legend_identity_conflict",
                    f"Legend identity {material.legend_identity!r} has "
                    f"conflicting {field} values: {values}.",
                )
        seen_identities.add(material.legend_identity)
        citations = list(
            dict.fromkeys(item.citation for item in members if item.citation)
        )
        items.append(
            {
                "material": material.legend_identity,
                "source_materials": [item.material_id for item in members],
                "role": material.role,
                "group": material.group,
                "legend_group": material.legend_group,
                "legend_column": material.legend_column,
                "legend_items_per_row": material.legend_items_per_row,
                "label": material.legend_label,
                "append_citation": not material.legend_label_explicit,
                "marker": styles[material.material_id]["marker"],
                "color": styles[material.material_id]["color"],
                "marker_fill_color": styles[material.material_id]["marker_fill_color"],
                "citation": "; ".join(citations),
                "journal": material.journal,
                "year": material.year,
                "doi": material.doi,
            }
        )
    return items


def _layout_payload(
    *,
    use_legend_panel: bool,
    legend_column_count: int = 1,
    plot_panel_width_mm: float = PERFORMANCE_PANEL_WIDTH_MM,
    left_margin_mm: float = UNIFIED_LEFT_MARGIN_MM,
    right_margin_mm: float = UNIFIED_RIGHT_MARGIN_MM,
    bottom_margin_mm: float = UNIFIED_BOTTOM_MARGIN_MM,
    top_margin_mm: float = UNIFIED_TOP_MARGIN_MM,
) -> dict[str, Any]:
    plot_panel_width_mm = float(plot_panel_width_mm)
    left_margin_mm = float(left_margin_mm)
    right_margin_mm = float(right_margin_mm)
    bottom_margin_mm = float(bottom_margin_mm)
    top_margin_mm = float(top_margin_mm)
    legend_column_count = max(1, min(int(legend_column_count), 2))
    legend_width_mm = (
        PERFORMANCE_REFERENCE_PANEL_WIDTH_MM * legend_column_count
        if use_legend_panel
        else 0.0
    )
    width_mm = (
        plot_panel_width_mm + legend_width_mm
        if use_legend_panel
        else plot_panel_width_mm
    )
    graph_right_margin = width_mm - plot_panel_width_mm + right_margin_mm
    return {
        "kind": (
            f"performance_{plot_panel_width_mm:g}mm_plot_with_reserved_legend"
            if use_legend_panel
            else f"performance_{plot_panel_width_mm:g}mm_inside_legend"
        ),
        "page_size_mm": [width_mm, PERFORMANCE_PANEL_HEIGHT_MM],
        "plot_panel_size_mm": [
            plot_panel_width_mm,
            PERFORMANCE_PANEL_HEIGHT_MM,
        ],
        "legend_panel_size_mm": (
            [legend_width_mm, PERFORMANCE_PANEL_HEIGHT_MM] if use_legend_panel else None
        ),
        "legend_column_count": (legend_column_count if use_legend_panel else 0),
        "graph_margins_mm": {
            "left": left_margin_mm,
            "right": graph_right_margin,
            "bottom": bottom_margin_mm,
            "top": top_margin_mm,
        },
        "plot_region_mm": [
            plot_panel_width_mm - left_margin_mm - right_margin_mm,
            PERFORMANCE_PANEL_HEIGHT_MM - bottom_margin_mm - top_margin_mm,
        ],
        "outside_legend": False,
        "legend_uses_reserved_panel": use_legend_panel,
    }


def _uses_compact_inside_legend(
    legend_items: list[dict[str, Any]],
) -> bool:
    """Use the shared inside-legend frame only for true group summaries."""

    if not legend_items:
        return False
    if len(legend_items) > DEFAULT_LAYOUT_POLICY.inside_legend_max_series:
        return False
    return all(
        str(item.get("label") or "").strip()
        == str(item.get("legend_group") or "").strip()
        == str(item.get("material") or "").strip()
        and not (
            bool(item.get("append_citation", True))
            and bool(str(item.get("citation") or "").strip())
        )
        for item in legend_items
    )


def _deterministic_scatter_x_values(
    comparison: PerformanceComparison,
    *,
    x_metric: PerformanceMetric,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    raw_values = {
        material.material_id: material.values[x_metric.metric_id]
        for material in comparison.materials
    }
    raw_span = max(raw_values.values()) - min(raw_values.values())
    if math.isclose(raw_span, 0.0):
        raw_span = max(abs(next(iter(raw_values.values()))), 1.0) * 0.16
    jitter_half_span = raw_span * PERFORMANCE_SCATTER_JITTER_HALFSPAN_FRACTION
    result = dict(raw_values)
    jitter_records: list[dict[str, Any]] = []
    buckets: dict[str, list[PerformanceMaterial]] = {}
    for material in comparison.samples:
        raw_value = raw_values[material.material_id]
        buckets.setdefault(f"{raw_value:.12g}", []).append(material)
    for raw_key, members in buckets.items():
        if len(members) <= 1:
            continue
        slots = [
            -jitter_half_span + 2.0 * jitter_half_span * index / float(len(members) - 1)
            for index in range(len(members))
        ]
        shuffled_members = sorted(
            members,
            key=lambda material: hashlib.sha256(
                (f"{comparison.source_sha256}|{raw_key}|{material.material_id}").encode(
                    "utf-8"
                )
            ).digest(),
        )
        for member, offset in zip(shuffled_members, slots, strict=True):
            source_value = raw_values[member.material_id]
            plotted_value = source_value + offset
            result[member.material_id] = plotted_value
            jitter_records.append(
                {
                    "material": member.material_id,
                    "source_x": source_value,
                    "offset": offset,
                    "plotted_x": plotted_value,
                }
            )
    transforms: list[dict[str, Any]] = []
    if jitter_records:
        transforms.append(
            {
                "id": "performance_scatter_repeated_x_jitter",
                "operation": "deterministic_horizontal_jitter",
                "implementation_ref": (
                    "sciplot_core.performance_comparison."
                    "_deterministic_scatter_x_values"
                ),
                "parameters": {
                    "policy": "stable_hash_shuffled_even_slots",
                    "scope": "Role=sample rows sharing the same source x value",
                    "half_span_fraction": (
                        PERFORMANCE_SCATTER_JITTER_HALFSPAN_FRACTION
                    ),
                    "source_metric": x_metric.metric_id,
                    "scientific_source_values_modified": False,
                },
                "records": jitter_records,
            }
        )
    return result, transforms
