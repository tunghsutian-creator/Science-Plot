"""Build series, polygons, marker shapes, and line geometry."""

from __future__ import annotations

import math
from typing import Any
from sciplot_core.performance_comparison import (
    PERFORMANCE_RADAR_TEMPLATE_ID,
    PERFORMANCE_SCATTER_TEMPLATE_ID,
)
from sciplot_core.policy import (
    PERFORMANCE_RADAR_GUIDE_COLOR,
    PERFORMANCE_RADAR_GUIDE_LINE_WIDTH_PT,
    PERFORMANCE_RADAR_RING_TRANSPARENCY,
    PERFORMANCE_RADAR_SPOKE_TRANSPARENCY,
    UNIFIED_LINE_WIDTH_PT,
    UNIFIED_MARKER_LINE_WIDTH_PT,
    UNIFIED_MARKER_SIZE_PT,
)

from sciplot_core.performance_veusz.style import (
    _RADAR_RING_LEVELS,
)

from sciplot_core.performance_veusz.legend_layout import (
    _legend_layout,
)


def _radar_cartesian(
    angles_degrees: list[float],
    radii: list[float],
    *,
    x_scale: float,
) -> tuple[list[float], list[float]]:
    x_values = [
        float(radius) * math.cos(math.radians(float(angle))) * x_scale
        for angle, radius in zip(angles_degrees, radii, strict=True)
    ]
    y_values = [
        float(radius) * math.sin(math.radians(float(angle)))
        for angle, radius in zip(angles_degrees, radii, strict=True)
    ]
    return x_values, y_values


