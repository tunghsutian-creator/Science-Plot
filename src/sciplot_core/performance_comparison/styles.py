"""Assign deterministic material colors, markers, and legend entries."""

from __future__ import annotations

from typing import Any
from sciplot_core.policy import (
    DEFAULT_PALETTE_COLORS,
    PERFORMANCE_MARKERS,
    PERFORMANCE_REFERENCE_COLOR,
    categorical_fill_color,
)

from sciplot_core.performance_comparison.models import (
    PerformanceComparisonError,
    PerformanceMaterial,
    PerformanceComparison,
)


def _sample_group_colors(
    materials: tuple[PerformanceMaterial, ...],
) -> dict[str, str]:
    groups = list(
        dict.fromkeys(item.group for item in materials if item.role == "sample")
    )
    palette = DEFAULT_PALETTE_COLORS[1:] or DEFAULT_PALETTE_COLORS
    return {group: palette[0] for group in groups}


def _reference_group_colors(
    materials: tuple[PerformanceMaterial, ...],
) -> dict[str, str]:
    colors: dict[str, str] = {}
    groups = list(dict.fromkeys(item.legend_group for item in materials))
    for group in groups:
        members = [item for item in materials if item.legend_group == group]
        group_colors = {
            item.marker_fill_color
            for item in members
            if item.marker_fill_color is not None
        }
        if len(group_colors) != 1 or any(
            item.marker_fill_color is None for item in members
        ):
            raise PerformanceComparisonError(
                "performance_reference_envelope_fill_conflict",
                f"Reference envelope group {group!r} requires one shared "
                "explicit MarkerFillColor for every included observation.",
            )
        colors[group] = next(iter(group_colors))
    return colors


def _material_styles(
    comparison: PerformanceComparison,
    *,
    radar: bool,
) -> dict[str, dict[str, Any]]:
    identity_order = list(
        dict.fromkeys(material.legend_identity for material in comparison.materials)
    )
    if len(identity_order) > len(PERFORMANCE_MARKERS):
        raise PerformanceComparisonError(
            "performance_marker_capacity_exceeded",
            f"One comparison figure supports at most {len(PERFORMANCE_MARKERS)} "
            "unique legend/marker identities.",
        )
    identity_markers: dict[str, str] = {}
    marker_owners: dict[str, str] = {}
    for identity_index, identity in enumerate(identity_order):
        members = [
            material
            for material in comparison.materials
            if material.legend_identity == identity
        ]
        explicit_markers = list(
            dict.fromkeys(
                material.marker for material in members if material.marker is not None
            )
        )
        if len(explicit_markers) > 1:
            raise PerformanceComparisonError(
                "performance_legend_identity_marker_conflict",
                f"Legend identity {identity!r} declares conflicting markers: "
                + ", ".join(explicit_markers),
            )
        marker = (
            explicit_markers[0]
            if explicit_markers
            else PERFORMANCE_MARKERS[identity_index]
        )
        previous_identity = marker_owners.get(marker)
        if previous_identity is not None and previous_identity != identity:
            raise PerformanceComparisonError(
                "performance_marker_identity_duplicate",
                f"Legend identities {previous_identity!r} and {identity!r} "
                f"reuse marker {marker!r} in one comparison figure.",
            )
        marker_owners[marker] = identity
        identity_markers[identity] = marker

    sample_color = (DEFAULT_PALETTE_COLORS[1:] or DEFAULT_PALETTE_COLORS)[0]
    identity_indexes = {
        identity: index for index, identity in enumerate(identity_order)
    }
    styles: dict[str, dict[str, Any]] = {}
    for material in comparison.materials:
        identity_index = identity_indexes[material.legend_identity]
        marker = identity_markers[material.legend_identity]
        color = (
            (
                DEFAULT_PALETTE_COLORS[
                    1 + identity_index % max(len(DEFAULT_PALETTE_COLORS) - 1, 1)
                ]
                if radar
                else sample_color
            )
            if material.role == "sample"
            else (
                material.marker_line_color
                if material.marker_line_color is not None
                else PERFORMANCE_REFERENCE_COLOR
            )
        )
        marker_fill_color = color if material.role == "sample" else "white"
        if not radar and material.marker_fill_color is not None:
            marker_fill_color = material.marker_fill_color
        styles[material.material_id] = {
            "color": color,
            "marker": marker,
            "marker_fill_color": marker_fill_color,
            "polygon_fill_color": (
                categorical_fill_color(color) if material.role == "sample" else "white"
            ),
            "marker_fill_hide": False,
            "role": material.role,
            "group": material.group,
        }
    return styles