def performance_series_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the exact data-bound XY inventory used by Studio and audits."""

    template = str(payload["template"])
    plot_width, plot_height = (
        float(value) for value in payload["layout"]["plot_region_mm"]
    )
    x_scale = plot_height / plot_width
    records: list[dict[str, Any]] = []
    for index, item in enumerate(payload["series"], start=1):
        if template == PERFORMANCE_SCATTER_TEMPLATE_ID:
            x_values = [float(value) for value in item["x_values"]]
            y_values = [float(value) for value in item["y_values"]]
            plot_line_hide = True
        else:
            x_values, y_values = _radar_cartesian(
                [float(value) for value in item["angles_degrees"]],
                [float(value) for value in item["radii"]],
                x_scale=x_scale,
            )
            plot_line_hide = item["role"] == "reference"
        expected_channels = ["marker"] if plot_line_hide else ["line", "marker"]
        records.append(
            {
                "name": f"series_{index}",
                "label": str(item["label"]),
                "legend_key": str(item["label"]),
                "x_name": f"performance_x_{index}",
                "y_name": f"performance_y_{index}",
                "x_values": x_values,
                "y_values": y_values,
                "error_values": [],
                "color": str(item["color"]),
                "line_width_pt": UNIFIED_LINE_WIDTH_PT,
                "line_style": "solid",
                "marker": str(item["marker"]),
                "marker_size_pt": UNIFIED_MARKER_SIZE_PT,
                "marker_thin_factor": 1,
                "marker_fill_color": str(item["marker_fill_color"]),
                "presentation_kind": (
                    "performance_scatter_material"
                    if template == PERFORMANCE_SCATTER_TEMPLATE_ID
                    else "performance_radar_material"
                ),
                "plot_line_hide": plot_line_hide,
                "marker_line_hide": False,
                "raw_points_visible": True,
                "expected_mark_channels": expected_channels,
                "source_artifacts": [
                    {
                        "path": str(payload["source"]),
                        "sha256": str(payload["source_sha256"]),
                    }
                ],
            }
        )
    return records


def _performance_polygons(payload: dict[str, Any]) -> list[dict[str, Any]]:
    polygons: list[dict[str, Any]] = []
    legend_rows = (
        _legend_layout(payload)[1]
        if payload["layout"]["legend_uses_reserved_panel"]
        else []
    )
    for row in legend_rows:
        index = int(row["index"])
        item = row["item"]
        y_position = float(row["y"])
        page_width, page_height = (
            float(value) for value in payload["layout"]["page_size_mm"]
        )
        center_x = float(row["marker_x"])
        radius_x = 0.8 / page_width
        radius_y = 0.8 / page_height
        normalized = _marker_polygon(str(item["marker"]))
        polygons.append(
            {
                "name": f"performance_legend_marker_{index}",
                "role": "material_index_marker",
                "parent": "page",
                "positioning": "relative",
                "x_axis": "x",
                "y_axis": "y",
                "xPos": [center_x + radius_x * float(point[0]) for point in normalized],
                "yPos": [
                    y_position + radius_y * float(point[1]) for point in normalized
                ],
                "line_color": str(item["color"]),
                "line_width_pt": UNIFIED_MARKER_LINE_WIDTH_PT,
                "line_style": "solid",
                "line_transparency": 0,
                "line_hide": False,
                "fill_color": str(item["marker_fill_color"]),
                "fill_transparency": 0,
                "fill_hide": False,
                "material": str(item["material"]),
            }
        )
    if payload["template"] == PERFORMANCE_SCATTER_TEMPLATE_ID:
        for index, envelope in enumerate(payload["envelopes"], start=1):
            polygons.append(
                {
                    "name": f"performance_envelope_{index}",
                    "role": str(envelope.get("role", "observed_sample_extent")),
                    "parent": "graph",
                    "positioning": "axes",
                    "x_axis": "x",
                    "y_axis": "y",
                    "xPos": [float(value) for value in envelope["x_values"]],
                    "yPos": [float(value) for value in envelope["y_values"]],
                    "line_color": str(envelope["line_color"]),
                    "line_width_pt": UNIFIED_LINE_WIDTH_PT,
                    "line_style": "solid",
                    "line_transparency": int(envelope["line_transparency"]),
                    "line_hide": bool(envelope.get("line_hide", False)),
                    "fill_color": str(envelope["fill_color"]),
                    "fill_transparency": int(envelope["fill_transparency"]),
                    "fill_hide": False,
                    "members": list(envelope["members"]),
                    "group": str(envelope["group"]),
                    "interpretation": str(
                        envelope.get(
                            "interpretation",
                            "Observed extent with deterministic visual "
                            "padding; not a confidence region.",
                        )
                    ),
                }
            )
        return polygons

    plot_width, plot_height = (
        float(value) for value in payload["layout"]["plot_region_mm"]
    )
    x_scale = plot_height / plot_width
    for ring_index, radius in enumerate(_RADAR_RING_LEVELS, start=1):
        angles = [
            *[float(value) for value in payload["angles_degrees"]],
            float(payload["angles_degrees"][0]),
        ]
        radii = [radius] * len(angles)
        x_values, y_values = _radar_cartesian(
            angles,
            radii,
            x_scale=x_scale,
        )
        polygons.append(
            {
                "name": f"performance_radar_ring_{ring_index}",
                "role": "radar_grid_ring",
                "parent": "graph",
                "positioning": "axes",
                "x_axis": "x",
                "y_axis": "y",
                "xPos": x_values,
                "yPos": y_values,
                "line_color": PERFORMANCE_RADAR_GUIDE_COLOR,
                "line_width_pt": PERFORMANCE_RADAR_GUIDE_LINE_WIDTH_PT,
                "line_style": "dashed",
                "line_transparency": PERFORMANCE_RADAR_RING_TRANSPARENCY,
                "line_hide": False,
                "fill_color": "white",
                "fill_transparency": 100,
                "fill_hide": True,
                "score": radius,
            }
        )
    for index, item in enumerate(payload["series"], start=1):
        if item["filled_polygon"] is not True:
            continue
        x_values, y_values = _radar_cartesian(
            [float(value) for value in item["angles_degrees"]],
            [float(value) for value in item["radii"]],
            x_scale=x_scale,
        )
        polygons.append(
            {
                "name": f"performance_radar_sample_fill_{index}",
                "role": "sample_score_polygon",
                "parent": "graph",
                "positioning": "axes",
                "x_axis": "x",
                "y_axis": "y",
                "xPos": x_values,
                "yPos": y_values,
                "line_color": str(item["color"]),
                "line_width_pt": UNIFIED_LINE_WIDTH_PT,
                "line_style": "solid",
                "line_transparency": 0,
                "line_hide": False,
                "fill_color": str(item.get("polygon_fill_color", item["color"])),
                "fill_transparency": int(item["fill_transparency"]),
                "fill_hide": False,
                "material": str(item["label"]),
            }
        )
    return polygons


def _marker_polygon(marker: str) -> list[tuple[float, float]]:
    marker = str(marker).strip().casefold()
    if marker == "circle":
        return [
            (
                math.cos(2.0 * math.pi * index / 24.0),
                math.sin(2.0 * math.pi * index / 24.0),
            )
            for index in range(24)
        ]
    if marker in {"ellipsehorz", "ellipsevert"}:
        x_scale = 1.25 if marker == "ellipsehorz" else 0.72
        y_scale = 0.72 if marker == "ellipsehorz" else 1.25
        return [
            (
                x_scale * math.cos(2.0 * math.pi * index / 24.0),
                y_scale * math.sin(2.0 * math.pi * index / 24.0),
            )
            for index in range(24)
        ]
    if marker == "square":
        return [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]
    if marker == "diamond":
        return [(0.0, 1.2), (1.0, 0.0), (0.0, -1.2), (-1.0, 0.0)]
    if marker in {"triangle", "triangledown"}:
        sign = 1.0 if marker == "triangle" else -1.0
        return [
            (0.0, 1.2 * sign),
            (-1.05, -0.75 * sign),
            (1.05, -0.75 * sign),
        ]
    if marker in {"triangleleft", "triangleright"}:
        sign = -1.0 if marker == "triangleleft" else 1.0
        return [
            (1.2 * sign, 0.0),
            (-0.75 * sign, -1.05),
            (-0.75 * sign, 1.05),
        ]
    if marker in {"pentagon", "hexagon", "octogon"}:
        count = {"pentagon": 5, "hexagon": 6, "octogon": 8}[marker]
        return [
            (
                math.cos(math.pi / 2.0 + 2.0 * math.pi * index / count),
                math.sin(math.pi / 2.0 + 2.0 * math.pi * index / count),
            )
            for index in range(count)
        ]
    if marker == "star4":
        return [
            (
                (1.0 if index % 2 == 0 else 0.43)
                * math.cos(math.pi / 2.0 + math.pi * index / 4.0),
                (1.0 if index % 2 == 0 else 0.43)
                * math.sin(math.pi / 2.0 + math.pi * index / 4.0),
            )
            for index in range(8)
        ]
    if marker == "star":
        return [
            (
                (1.0 if index % 2 == 0 else 0.43)
                * math.cos(math.pi / 2.0 + math.pi * index / 5.0),
                (1.0 if index % 2 == 0 else 0.43)
                * math.sin(math.pi / 2.0 + math.pi * index / 5.0),
            )
            for index in range(10)
        ]
    plus = [
        (-0.32, -1.0),
        (0.32, -1.0),
        (0.32, -0.32),
        (1.0, -0.32),
        (1.0, 0.32),
        (0.32, 0.32),
        (0.32, 1.0),
        (-0.32, 1.0),
        (-0.32, 0.32),
        (-1.0, 0.32),
        (-1.0, -0.32),
        (-0.32, -0.32),
    ]
    if marker == "cross":
        cosine = math.sqrt(0.5)
        return [
            (
                x_value * cosine - y_value * cosine,
                x_value * cosine + y_value * cosine,
            )
            for x_value, y_value in plus
        ]
    return plus


def _performance_lines(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload["template"] != PERFORMANCE_RADAR_TEMPLATE_ID:
        return []
    plot_width, plot_height = (
        float(value) for value in payload["layout"]["plot_region_mm"]
    )
    x_scale = plot_height / plot_width
    lines: list[dict[str, Any]] = []
    for index, angle in enumerate(payload["angles_degrees"], start=1):
        radians = math.radians(float(angle))
        lines.append(
            {
                "name": f"performance_radar_spoke_{index}",
                "positioning": "axes",
                "x_axis": "x",
                "y_axis": "y",
                "mode": "point-to-point",
                "xPos": [0.0],
                "yPos": [0.0],
                "xPos2": [math.cos(radians) * x_scale],
                "yPos2": [math.sin(radians)],
                "clip": True,
                "hide": False,
                "line_color": PERFORMANCE_RADAR_GUIDE_COLOR,
                "line_width_pt": PERFORMANCE_RADAR_GUIDE_LINE_WIDTH_PT,
                "line_style": "solid",
                "line_transparency": PERFORMANCE_RADAR_SPOKE_TRANSPARENCY,
                "line_hide": False,
                "arrow_left": "none",
                "arrow_right": "none",
                "fill_hide": True,
            }
        )
    return lines
